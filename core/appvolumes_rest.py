"""
core/appvolumes_rest.py
Cliente REST puro para Omnissa (ex-VMware) App Volumes Manager.
Auth por cookie de sesión (no bearer token como Horizon/vCenter) -- POST
/app_volumes/sessions devuelve un Set-Cookie que hay que reusar en cada
llamada siguiente, acá vía http.cookiejar + urllib opener.

Referencia: "Using Omnissa App Volumes API" (release 2412), developer.omnissa.com/app-volumes-apis.
NOTA: escrito contra la documentación oficial, sin poder probarlo todavía contra un
App Volumes Manager real -- validar el primer run con cuidado (ver log detallado).
"""
import ssl
import json
import http.cookiejar
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

from web.security_utils import normalizar_username


class AppVolumesRestClient:
    """Cliente HTTPS REST para Omnissa App Volumes Manager (API 4.x, 2306+)."""

    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda msg: print(msg, flush=True))

    def log(self, msg: str):
        self._log(msg)

    def _login(self, servidor: str, usuario: str, password: str, dominio: str, ctx):
        """POST /app_volumes/sessions. Devuelve un opener urllib con la cookie de
        sesión ya seteada para reusar en el resto de las llamadas."""
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=ctx),
        )

        # El "usuario" recibido suele ser el email corporativo del operador (con "@" de
        # su propio dominio de correo, no necesariamente el de AD) -- no asumir que un "@"
        # ya presente significa "viene bien formado para este servidor". Se limpia a la
        # parte local primero: habitualmente en App Volumes Manager el
        # login real es el username pelado, sin dominio ni "@" --
        # por eso va primero, para no gastar 3-4 intentos fallidos (y varios segundos) en
        # cada corrida antes de llegar al que siempre funciona acá. Los formatos
        # calificados con dominio quedan de fallback para otros entornos que sí los usen.
        local = normalizar_username(usuario)
        user_formats = [local] if local else []
        if dominio and local:
            user_formats.append(f"{dominio}\\{local}")
            user_formats.append(f"{local}@{dominio}")
        user_formats.append(usuario)
        # Deduplicar preservando el orden de intento.
        vistos = set()
        user_formats = [u for u in user_formats if u and not (u in vistos or vistos.add(u))]

        last_err = None
        for u_fmt in user_formats:
            self.log(f"   [App Volumes REST] Probando login como '{u_fmt}'...")
            try:
                payload = json.dumps({"username": u_fmt, "password": password}).encode("utf-8")
                req = urllib.request.Request(
                    f"https://{servidor}/app_volumes/sessions",
                    data=payload, method="POST",
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                with opener.open(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("success"):
                        self.log(f"   ✅ Login App Volumes exitoso como '{u_fmt}'.")
                        return opener
                    last_err = data.get("error") or "respuesta sin 'success'"
            except urllib.error.HTTPError as e:
                try:
                    body = json.loads(e.read().decode("utf-8"))
                    last_err = body.get("error") or f"HTTP {e.code}"
                except Exception:
                    last_err = f"HTTP {e.code}"
            except Exception as e:
                last_err = str(e)

        raise RuntimeError(f"Fallo de autenticación en App Volumes Manager {servidor}: {last_err}")

    @staticmethod
    def _get(opener, url: str, timeout: float = 20) -> dict:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def obtener_todo(self, servidor: str, usuario: str, password: str, dominio: str = "",
                      progress_callback=None) -> dict:
        """
        Trae aplicaciones (con sus packages anidados), programas por package,
        asignaciones por aplicación, y el activity log completo.

        Retorna:
        {
          "aplicaciones": [{av_id, guid, nombre, descripcion, assignment_count}],
          "paquetes": [{av_id, aplicacion_av_id, guid, nombre, version, lifecycle_stage,
                        delivery, status, attachment_count, size_mb, datastore_name,
                        programas: [{av_id, nombre, publisher, install_location, version}]}],
          "asignaciones": [{av_id, aplicacion_av_id, paquete_av_id, entity_type, entity_name,
                             entity_upn, entity_dn, filtro_prefijo_computadora, delivery}],
          "actividad": [{av_id, source_type, source_name, target_type, target_name,
                          accion, resultado, event_time, admin_user_name}],
        }
        """
        def prog(pct, desc):
            if progress_callback:
                progress_callback(pct, desc)

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        self.log(f"[App Volumes REST] Conectando a https://{servidor} ...")
        opener = self._login(servidor, usuario, password, dominio, ctx)
        self.log(f"   ✅ Sesión App Volumes ({servidor}) activa.")
        prog(0.05, "Sesión App Volumes activa")

        # Catálogo de lifecycle stages (New/Tested/Published/Retired) -- app_products no
        # trae el nombre, solo lifecycle_stage_id numérico. Sic: el endpoint real de Omnissa
        # está mal escrito ("lifcycle", sin la "y") -- no es un typo nuestro, es el contrato real.
        stage_names = {}
        try:
            data_stages = self._get(opener, f"https://{servidor}/app_volumes/lifcycle_stages", timeout=15)
            for st in (data_stages.get("data") or []):
                if isinstance(st, dict) and st.get("id") is not None:
                    stage_names[st["id"]] = st.get("name") or ""
        except Exception as e:
            self.log(f"   ⚠️ [App Volumes] No se pudo traer catálogo de lifecycle stages: {e}")

        # Aplicaciones + packages anidados (vienen en la misma respuesta, sin llamada extra)
        try:
            data_apps = self._get(opener, f"https://{servidor}/app_volumes/app_products", timeout=30)
        except Exception as e:
            raise RuntimeError(f"No se pudo listar aplicaciones de App Volumes en {servidor}: {e}")

        apps_raw = data_apps.get("data") or []
        self.log(f"   [App Volumes REST] {len(apps_raw)} aplicaciones encontradas.")
        prog(0.15, f"{len(apps_raw)} aplicaciones encontradas")

        aplicaciones = []
        paquetes = []
        for app in apps_raw:
            if not isinstance(app, dict):
                continue
            aplicaciones.append({
                "av_id": app.get("id"),
                "guid": app.get("guid"),
                "nombre": app.get("name") or "",
                "descripcion": app.get("description"),
                "assignment_count": app.get("assignment_count") or 0,
            })
            for pkg in (app.get("app_packages") or []):
                if not isinstance(pkg, dict):
                    continue
                paquetes.append({
                    "av_id": pkg.get("id"),
                    "aplicacion_av_id": app.get("id"),
                    "guid": pkg.get("guid"),
                    "nombre": pkg.get("name") or "",
                    "version": pkg.get("version"),
                    "lifecycle_stage": stage_names.get(pkg.get("lifecycle_stage_id"), ""),
                    "delivery": pkg.get("delivery"),
                    "status": pkg.get("status"),
                    "attachment_count": pkg.get("attachment_count") or 0,
                    "size_mb": pkg.get("size_mb"),
                    "datastore_name": pkg.get("datastore_name"),
                    "programas": [],
                })

        # Programas (software real instalado) por package, en paralelo -- puede ser
        # 1 llamada por package, igual que Horizon resolviendo SIDs 1 a 1.
        def _fetch_programs(paquete):
            pid = paquete["av_id"]
            if not pid:
                return
            try:
                data_p = self._get(opener, f"https://{servidor}/app_volumes/app_packages/{pid}/programs", timeout=15)
                for prog_raw in (data_p.get("data") or []):
                    if not isinstance(prog_raw, dict):
                        continue
                    paquete["programas"].append({
                        "av_id": prog_raw.get("id"),
                        "nombre": prog_raw.get("name") or "",
                        "publisher": prog_raw.get("publisher"),
                        "install_location": prog_raw.get("install_location"),
                        "version": prog_raw.get("version"),
                    })
            except Exception as e:
                self.log(f"   ⚠️ [App Volumes] Programas de package '{paquete['nombre']}' (id={pid}): {e}")

        if paquetes:
            self.log(f"   [App Volumes REST] Consultando programas instalados en {len(paquetes)} packages...")
            with ThreadPoolExecutor(max_workers=min(8, len(paquetes))) as ex:
                list(ex.map(_fetch_programs, paquetes))
        prog(0.60, f"Programas de {len(paquetes)} packages recolectados")

        # Asignaciones por aplicación -- verificado 2026-08-12 contra un HAR real capturado
        # del Admin UI (ver .agents si hace falta el detalle): la llamada SIN query params
        # que se usaba antes no devuelve la relación "entities" -- este server la omite si
        # no se pide explícito, quedando 0 asignaciones persistidas siempre pese a traer
        # miles de filas (el av_id/entity_name salían vacíos y el loop de persistencia los
        # descartaba en silencio). Hace falta "include=...,entities,..." + "light=1" +
        # "enabled=true" tal cual los arma el propio Admin UI.
        #
        # Además la entidad NO trae "name"/"account_name"/"distinguished_name" como se
        # asumía -- el único campo real es "upn", y pese al nombre viene en formato
        # "DOMINIO\\usuario" (no user@dominio). Y el package asociado no es un campo plano
        # "app_package_id" en la asignación: cuelga de app_marker.app_package.id.
        asignaciones = []

        def _fetch_assignments(app):
            aid = app.get("id")
            if not aid:
                return
            try:
                url = (
                    f"https://{servidor}/app_volumes/app_products/{aid}/assignments"
                    "?include=app_package,operating_systems,entities,app_marker,filters"
                    "&light=1&enabled=true"
                )
                data_a = self._get(opener, url, timeout=20)
                for asig in (data_a.get("data") or []):
                    if not isinstance(asig, dict):
                        continue
                    filtros = asig.get("filters") or []
                    prefijo = ""
                    for f in filtros:
                        if isinstance(f, dict) and f.get("type") == "ComputerPrefixFilter":
                            prefijo = f.get("value") or ""
                            break
                    paquete_av_id = ((asig.get("app_marker") or {}).get("app_package") or {}).get("id")
                    entidades = asig.get("entities") or []
                    if not entidades:
                        # Sin entidad resuelta (no debería pasar con enabled=true, pero no perder el registro)
                        entidades = [{"entity_type": "Desconocido", "upn": ""}]
                    for ent in entidades:
                        if not isinstance(ent, dict):
                            continue
                        upn_raw = ent.get("upn") or ""
                        # "upn" es en realidad "DOMINIO\\usuario", no un UPN real -- se
                        # limpia a la parte de usuario para poder cruzar contra
                        # Maquina.usuario_asignado (que ya viene limpio del mismo modo).
                        entity_name = upn_raw.split("\\")[-1].strip() if upn_raw else (ent.get("name") or ent.get("account_name") or "")
                        asignaciones.append({
                            "av_id": asig.get("id"),
                            "aplicacion_av_id": aid,
                            "paquete_av_id": paquete_av_id,
                            "entity_type": ent.get("entity_type") or "Desconocido",
                            "entity_name": entity_name,
                            "entity_upn": upn_raw or ent.get("upn"),
                            "entity_dn": ent.get("distinguished_name"),
                            "filtro_prefijo_computadora": prefijo,
                            "delivery": asig.get("delivery"),
                        })
            except Exception as e:
                self.log(f"   ⚠️ [App Volumes] Asignaciones de '{app.get('name')}' (id={aid}): {e}")

        if apps_raw:
            with ThreadPoolExecutor(max_workers=min(8, len(apps_raw))) as ex:
                list(ex.map(_fetch_assignments, apps_raw))
        self.log(f"   [App Volumes REST] {len(asignaciones)} asignaciones (entidad<->aplicación) encontradas.")
        prog(0.85, f"{len(asignaciones)} asignaciones encontradas")

        # Activity log: única fuente con el link real "en vivo" VM+usuario+AppStack (Attach).
        # NOTA: la documentación no especifica un parámetro de fecha/"desde" para filtrar --
        # se trae el log tal como lo devuelve el server. AppVolumesActividad tiene UNIQUE
        # (servidor_id, av_id) así que reimportar filas ya vistas es un no-op idempotente,
        # no genera duplicados aunque se traiga el mismo rango en cada corrida.
        actividad = []
        try:
            data_log = self._get(opener, f"https://{servidor}/app_volumes/activity_logs", timeout=30)
            logs_raw = ((data_log.get("actlogs") or {}).get("logs")) or []
            for entry in logs_raw:
                if not isinstance(entry, dict):
                    continue
                actividad.append({
                    "av_id": entry.get("id"),
                    "source_type": entry.get("source_type"),
                    "source_name": entry.get("source_name"),
                    "target_type": entry.get("target_type"),
                    "target_name": entry.get("target_name"),
                    "accion": entry.get("action"),
                    "resultado": entry.get("log"),
                    "event_time": entry.get("event_time"),
                    "admin_user_name": entry.get("admin_user_name"),
                })
        except Exception as e:
            self.log(f"   ⚠️ [App Volumes] No se pudo traer activity_logs: {e}")

        # Writable Volumes (perfil + datos persistentes por usuario) -- a diferencia del
        # AppStack (solo-lectura, 1 imagen compartida), esto es un VMDK propio por usuario
        # que persiste entre sesiones. Pedido 2026-08-13: cruzar esto contra las alertas de
        # disco, porque es común que un usuario acumule más de un writable sin que nadie lo
        # note (perfil + volúmenes de datos, o uno viejo huérfano) inflando el disco real
        # de la VM más de lo que el ficha muestra a simple vista.
        #
        # Confirmado en vivo 2026-08-13 contra un App Volumes Manager real (la primera
        # versión de este bloque estaba escrita solo contra la doc oficial y tenía 3 bugs
        # reales, corregidos acá):
        #   - "id" viene como STRING ("157") -- guardarlo así rompía la detección de
        #     "sigue existiendo" en inventario.py (comparaba int leído de la DB contra el
        #     string crudo de la API, "not in" daba True siempre, desactivaba TODO en
        #     cada corrida). Casteado a int acá, en el origen.
        #   - El usuario dueño real viene en "owner_name"/"owner_type" (no "entity"/
        #     "entity_type" como decía la doc genérica).
        #   - La VM donde está montado AHORA solo aparece cuando "attached"=="Attached",
        #     anidado en datastore_host.computer.name -- cuando está "Detached" ese campo
        #     es null, no hay VM que reportar (correcto, no es un bug, es el estado real).
        writables = []
        try:
            data_w = self._get(opener, f"https://{servidor}/app_volumes/writables", timeout=30)
            writ_raw = data_w.get("data") or []
            for w in writ_raw:
                if not isinstance(w, dict):
                    continue
                raw_id = w.get("id")
                try:
                    av_id = int(raw_id) if raw_id is not None else None
                except (TypeError, ValueError):
                    av_id = None
                if av_id is None:
                    continue
                datastore_host = w.get("datastore_host") if isinstance(w.get("datastore_host"), dict) else {}
                computer = datastore_host.get("computer") if isinstance(datastore_host.get("computer"), dict) else {}
                total_mb = w.get("total_mb")
                free_mb = w.get("free_mb")
                used_mb = (total_mb - free_mb) if isinstance(total_mb, (int, float)) and isinstance(free_mb, (int, float)) else None
                # owner_upn viene "DOMINIO\\usuario" (igual que en assignments, pese al
                # nombre no es un UPN real) -- se limpia a la parte de usuario para poder
                # matchear contra Maquina.usuario_asignado, mismo criterio que
                # AppVolumesAsignacion en el resto del archivo. owner_name (nombre humano,
                # ej. "Barbara Morana") se guarda aparte solo para mostrar en la ficha.
                owner_upn = w.get("owner_upn") or ""
                entity_name = owner_upn.split("\\")[-1].strip() if owner_upn else ""
                # provisioned_at/owner_email/storage_group agregados 2026-09-07 -- a
                # diferencia de los campos de arriba, NO confirmados contra el payload real
                # (el HAR de 2026-08-13 no los cubrió). Lectura defensiva con variantes de
                # nombre; si ninguna matchea quedan None/"" -- no rompe el resto del bloque.
                provisioned_raw = w.get("created_at") or w.get("created") or w.get("date_created")
                storage_group_val = w.get("storage_group_name") or w.get("storage_group") or ""
                if isinstance(storage_group_val, dict):
                    storage_group_val = storage_group_val.get("name") or ""

                writables.append({
                    "av_id": av_id,
                    "guid": w.get("volume_guid"),
                    "nombre": w.get("name") or "",
                    "tipo": w.get("type") or w.get("display_type") or "",
                    "entity_type": w.get("owner_type") or "",
                    "entity_name": entity_name,
                    "owner_display_name": w.get("owner_name") or "",
                    "owner_email": w.get("owner_email") or w.get("owner_mail") or "",
                    "estado": w.get("status") or "",
                    "attached_to": computer.get("name") or "",
                    "size_mb": w.get("size_mb"),
                    "used_mb": used_mb,
                    "datastore_name": w.get("datastore_name"),
                    "storage_group": storage_group_val,
                    "provisioned_at_raw": provisioned_raw,
                })
            self.log(f"   [App Volumes REST] {len(writables)} writable volumes encontrados.")
            if writ_raw and not writables:
                self.log(f"   ⚠️ [App Volumes] writables vino con {len(writ_raw)} filas pero ninguna se pudo "
                         f"parsear -- revisar formato real, ejemplo crudo: {json.dumps(writ_raw[0])[:500]}")
        except Exception as e:
            self.log(f"   ⚠️ [App Volumes] No se pudo traer writable volumes: {e}")
        prog(0.95, f"{len(writables)} writable volumes encontrados")

        self.log(f"[App Volumes REST] 🎉 {len(aplicaciones)} aplicaciones, {len(paquetes)} packages, "
                 f"{len(asignaciones)} asignaciones, {len(writables)} writable volumes, "
                 f"{len(actividad)} eventos de actividad extraídos de {servidor}.")
        prog(1.0, "Extracción App Volumes completa")

        return {
            "aplicaciones": aplicaciones,
            "paquetes": paquetes,
            "asignaciones": asignaciones,
            "actividad": actividad,
            "writables": writables,
        }
