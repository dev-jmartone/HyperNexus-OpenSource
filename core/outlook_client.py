"""
core/outlook_client.py
Módulo de integración con Microsoft Outlook para resolución de usuarios.
Gestiona la caché local del GAL y clasifica usuarios por empresa
mediante jefatura recursiva y búsqueda por compañeros.
"""
import json
import os
import sys

try:
    import win32com.client
except ImportError:
    win32com = None

# Mapeo configurable de sufijos de dominio de correo a empresa / organización.
# Puede extenderse o sobreescribirse mediante la variable de entorno DOMINIOS_EMPRESA_JSON
_DOMINIOS_DEFAULT = {
    "@corp": "Corporation",
    "@subsidiary": "Subsidiary",
    "@vendor": "Vendor",
    "@partner": "Partner",
}
try:
    DOMINIOS_EMPRESA = json.loads(os.environ.get("DOMINIOS_EMPRESA_JSON", ""))
except Exception:
    DOMINIOS_EMPRESA = _DOMINIOS_DEFAULT

# Ruta por defecto al archivo de caché
if getattr(sys, "frozen", False):
    DATA_DIR = os.path.join(os.path.dirname(sys.executable), "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CACHE_FILE = os.path.join(DATA_DIR, "gal_cache.json")


class OutlookClient:
    """Cliente de Outlook para resolución de usuarios del GAL."""

    def __init__(self, log_callback=None):
        """
        Args:
            log_callback: Función opcional para loguear mensajes (ej. GUI log).
                          Si es None, se imprime por consola.
        """
        self._log = log_callback or (lambda msg: print(msg, flush=True))
        self._namespace = None
        self._offline_mode = False  # True si no se pudo conectar a Outlook ni ADSI
        self._adsi_conn = None  # Conexión ADODB para ADSI/LDAP
        self._entries: list[dict] = []
        self._by_alias: dict[str, dict] = {}
        self._by_email_local: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}
        self._cache_updated = False
        self._user_mappings: dict[str, str] = {}
        self._cargar_mappings()

    # ── Logging ──────────────────────────────────────────────────────

    def log(self, msg: str):
        self._log(msg)

    # ── Conexión a Outlook ───────────────────────────────────────────

    def conectar(self):
        """Establece conexión con Outlook (MAPI) o AD (ADSI) como fallback. Nunca lanza excepción."""
        if win32com is None:
            self.log("[Outlook] pywin32 no instalado. Modo offline activado.")
            self._offline_mode = True
            return

        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        # Intento 1: Outlook Classic via COM/MAPI
        try:
            self.log("[Outlook] Intentando conexión MAPI (Outlook Classic)...")
            outlook = win32com.client.Dispatch("Outlook.Application")
            self._namespace = outlook.GetNamespace("MAPI")
            self._offline_mode = False
            self.log("[Outlook] Conexión MAPI exitosa.")
            return
        except Exception as e:
            self.log(f"[Outlook] MAPI no disponible (posiblemente Nuevo Outlook): {e}")

        # Intento 2: ADSI via ADODB (funciona sin Outlook, usa AD directamente)
        try:
            self.log("[Outlook] Intentando conexión ADSI/LDAP (sin Outlook)...")
            conn = win32com.client.Dispatch("ADODB.Connection")
            conn.Open("Provider=ADsDSOObject;")
            self._adsi_conn = conn
            self._offline_mode = False
            self.log("[Outlook] Conexión ADSI/LDAP exitosa.")
            return
        except Exception as e:
            self.log(f"[Outlook] ADSI tampoco disponible: {e}")

        # Fallback: modo offline con caché local
        self._offline_mode = True
        self.log("[Outlook] ⚠️  Modo offline: se usará únicamente la caché local.")

    # ── Caché del GAL ────────────────────────────────────────────────

    def cargar_cache(self) -> bool:
        """Intenta cargar el índice del GAL desde el archivo local. Retorna True si tuvo éxito."""
        if not os.path.exists(CACHE_FILE):
            return False
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    self._entries = data
                    self._construir_lookups()
                    self.log(f"[Outlook] Cache cargado desde '{os.path.basename(CACHE_FILE)}' ({len(data)} registros).")
                    return True
        except Exception as e:
            self.log(f"[Outlook] Error al cargar cache: {e}. Se reindexará.")
        return False

    def guardar_cache(self):
        """Guarda el índice del GAL actual en el archivo local."""
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, ensure_ascii=False, indent=2)
            self.log(f"[Outlook] Cache guardado ({len(self._entries)} registros).")
        except Exception as e:
            self.log(f"[Outlook] Error al guardar cache: {e}")

    def invalidar_cache(self):
        """Elimina el archivo de caché para forzar reindexación."""
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            self.log("[Outlook] Cache eliminado. Se reindexará en la próxima ejecución.")
        self._entries = []
        self._by_alias = {}
        self._by_email_local = {}
        self._by_name = {}

    # ── Indexación del GAL ───────────────────────────────────────────

    def indexar_gal(self, progress_callback=None):
        """
        Indexa la Libreta de Direcciones Global de Outlook y guarda en caché.
        Args:
            progress_callback: Función opcional (current, total) para reportar progreso.
        """
        if self._namespace is None:
            self.conectar()

        if self._namespace is None:
            self.log("[Outlook] No se pudo establecer conexión MAPI (Outlook Classic). Omitiendo indexación de GAL.")
            return

        lista_global = None
        for lista in self._namespace.AddressLists:
            if lista.AddressListType == 16 or "global" in lista.Name.lower():
                lista_global = lista
                break

        if not lista_global:
            self.log("[Outlook] ⚠️  No se encontró la Libreta de Direcciones Global (GAL). Indexación omitida.")
            return

        self.log(f"[Outlook] Indexando GAL: {lista_global.Name}")
        self.log("[Outlook] Este proceso toma ~3 minutos y se guarda en caché para futuras ejecuciones.")

        entradas_gal = lista_global.AddressEntries
        total = entradas_gal.Count

        PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"
        PR_ACCOUNT = "http://schemas.microsoft.com/mapi/proptag/0x3A00001E"
        PR_COMPANY_NAME = "http://schemas.microsoft.com/mapi/proptag/0x3A16001E"
        PR_DEPARTMENT_NAME = "http://schemas.microsoft.com/mapi/proptag/0x3A18001E"
        PR_TITLE = "http://schemas.microsoft.com/mapi/proptag/0x3A17001E"

        entries = []

        for i in range(1, total + 1):
            try:
                contacto = entradas_gal.Item(i)
            except Exception:
                continue

            nombre = contacto.Name or ""

            smtp = ""
            try:
                smtp = contacto.PropertyAccessor.GetProperty(PR_SMTP_ADDRESS) or ""
            except Exception:
                pass

            alias = ""
            try:
                alias = contacto.PropertyAccessor.GetProperty(PR_ACCOUNT) or ""
            except Exception:
                pass

            company = ""
            try:
                company = contacto.PropertyAccessor.GetProperty(PR_COMPANY_NAME) or ""
            except Exception:
                pass

            department = ""
            try:
                department = contacto.PropertyAccessor.GetProperty(PR_DEPARTMENT_NAME) or ""
            except Exception:
                pass

            title = ""
            try:
                title = contacto.PropertyAccessor.GetProperty(PR_TITLE) or ""
            except Exception:
                pass

            if not smtp:
                smtp = contacto.Address or ""

            entries.append({
                "name": nombre,
                "alias": alias,
                "email": smtp,
                "company": company,
                "department": department,
                "title": title,
                "manager_name": None,
                "manager_email": None
            })

            if i % 1000 == 0 or i == total:
                self.log(f"    Indexando {i}/{total} registros...")
                if progress_callback:
                    progress_callback(i, total)

        self._entries = entries
        self._construir_lookups()
        self.guardar_cache()
        self.log(f"[Outlook] Índice completado: {len(entries)} registros.")

    # ── Inicialización completa ──────────────────────────────────────

    def inicializar(self, progress_callback=None):
        """
        Inicializa el cliente: carga la caché si existe, o indexa el GAL.
        Resiliente: si no hay Outlook ni ADSI, opera en modo offline con caché local.
        """
        if self.cargar_cache():
            self.log("[Outlook] Caché local cargada exitosamente.")
            if self._namespace is None and self._adsi_conn is None and not self._offline_mode:
                # Intentar conectar para resolución online de managers
                self.conectar()
        else:
            # No hay caché: necesitamos conectar e indexar
            self.conectar()
            if not self._offline_mode:
                self.indexar_gal(progress_callback)
            else:
                self.log("[Outlook] Sin conexión y sin caché. Clasificación de empresas limitada.")

    def obtener_contacto_gal(self, identificador: str) -> dict | None:
        """
        Intenta buscar un contacto en la caché local del GAL por alias, email o nombre.
        Si no lo encuentra localmente, intenta resolverlo online y lo cachea.
        """
        if not identificador:
            return None

        ident = identificador.strip().lower()
        if "\\" in ident:
            ident = ident.split("\\")[-1]

        # 1. Buscar en cache por alias
        if ident in self._by_alias:
            return self._by_alias[ident]

        # 2. Buscar por parte local del email
        if ident in self._by_email_local:
            return self._by_email_local[ident]

        # 3. Buscar por email completo
        for entry in self._entries:
            if (entry.get("email") or "").lower() == ident:
                return entry

        # 4. Buscar por nombre exacto
        if ident in self._by_name:
            return self._by_name[ident]

        # 5. Buscar por coincidencia parcial de nombre
        for entry in self._entries:
            if ident in (entry.get("name") or "").lower():
                return entry

        # 5b. Buscar por presencia de todas las palabras (ej: "Gonzalo Slobozian" encuentra "Slobozian, Gonzalo")
        palabras = [p for p in ident.split() if len(p) > 1]
        if palabras:
            for entry in self._entries:
                name_lower = (entry.get("name") or "").lower()
                if all(p in name_lower for p in palabras):
                    return entry

        # 5c. Si no se encontró y el identificador no parece un email, buscar si es el manager_name de algún usuario.
        # Si lo es, usamos su manager_email para buscar en caché o resolver online (ya que resolver emails es 100% efectivo).
        if "@" not in ident:
            for entry in self._entries:
                m_name = (entry.get("manager_name") or "").lower().strip()
                m_email = (entry.get("manager_email") or "").lower().strip()
                if m_name == ident and m_email:
                    # Buscar de nuevo en la caché por este email
                    for ent in self._entries:
                        if (ent.get("email") or "").lower() == m_email:
                            return ent
                    # Si no está en caché local, resolver online con el email exacto
                    self.log(f"      [GAL] Nombre '{identificador}' coincide con manager de '{entry.get('name')}', resolviendo vía email '{m_email}'...")
                    contacto = self._resolver_online_y_cachear(m_email)
                    if contacto:
                        self.guardar_cache()
                        return contacto
                    break

        # 6. Intentar resolver online
        contacto = self._resolver_online_y_cachear(identificador)
        if contacto:
            self.guardar_cache()
            return contacto

        return None

    # ── Clasificación de usuarios ────────────────────────────────────

    def clasificar_empresa_directa(self, email: str) -> str:
        """Clasifica una empresa basándose únicamente en el dominio del email."""
        if not email:
            return ""
        email_lower = email.lower()
        for dominio, empresa in DOMINIOS_EMPRESA.items():
            if dominio in email_lower:
                return empresa
        return ""

    def _resolver_online_y_cachear(self, username: str) -> dict | None:
        """Intenta resolver un usuario online usando Outlook COM y lo agrega a la caché."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        if self._namespace is None:
            if self._adsi_conn is not None:
                # Fallback: consultar vía ADSI/LDAP en Active Directory
                contacto = self._query_adsi(username)
                if contacto:
                    alias = contacto.get("alias") or username
                    email = contacto.get("email") or ""
                    nombre = contacto.get("name") or username

                    item = {
                        "name": nombre,
                        "alias": alias,
                        "email": email,
                        "company": contacto.get("company", ""),
                        "department": contacto.get("department", ""),
                        "title": contacto.get("title", ""),
                        "manager_name": contacto.get("manager_name", ""),
                        "manager_email": "",
                        "search_aliases": [username]
                    }
                    self._entries.append(item)
                    if alias:
                        self._by_alias[alias.lower()] = item
                    if username:
                        self._by_alias[username.lower()] = item
                    if email and "@" in email:
                        local = email.split("@")[0].lower()
                        self._by_email_local[local] = item
                    if nombre:
                        self._by_name[nombre.lower()] = item

                    self._cache_updated = True
                    self.log(f"      [+] Usuario '{username}' (ADSI) resuelto y cacheado -> Email: {email}")
                    return item
                return None
            
            try:
                self.conectar()
            except Exception:
                return None

        try:
            recipient = self._namespace.CreateRecipient(username)
            if recipient.Resolve():
                contacto = recipient.AddressEntry
                
                alias = ""
                email = ""
                company = ""
                department = ""
                title = ""
                nombre = contacto.Name or username

                PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"
                PR_ACCOUNT = "http://schemas.microsoft.com/mapi/proptag/0x3A00001E"
                PR_COMPANY_NAME = "http://schemas.microsoft.com/mapi/proptag/0x3A16001E"
                PR_DEPARTMENT_NAME = "http://schemas.microsoft.com/mapi/proptag/0x3A18001E"
                PR_TITLE = "http://schemas.microsoft.com/mapi/proptag/0x3A17001E"

                try:
                    email = contacto.PropertyAccessor.GetProperty(PR_SMTP_ADDRESS) or ""
                except Exception:
                    pass

                try:
                    alias = contacto.PropertyAccessor.GetProperty(PR_ACCOUNT) or ""
                except Exception:
                    pass

                try:
                    company = contacto.PropertyAccessor.GetProperty(PR_COMPANY_NAME) or ""
                except Exception:
                    pass

                try:
                    department = contacto.PropertyAccessor.GetProperty(PR_DEPARTMENT_NAME) or ""
                except Exception:
                    pass

                try:
                    title = contacto.PropertyAccessor.GetProperty(PR_TITLE) or ""
                except Exception:
                    pass

                if contacto.AddressEntryUserType == 0:  # olExchangeUserAddressEntry
                    try:
                        ex_user = contacto.GetExchangeUser()
                        if ex_user:
                            if not alias:
                                alias = ex_user.Alias or ""
                            if not email:
                                email = ex_user.PrimarySmtpAddress or ""
                            if not company:
                                company = ex_user.CompanyName or ""
                            if not department:
                                department = ex_user.Department or ""
                            if not title:
                                title = ex_user.JobTitle or ""
                    except Exception:
                        pass

                if not email:
                    email = contacto.Address or ""

                if not alias:
                    if email and "@" in email:
                        alias = email.split("@")[0]
                    else:
                        alias = username

                # Buscar si ya existe el usuario con este alias resuelto en nuestra caché
                existing_item = self._by_alias.get(alias.lower())
                if existing_item:
                    if "search_aliases" not in existing_item:
                        existing_item["search_aliases"] = []
                    if username.lower() not in [x.lower() for x in existing_item["search_aliases"]]:
                        existing_item["search_aliases"].append(username)
                    self._by_alias[username.lower()] = existing_item
                    self._cache_updated = True
                    self.log(f"      [+] Vinculado alias alternativo '{username}' al usuario existente '{alias}'")
                    return existing_item

                item = {
                    "name": nombre,
                    "alias": alias,
                    "email": email,
                    "company": company,
                    "department": department,
                    "title": title,
                    "manager_name": None,
                    "manager_email": None,
                    "search_aliases": [username]
                }

                self._entries.append(item)
                if alias:
                    self._by_alias[alias.lower()] = item
                if username:
                    self._by_alias[username.lower()] = item
                if email and "@" in email:
                    local = email.split("@")[0].lower()
                    self._by_email_local[local] = item
                if nombre:
                    self._by_name[nombre.lower()] = item

                self._cache_updated = True
                self.log(f"      [+] Usuario '{username}' (alias real '{alias}') resuelto online y cacheado -> Email: {email}")
                return item
        except Exception as e:
            self.log(f"      [-] Error resolviendo online '{username}': {e}")
        
        return None

    def _resolve_manager_online(self, item: dict) -> tuple[str, str]:
        """Busca el manager de un usuario online usando Outlook COM."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        if item.get("manager_email") is not None:
            return item.get("manager_name", ""), item.get("manager_email", "")

        email = item.get("email") or item.get("name")
        if not email:
            item["manager_name"] = ""
            item["manager_email"] = ""
            self._cache_updated = True
            return "", ""

        if self._namespace is None:
            if self._adsi_conn is not None:
                if item.get("manager_name"):
                    return item["manager_name"], ""
                m_info = self._query_adsi(email)
                if m_info and m_info.get("manager_name"):
                    item["manager_name"] = m_info["manager_name"]
                    item["manager_email"] = ""
                    self._cache_updated = True
                    return m_info["manager_name"], ""
            
            item["manager_name"] = ""
            item["manager_email"] = ""
            self._cache_updated = True
            return "", ""

        try:
            recipient = self._namespace.CreateRecipient(email)
            if recipient.Resolve():
                contacto = recipient.AddressEntry
                ex_user = contacto.GetExchangeUser()
                if ex_user:
                    manager = ex_user.Manager
                    if manager:
                        m_name = manager.Name or ""
                        m_email = ""
                        try:
                            PR_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"
                            m_email = manager.PropertyAccessor.GetProperty(PR_SMTP) or ""
                        except Exception:
                            pass
                        if not m_email:
                            try:
                                m_ex = manager.GetExchangeUser()
                                if m_ex:
                                    m_email = m_ex.PrimarySmtpAddress or ""
                            except Exception:
                                pass
                        if not m_email:
                            m_email = manager.Address or ""

                        item["manager_name"] = m_name
                        item["manager_email"] = m_email
                        self._cache_updated = True
                        return m_name, m_email
        except Exception:
            pass

        item["manager_name"] = ""
        item["manager_email"] = ""
        self._cache_updated = True
        return "", ""

    def _obtener_empresa_por_companeros(self, item: dict, ya_visitados: set) -> str:
        """Busca compañeros con mismo departamento/rol que tengan jefatura definida."""
        user_dept = (item.get("department") or "").strip().lower()
        user_title = (item.get("title") or "").strip().lower()
        user_company = (item.get("company") or "").strip().lower()
        user_email = (item.get("email") or "").strip().lower()

        if not user_dept:
            return "externo"

        companeros = []
        for peer in self._entries:
            p_email = (peer.get("email") or "").strip().lower()
            if p_email == user_email:
                continue
            p_dept = (peer.get("department") or "").strip().lower()
            p_title = (peer.get("title") or "").strip().lower()
            p_company = (peer.get("company") or "").strip().lower()

            if p_dept == user_dept:
                coincide_rol = user_title and (p_title == user_title)
                coincide_empresa = user_company and (p_company == user_company)
                if coincide_rol or coincide_empresa:
                    companeros.append(peer)

        for peer in companeros:
            m_name, m_email = self._resolve_manager_online(peer)
            if m_email:
                local = m_email.split("@")[0].lower() if "@" in m_email else ""
                manager_item = self._by_email_local.get(local) or self._by_name.get(m_name.lower())
                if manager_item:
                    empresa = self._obtener_empresa_usuario(manager_item, ya_visitados)
                else:
                    empresa = self.clasificar_empresa_directa(m_email)
                if empresa and empresa != "externo":
                    self.log(f"      [+] Clasificado por compañero '{peer.get('name')}' -> '{empresa}'")
                    # Asignar manager al usuario actual
                    item["manager_name"] = m_name
                    item["manager_email"] = m_email
                    self._cache_updated = True
                    return empresa

        return "externo"

    def _obtener_empresa_usuario(self, item: dict, ya_visitados: set = None) -> str:
        """Determina la empresa de un contacto (recursivo por jefatura y compañeros)."""
        if ya_visitados is None:
            ya_visitados = set()

        email = item.get("email") or ""
        if not email:
            return "externo"

        if email.lower() in ya_visitados:
            return "externo"
        ya_visitados.add(email.lower())

        email_lower = email.lower()

        # Siempre resolver el manager online si no lo tenemos en caché
        m_name, m_email = self._resolve_manager_online(item)

        # Caso externo / contratista (configurable por variable EXTERNAL_DOMAIN_KEYWORDS)
        ext_keywords = [
            k.strip() for k in os.environ.get("EXTERNAL_DOMAIN_KEYWORDS", "externo,contractor,vendor,consultant,ext.").lower().split(",")
            if k.strip()
        ]
        if any(kw in email_lower for kw in ext_keywords):
            if m_email:
                local = m_email.split("@")[0].lower() if "@" in m_email else ""
                manager_item = self._by_email_local.get(local) or self._by_name.get(m_name.lower())
                if manager_item:
                    return self._obtener_empresa_usuario(manager_item, ya_visitados)
                else:
                    return self.clasificar_empresa_directa(m_email)

            return self._obtener_empresa_por_companeros(item, ya_visitados)

        # Caso interno
        return self.clasificar_empresa_directa(email)

    def clasificar_usuario(self, username: str) -> dict:
        """
        Clasifica un único username y retorna un diccionario con la información.
        Returns:
            dict con keys: usuario, empresa, email, manager_name, encontrado
        """
        username_clean = username.lower().strip()
        # Aplicar mapeo de usuario si existe (ej. etcdacac -> dcaceres)
        mapped_username = self._user_mappings.get(username_clean, username_clean)

        # 1. Buscar en caché usando el nombre (o mapeado)
        item = (
            self._by_alias.get(mapped_username)
            or self._by_email_local.get(mapped_username)
            or self._by_name.get(mapped_username)
        )

        # 2. Si no se encuentra, ver si tiene un prefijo de organización conocido y buscar el resto en caché
        prefix_used = ""
        remainder = ""
        if not item:
            for pref in ["etc", "vax", "vrh", "vsi", "vtc", "vgr"]:
                if mapped_username.startswith(pref) and len(mapped_username) > len(pref):
                    prefix_used = pref
                    remainder = mapped_username[len(pref):]
                    item = (
                        self._by_alias.get(remainder)
                        or self._by_email_local.get(remainder)
                        or self._by_name.get(remainder)
                    )
                    if item:
                        break

        # 3. Si no está en caché, intentar resolver online con el nombre buscado
        if not item:
            item = self._resolver_online_y_cachear(mapped_username)

        # 4. Si falló y tenemos un alias sin prefijo (remainder), intentar resolver online el remainder
        if not item and remainder:
            item = self._resolver_online_y_cachear(remainder)
            if item:
                # Vincular también el username original buscado a este item para el futuro
                if "search_aliases" not in item:
                    item["search_aliases"] = []
                if username_clean not in [x.lower() for x in item["search_aliases"]]:
                    item["search_aliases"].append(username_clean)
                self._by_alias[username_clean] = item
                self._cache_updated = True

        if item:
            empresa = self._obtener_empresa_usuario(item)
            return {
                "usuario": username,
                "empresa": empresa,
                "email": item.get("email", ""),
                "manager_name": item.get("manager_name", ""),
                "department": item.get("department", ""),
                "title": item.get("title", ""),
                "encontrado": True,
            }
        else:
            return {
                "usuario": username,
                "empresa": "no encontrado",
                "email": "",
                "manager_name": "",
                "department": "",
                "title": "",
                "encontrado": False,
            }

    def clasificar_usuarios(self, usernames: list[str], progress_callback=None) -> list[dict]:
        """
        Clasifica una lista de usernames y retorna la lista de resultados.
        Args:
            usernames: Lista de usernames a clasificar.
            progress_callback: Función opcional (current, total) para reportar progreso.
        Returns:
            Lista de dicts con la clasificación de cada usuario.
        """
        self._cache_updated = False
        resultados = []

        for index, username in enumerate(usernames, 1):
            resultado = self.clasificar_usuario(username)
            resultados.append(resultado)

            if index % 10 == 0 or index == len(usernames):
                self.log(f"    Clasificando usuarios: {index}/{len(usernames)}...")
                if progress_callback:
                    progress_callback(index, len(usernames))

        # Si se resolvieron nuevos managers, guardar la caché actualizada
        if self._cache_updated:
            self.guardar_cache()

        return resultados

    def buscar_usuario(self, username: str) -> dict | None:
        """Busca un usuario en el índice sin clasificarlo. Retorna el dict crudo o None."""
        username_clean = username.lower().strip()
        return (
            self._by_alias.get(username_clean)
            or self._by_email_local.get(username_clean)
            or self._by_name.get(username_clean)
        )

    # ── Helpers internos ─────────────────────────────────────────────

    def _construir_lookups(self):
        """Construye los diccionarios de búsqueda rápida a partir de self._entries."""
        self._by_alias = {}
        self._by_email_local = {}
        self._by_name = {}

        for item in self._entries:
            alias = item.get("alias")
            email = item.get("email")
            name = item.get("name")

            if alias:
                self._by_alias[alias.lower()] = item
            if email and "@" in email:
                local = email.split("@")[0]
                if local:
                    self._by_email_local[local.lower()] = item
            if name:
                self._by_name[name.lower()] = item

            # Indexar también por alias alternativos de búsqueda (autoresueltos)
            for alt in item.get("search_aliases", []):
                self._by_alias[alt.lower()] = item

    @property
    def total_registros(self) -> int:
        return len(self._entries)

    def _cargar_mappings(self):
        """Carga el mapeo de usuarios modificados (ej. etcdacac -> dcaceres) desde json."""
        mapping_file = os.path.join(DATA_DIR, "user_mapping.json")
        if not os.path.exists(mapping_file):
            # Inicializar con el ejemplo sugerido por el usuario
            default_mappings = {
                "etcdacac": "dcaceres"
            }
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(mapping_file, "w", encoding="utf-8") as f:
                    json.dump(default_mappings, f, ensure_ascii=False, indent=2)
                self._user_mappings = {k.lower().strip(): v.lower().strip() for k, v in default_mappings.items()}
                self.log(f"[Outlook] Archivo de mapeos de usuario creado por defecto: 'data/user_mapping.json'")
            except Exception as e:
                self.log(f"[Outlook] Error al crear mappings por defecto: {e}")
        else:
            try:
                with open(mapping_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._user_mappings = {k.lower().strip(): v.lower().strip() for k, v in data.items()}
                        self.log(f"[Outlook] {len(self._user_mappings)} mapeos de usuario cargados desde 'data/user_mapping.json'")
            except Exception as e:
                self.log(f"[Outlook] Error al cargar mappings: {e}")

    def buscar_en_gal(self, termino: str) -> list[dict]:
        """
        Busca contactos en la caché local del GAL que coincidan con el término
        (en nombre, alias, email, departamento, etc.).
        """
        if not self._entries:
            self.cargar_cache()

        term = termino.strip().lower()
        if not term:
            return []

        resultados = []
        for entry in self._entries:
            name = (entry.get("name") or "").lower()
            alias = (entry.get("alias") or "").lower()
            email = (entry.get("email") or "").lower()
            company = (entry.get("company") or "").lower()
            dept = (entry.get("department") or "").lower()

            if (term in name or
                term in alias or
                term in email or
                term in company or
                term in dept):
                resultados.append(entry)

            if len(resultados) >= 100:  # Limitar para evitar saturar la interfaz
                break
        return resultados

    def obtener_companeros_equipo(self, contacto: dict) -> list[dict]:
        """
        Retorna la lista de compañeros de equipo (personas con el mismo manager,
        o del mismo departamento y empresa si no hay manager) ordenados alfabéticamente.
        """
        if not contacto:
            return []
        
        m_name = (contacto.get("manager_name") or "").strip().lower()
        m_email = (contacto.get("manager_email") or "").strip().lower()
        my_email = (contacto.get("email") or "").strip().lower()
        my_dept = (contacto.get("department") or "").strip().lower()
        my_company = (contacto.get("company") or "").strip().lower()
        
        peers = []
        for entry in self._entries:
            e_email = (entry.get("email") or "").strip().lower()
            if e_email == my_email:
                continue
            
            # 1. Por Manager
            if m_email or m_name:
                e_m_email = (entry.get("manager_email") or "").strip().lower()
                e_m_name = (entry.get("manager_name") or "").strip().lower()
                if (m_email and e_m_email == m_email) or (m_name and e_m_name == m_name):
                    peers.append(entry)
                    continue
            
            # 2. Si no hay manager, buscar por mismo departamento y empresa
            if not m_email and not m_name and my_dept and my_company:
                e_dept = (entry.get("department") or "").strip().lower()
                e_company = (entry.get("company") or "").strip().lower()
                if e_dept == my_dept and e_company == my_company:
                    peers.append(entry)
                    
        # Ordenar por nombre
        peers.sort(key=lambda x: (x.get("name") or "").lower())
        return peers

    def _query_adsi(self, identifier: str) -> dict | None:
        """Realiza una consulta a Active Directory (ADSI/LDAP) para resolver un usuario."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        if not self._adsi_conn:
            return None

        # 1. Obtener Base DN de forma resiliente
        base_dn = None
        ldap_prefix = "LDAP://"
        
        try:
            root_dse = win32com.client.GetObject("LDAP://rootDSE")
            base_dn = root_dse.Get("defaultNamingContext")
        except Exception:
            # Fallback 1: usar variables de entorno de dominio
            import os
            dom = os.environ.get("USERDNSDOMAIN") or os.environ.get("USERDOMAIN")
            if dom:
                try:
                    ldap_prefix = f"LDAP://{dom}/"
                    root_dse = win32com.client.GetObject(f"LDAP://{dom}/rootDSE")
                    base_dn = root_dse.Get("defaultNamingContext")
                except Exception as e:
                    self.log(f"[Outlook ADSI] Error al conectar con dominio {dom}: {e}")
            
        if not base_dn:
            self.log("[Outlook ADSI] No se pudo obtener el defaultNamingContext de Active Directory.")
            return None

        ident = identifier.strip()
        if "\\" in ident:
            ident = ident.split("\\")[-1]

        # Evitar inyección LDAP saneando comillas/paréntesis simples
        ident_safe = ident.replace("(", "\\28").replace(")", "\\29").replace("*", "\\2a")

        query = f"<{ldap_prefix}{base_dn}>;(&(objectCategory=user)(|(sAMAccountName={ident_safe})(mail={ident_safe})(cn={ident_safe})));name,sAMAccountName,mail,company,department,title,manager;subtree"

        try:
            cmd = win32com.client.Dispatch("ADODB.Command")
            cmd.ActiveConnection = self._adsi_conn
            cmd.CommandText = query
            cmd.Properties("Page Size").Value = 10
            
            res = cmd.Execute()
            recordset = res[0]
            
            if not recordset.EOF:
                name = recordset.Fields('name').Value or ""
                alias = recordset.Fields('sAMAccountName').Value or ""
                email = recordset.Fields('mail').Value or ""
                company = recordset.Fields('company').Value or ""
                department = recordset.Fields('department').Value or ""
                title = recordset.Fields('title').Value or ""
                manager_dn = recordset.Fields('manager').Value or ""
                
                manager_name = ""
                if manager_dn:
                    try:
                        for part in manager_dn.split(","):
                            if part.upper().startswith("CN="):
                                manager_name = part.split("=")[-1]
                                break
                    except Exception:
                        pass
                
                contacto = {
                    "name": name,
                    "alias": alias,
                    "email": email,
                    "company": company,
                    "department": department,
                    "title": title,
                    "manager_name": manager_name,
                    "manager_email": "",
                    "encontrado": True
                }
                recordset.Close()
                return contacto
                
            recordset.Close()
        except Exception as e:
            self.log(f"[Outlook ADSI Error] Fallo al buscar '{identifier}': {e}")
            
        return None


