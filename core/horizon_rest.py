"""
core/horizon_rest.py
Cliente de extracción 100% PURE REST API para VMware / Omnissa Horizon Connection Server.
Elimina la dependencia de PowerShell/PowerCLI y ejecuta consultas multihilo ultra-rápidas.
"""
import ssl
import json
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

from web.security_utils import normalizar_username

class HorizonRestClient:
    """Cliente HTTPS REST para Omnissa / VMware Horizon Connection Server."""

    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda msg: print(msg, flush=True))

    def log(self, msg: str):
        self._log(msg)

    def _resolver_sids(self, servidor: str, headers: dict, ctx, sids) -> dict:
        """Resuelve SIDs de AD a nombre de usuario real vía External API de Horizon
        (GET /rest/external/v1/ad-users-or-groups/{sid}). La API de sessions/machines
        de este Connection Server solo manda el SID crudo (S-1-5-21-...), nunca el
        nombre — sin esto 'usuario asignado' queda vacío aunque la VM SÍ tenga usuario.
        No hay endpoint batch, es 1 llamada por SID; el caller cachea el resultado en
        DB para no repetir esto en cada corrida del scheduler."""
        resultado = {}

        def _uno(sid):
            try:
                url = f"https://{servidor}/rest/external/v1/ad-users-or-groups/{sid}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    # login_name/UPN son el username real (sam account / user@dominio). display_name
                    # es el nombre para mostrar ("Jose Martone") -- usarlo acá contamina
                    # Maquina.usuario_asignado y de ahí DirectorioUsuario.username con nombres con
                    # espacio en vez del login, duplicando cada persona en el directorio (bug real:
                    # ~47% de directorio_usuarios terminó así). Solo se cae a display_name como
                    # último recurso si Horizon no informó ningún login utilizable.
                    nombre = (data.get("login_name") or data.get("user_principal_name")
                              or data.get("display_name") or "")
                    return sid, nombre
            except Exception as e:
                self.log(f"   ⚠️ [Horizon] No se pudo resolver SID '{sid}' a usuario: {e}")
                return sid, ""

        sids = list(sids)
        if not sids:
            return resultado
        with ThreadPoolExecutor(max_workers=min(8, len(sids))) as ex:
            for sid, nombre in ex.map(_uno, sids):
                if nombre:
                    resultado[sid] = nombre
        return resultado

    def login(self, servidor: str, usuario: str, password: str, dominio: str = "", ctx=None) -> str:
        """POST /rest/login — devuelve el token Bearer. Factorizado aparte de obtener_todo
        para poder validar una credencial (¿esta clave realmente autentica?) sin tener que
        disparar una extracción completa."""
        if not servidor or not usuario or not password:
            raise RuntimeError("Servidor, usuario y contraseña son obligatorios.")

        if ctx is None:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        user_clean = usuario.strip()
        sam_user = normalizar_username(user_clean) if user_clean else ""

        login_payload = json.dumps({
            "username": sam_user,
            "password": password,
            "domain": dominio or os.environ.get("HORIZON_DEFAULT_DOMAIN", "CORP")
        }).encode("utf-8")

        req = urllib.request.Request(
            f"https://{servidor}/rest/login",
            data=login_payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST"
        )

        access_token = None
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                access_token = data.get("access_token")
        except Exception as e:
            raise RuntimeError(f"Fallo al autenticar en Horizon REST API ({servidor}): {e}")

        if not access_token:
            raise RuntimeError(f"No se obtuvo token Bearer desde Horizon REST ({servidor}).")

        return access_token

    def obtener_todo(self, servidor: str, usuario: str, password: str, dominio: str = "",
                     progress_callback=None, sid_cache: dict | None = None) -> dict:
        """
        Consulta endpoints REST API de Horizon Connection Server:
        - POST /rest/login (Token de acceso Bearer)
        - GET  /rest/inventory/v1/desktop-pools (Pools)
        - GET  /rest/inventory/v1/sessions (Sesiones conectadas/desconectadas)
        - GET  /rest/inventory/v1/machines (Máquinas VDI)
        """
        if progress_callback:
            progress_callback(1, 5, "Conectando a Horizon REST API...")

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        access_token = self.login(servidor, usuario, password, dominio, ctx)
        self.log(f"[Horizon REST] ✅ Autenticación exitosa en {servidor}.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }

        def _unwrap_list(val):
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for k in ("value", "items", "data"):
                    if isinstance(val.get(k), list):
                        return val[k]
            return []

        # 1. Desktop Pools
        # v1 de este endpoint solo trae id/name/type/source/settings — sin referencia a la
        # golden image. v2 agrega provisioning_settings (con parent_vm_id), que es lo que
        # necesitamos para detectar MASTER. Confirmado contra servidor real: parent_vm_id
        # viene en formato "vm-XXXXX", igual al ExternalId que ya guarda vCenter — matchean
        # directo sin transformar nada.
        pools = []
        pool_id_to_name = {}
        master_refs = set()
        try:
            req_p = urllib.request.Request(f"https://{servidor}/rest/inventory/v2/desktop-pools", headers=headers)
            with urllib.request.urlopen(req_p, context=ctx, timeout=30) as resp_p:
                p_raw = json.loads(resp_p.read().decode("utf-8"))
                p_list = _unwrap_list(p_raw)
                for p in p_list:
                    p_name = p.get("name") or p.get("id") or "Pool"
                    p_id = p.get("id")
                    if p_id:
                        pool_id_to_name[p_id] = p_name
                    # Errores de provisioning: confirmado en vivo contra servidor real —
                    # "last_provisioning_error" (full clone / genérico) o
                    # "instant_clone_pending_image_state" == "FAILED" (instant clone,
                    # el mensaje real viene en "instant_clone_pending_image_error").
                    # "last_provisioning_error_time" solo (sin mensaje) es residuo viejo
                    # de un error ya resuelto — no cuenta como error actual.
                    prov = p.get("provisioning_status_data") or {}
                    prov_error = prov.get("last_provisioning_error") or ""
                    if not prov_error and prov.get("instant_clone_pending_image_state") == "FAILED":
                        prov_error = prov.get("instant_clone_pending_image_error") or "Falló la personalización del clon (sin detalle del agente)."

                    parent_vm_id = (p.get("provisioning_settings") or {}).get("parent_vm_id")

                    pools.append({
                        "Name": p_name,
                        "DisplayName": p.get("display_name") or p_name,
                        "Type": p.get("type") or "Automated",
                        "UserAssignment": p.get("user_assignment") or "Dedicated",
                        "Enabled": p.get("enabled", True),
                        "ProvisioningError": prov_error,
                        # MoRef real del master configurado en el pool (provisioning_settings,
                        # siempre presente en pools instant-clone) -- distinto de
                        # Pool.master_vm_actual (que solo se llena si Horizon alguna vez
                        # generó un audit-event "Image Publish...succeeded" para ese pool,
                        # cosa que en la práctica pasó para 3 de 48 pools nada más). Con esto
                        # se puede saber el master real de un pool aunque nunca se haya
                        # republicado la imagen desde que arrancó a monitorearse.
                        "ParentVmId": parent_vm_id or "",
                        # Id de la Farm que respalda este pool si es tipo RDS -- riesgo:
                        # nombre de campo no confirmado contra servidor real, se prueban
                        # ambas variantes (ver Task 2 del plan de Granja RDS).
                        "FarmId": p.get("farm_id") or (p.get("desktop_pool_rds_data") or {}).get("farm_id") or "",
                    })

                    if parent_vm_id:
                        master_refs.add(parent_vm_id)
        except Exception as e_p:
            self.log(f"   ⚠️ Error consultando pools REST: {e_p}")

        if pools and not master_refs:
            self.log("   ℹ️ No se detectaron referencias de golden image (parent_vm_id) en desktop-pools "
                      "de este servidor — normal si son pools manuales/full-clone sin instant-clone.")

        # 2. Sessions
        sessions_map = {}
        raw_sessions_list = []
        try:
            req_s = urllib.request.Request(f"https://{servidor}/rest/inventory/v1/sessions", headers=headers)
            with urllib.request.urlopen(req_s, context=ctx, timeout=30) as resp_s:
                s_raw = json.loads(resp_s.read().decode("utf-8"))
                s_list = _unwrap_list(s_raw)
                for s in s_list:
                    m_id = s.get("machine_id") or s.get("machineId")
                    m_name = s.get("machine_name") or s.get("machineName") or s.get("dns_name") or s.get("name") or ""
                    # La API actual manda el usuario como SID (user_id), no como texto —
                    # user_name/username quedan como fallback por si una versión vieja
                    # de Horizon sí lo manda plano. Se resuelve el SID más abajo.
                    user_sid = s.get("user_id") or s.get("userId") or ""
                    username = s.get("user_name") or s.get("username") or s.get("user") or ""
                    state = (s.get("state") or s.get("session_state") or s.get("status") or "CONNECTED").upper()

                    # Confirmado en vivo 2026-08-13 contra un Connection Server real: el IP/nombre
                    # del cliente NO son campos planos "client_ip"/"client_name" (esa era una
                    # suposición sin verificar, igual que el bug de los Writable Volumes de App
                    # Volumes el mismo día) -- vienen anidados en "client_data" ({"address":
                    # "10.45.1.85", "name": "MGT", "type": "WINDOWS", ...}). De paso, también hay
                    # "security_gateway_data" ({"address":..., "domain_name":"gw-uag01...",
                    # "location":"EXTERNAL"|"INTERNAL"}) -- el gateway/UAG real que atendió la
                    # sesión, útil para diagnosticar problemas de conectividad o balanceo.
                    client_data = s.get("client_data") if isinstance(s.get("client_data"), dict) else {}
                    gateway_data = s.get("security_gateway_data") if isinstance(s.get("security_gateway_data"), dict) else {}
                    # Campos agregados 2026-09-07 -- ClientType SÍ confirmado en el HAR real de
                    # 2026-08-13 (el "..." del comentario de arriba, mismo objeto client_data
                    # que ya da ClientName/ClientIP). ClientVersion/SessionProtocol/SessionType/
                    # SessionIdleSeconds NO verificados contra un HAR real todavía -- lectura
                    # defensiva con .get(), quedan "" o None si el nombre no matchea (sin
                    # romper nada, mismo criterio que el resto de este archivo).
                    idle_raw = s.get("idle_duration") or s.get("idle_duration_seconds") or s.get("idleDurationSeconds")
                    sess_item = {
                        "MachineId": m_id or "",
                        "MachineName": m_name,
                        "MachineOrRDSServerName": m_name,
                        "UserSid": user_sid,
                        "UserName": username,
                        "ClientName": client_data.get("name") or "",
                        "ClientIP": client_data.get("address") or "",
                        "ClientType": client_data.get("type") or "",
                        "ClientVersion": client_data.get("version") or client_data.get("client_version") or "",
                        "GatewayName": gateway_data.get("domain_name") or "",
                        "GatewayIP": gateway_data.get("address") or "",
                        "GatewayLocation": gateway_data.get("location") or "",
                        "SessionProtocol": s.get("session_protocol") or s.get("protocol") or "",
                        "SessionType": s.get("session_type") or s.get("sessionType") or "",
                        "SessionIdleSeconds": idle_raw if isinstance(idle_raw, (int, float)) else None,
                        "State": state,
                        "SessionState": state,
                        "StartTime": s.get("start_time") or s.get("startTime") or ""
                    }
                    raw_sessions_list.append(sess_item)
                    if m_id:
                        sessions_map[m_id] = sess_item
                    if m_name:
                        sessions_map[m_name.lower().strip()] = sess_item
        except Exception as e_s:
            self.log(f"   ⚠️ Error consultando sesiones REST: {e_s}")

        # 3. Machines
        vms = []
        try:
            req_m = urllib.request.Request(f"https://{servidor}/rest/inventory/v1/machines", headers=headers)
            with urllib.request.urlopen(req_m, context=ctx, timeout=45) as resp_m:
                m_raw = json.loads(resp_m.read().decode("utf-8"))
                m_list = _unwrap_list(m_raw)
                for m in m_list:
                    m_id = m.get("id")
                    m_name = m.get("name") or m.get("dns_name") or ""
                    m_name_clean = m_name.lower().strip()
                    p_id = m.get("desktop_pool_id")
                    pool_name = pool_id_to_name.get(p_id) or m.get("desktop_pool_name") or "Estática"

                    sess = sessions_map.get(m_id) or sessions_map.get(m_name_clean) or {}
                    # Sin default falso (mismo criterio que OperatingSystem más abajo, auditoría
                    # 2026-08-12): sin sesión activa y sin "state", mejor vacío que asumir
                    # "AVAILABLE" -- una VDI en error/desconocida no debe verse igual que una
                    # sana en los KPIs.
                    basic_state = sess.get("State") or m.get("state") or ""

                    # user_ids: array de SIDs (asignación dedicada) — la API no manda
                    # nombre de usuario en texto. Se toma el primero y se resuelve más abajo.
                    m_user_ids = m.get("user_ids") or m.get("userIds") or []
                    m_user_sid = m_user_ids[0] if isinstance(m_user_ids, list) and m_user_ids else (m.get("user_id") or "")

                    # IPAddress: no verificado contra un HAR real todavía (a diferencia de
                    # client_data), pero es un campo documentado del objeto machine de la API
                    # de Horizon -- agregado 2026-09-07 para evitar la resolución DNS reversa
                    # que hacía web/routes/inventario.py cuando esto quedaba siempre vacío.
                    # Si el nombre real de campo no matchea, sigue "" y el fallback DNS de
                    # siempre se activa igual -- no rompe nada si la suposición es incorrecta.
                    ip_agente = m.get("ip_address") or m.get("ipAddress") or m.get("IpAddress") or ""

                    vms.append({
                        "Name": m_name,
                        "DnsName": m.get("dns_name") or m_name,
                        "IPAddress": ip_agente,
                        "Pool": pool_name,
                        "AssignedUserSid": m_user_sid,
                        "AssignedUser": m.get("user_name") or sess.get("UserName") or "",
                        "BasicState": basic_state.upper() if isinstance(basic_state, str) and basic_state else "",
                        "AgentVersion": m.get("agent_version") or "",
                        # Sin default falso: si Horizon no informa el SO, mejor vacío que
                        # asumir "Windows 11" para cualquier VDI (podía ser Linux, Server, etc.)
                        "OperatingSystem": m.get("operating_system") or "",
                        "InErrorState": m.get("in_error_state", False),
                        "MaintenanceMode": m.get("maintenance_mode", False),
                        # Estado crudo de máquina (AVAILABLE/AGENT_UNREACHABLE/AGENT_ERR_*/...),
                        # sin pisar con el estado de sesión — es la señal real de salud del
                        # Horizon Agent, independiente de si hay usuario conectado o no.
                        "AgentState": str(m.get("state") or "").upper(),
                        "Session": sess
                    })
        except Exception as e_m:
            self.log(f"   ❌ Error consultando máquinas Horizon REST: {e_m}")

        # 3a. Audit Events — trail real de "quién hizo qué" (creó/borró pool, removió
        # máquina, etc). Confirmado en vivo: GET /rest/external/v1/audit-events, sin
        # filtro de fecha soportado de forma confiable — se trae la página más reciente
        # (ordenada desc por id/time) y se dedupea por "id" del lado del caller (DB).
        # user_id viene como SID, igual que sessions/machines — se resuelve en el mismo
        # batch de abajo. Se excluye ruido de login/logout rutinario (ya cubierto por
        # sessions) para quedarnos con acciones administrativas reales.
        _RUIDO_AUDIT = {
            "REST_AUTH_LOGIN_SUCCESS", "REST_AUTH_LOGOUT_SUCCESS", "REST_AUTH_REFRESH_TOKEN_SUCCESS",
            "VLSI_USERLOGGEDIN", "VLSI_USERLOGGEDIN_REST", "VLSI_USERLOGOFF_REST",
            "ADMIN_USERLOGGEDOUT", "BROKER_USERLOGGEDIN", "BROKER_USERLOGGEDOUT",
        }
        audit_events = []
        try:
            url_ae = f"https://{servidor}/rest/external/v1/audit-events?size=1000"
            req_ae = urllib.request.Request(url_ae, headers=headers)
            with urllib.request.urlopen(req_ae, context=ctx, timeout=30) as resp_ae:
                ae_raw = json.loads(resp_ae.read().decode("utf-8"))
                ae_list = _unwrap_list(ae_raw)
                for ev in ae_list:
                    if not isinstance(ev, dict):
                        continue
                    if ev.get("severity") not in ("AUDIT_SUCCESS", "AUDIT_FAIL"):
                        continue
                    if (ev.get("type") or "") in _RUIDO_AUDIT:
                        continue
                    audit_events.append({
                        "Id": ev.get("id"),
                        "UserSid": ev.get("user_id") or "",
                        "Type": ev.get("type") or "",
                        "Severity": ev.get("severity") or "",
                        "Time": ev.get("time"),
                        "Message": ev.get("message") or "",
                        "PoolName": ev.get("desktop_pool_name") or "",
                        "MachineDns": ev.get("machine_dns_name") or "",
                    })
        except Exception as e_ae:
            self.log(f"   ⚠️ Error consultando audit-events REST: {e_ae}")

        # 3b. Resolver SIDs de usuario asignado a nombre real (ver _resolver_sids).
        # sid_cache viene precargado por el caller desde DB — solo se pega a Horizon
        # por los SIDs que todavía no se conocen de corridas anteriores.
        if sid_cache is None:
            sid_cache = {}

        sids_pendientes = set()
        for s in raw_sessions_list:
            sid = s.get("UserSid")
            if sid and sid not in sid_cache:
                sids_pendientes.add(sid)
        for vm in vms:
            sid = vm.get("AssignedUserSid")
            if sid and sid not in sid_cache:
                sids_pendientes.add(sid)
        for ev in audit_events:
            sid = ev.get("UserSid")
            if sid and sid not in sid_cache:
                sids_pendientes.add(sid)

        if sids_pendientes:
            self.log(f"   [Horizon REST] Resolviendo {len(sids_pendientes)} usuario(s) nuevo(s) (SID -> nombre)...")
            sid_cache.update(self._resolver_sids(servidor, headers, ctx, sids_pendientes))

        for s in raw_sessions_list:
            sid = s.get("UserSid")
            if sid and sid_cache.get(sid):
                s["UserName"] = sid_cache[sid]

        for vm in vms:
            sid = vm.get("AssignedUserSid")
            resuelto = sid_cache.get(sid) if sid else ""
            sess_nombre = (vm.get("Session") or {}).get("UserName") or ""
            vm["AssignedUser"] = resuelto or sess_nombre or vm.get("AssignedUser") or ""

        for ev in audit_events:
            sid = ev.get("UserSid")
            ev["Usuario"] = sid_cache.get(sid, "") if sid else ""

        # 4. Entitlements (Autorizaciones de Pools)
        ent_locales = []
        ent_globales = []
        seen_ents = set()

        # Extraer autorizaciones asignadas por máquina
        for vm in vms:
            pool_n = vm.get("Pool")
            usr = vm.get("AssignedUser")
            if pool_n and usr and usr.lower() != "sin usuario":
                key = (pool_n, usr)
                if key not in seen_ents:
                    seen_ents.add(key)
                    ent_locales.append({
                        "PoolName": pool_n,
                        "UserOrGroup": usr,
                        "IsGroup": False
                    })

        # Extraer autorizaciones explícitas de pools -- 2do intento real, 2026-09-07.
        # El 1er intento (/rest/inventory/v1|v2/desktop-pools/{id}/entitlements, por
        # pool) daba 404 para el 100% de +60 pools reales incluso probando ambas
        # versiones -- confirmado con 2 extracciones reales seguidas, el endpoint no
        # existe así en este Connection Server, no era un tema de versión.
        # Pista real: los entitlements de APPLICATION pools sí funcionan (ver bloque
        # "Entitlements de Application Pools" más abajo) y viven en un namespace
        # aparte, "/rest/entitlements/v1/*", bulk (1 sola llamada, no por-pool). Por
        # analogía directa dentro del mismo servidor, se prueba el equivalente para
        # desktop-pools -- mismo shape esperado ({"id":..., "ad_user_or_group_ids":
        # [sid,...]}), mismo mecanismo de resolución de SIDs. Si esto también falla,
        # ent_locales se queda con lo que ya aportó el fallback por-máquina de arriba.
        try:
            req_ent = urllib.request.Request(f"https://{servidor}/rest/entitlements/v1/desktop-pools", headers=headers)
            with urllib.request.urlopen(req_ent, context=ctx, timeout=30) as resp_ent:
                ent_raw = json.loads(resp_ent.read().decode("utf-8"))
                ent_list = _unwrap_list(ent_raw)

            todos_los_sids_pool = set()
            for item in ent_list:
                todos_los_sids_pool.update(item.get("ad_user_or_group_ids") or [])
            sid_to_nombre_pool = self._resolver_sids(servidor, headers, ctx, todos_los_sids_pool)

            for item in ent_list:
                p_id = item.get("id")
                p_name = pool_id_to_name.get(p_id)
                if not p_name:
                    continue
                for sid in (item.get("ad_user_or_group_ids") or []):
                    nombre = sid_to_nombre_pool.get(sid)
                    if nombre:
                        key = (p_name, nombre)
                        if key not in seen_ents:
                            seen_ents.add(key)
                            ent_locales.append({
                                "PoolName": p_name,
                                "UserOrGroup": nombre,
                                "IsGroup": False,
                            })
            self.log(f"   ℹ️ Entitlements de pools: {len(ent_list)} desktop-pools con entitlements, "
                      f"{len(todos_los_sids_pool)} SIDs únicos, {len(sid_to_nombre_pool)} resueltos a nombre.")
        except Exception as e_ent:
            self.log(f"   ⚠️ Error consultando /rest/entitlements/v1/desktop-pools: {e_ent}")

        # 5. Farms (Granjas RDS) -- riesgo: nombres de campo no confirmados contra un
        # Connection Server real todavía (a diferencia de desktop-pools/sessions/machines,
        # ya verificados en vivo). Se soportan variantes de mayúscula/minúscula como
        # salvaguarda; ajustar en la primera extracción real contra el Connection Server.
        farms = []
        farm_id_to_name = {}
        try:
            req_f = urllib.request.Request(f"https://{servidor}/rest/inventory/v1/farms", headers=headers)
            with urllib.request.urlopen(req_f, context=ctx, timeout=30) as resp_f:
                f_raw = json.loads(resp_f.read().decode("utf-8"))
                f_list = _unwrap_list(f_raw)
                for f in f_list:
                    f_id = f.get("id") or f.get("Id")
                    f_name = f.get("name") or f.get("Name") or f_id or "Farm"
                    if f_id:
                        farm_id_to_name[f_id] = f_name
                    farms.append({
                        "Id": f_id,
                        "Name": f_name,
                        "DisplayName": f.get("display_name") or f.get("displayName") or f_name,
                        "Type": f.get("type") or f.get("Type") or "AUTOMATED",
                        "Enabled": f.get("enabled") if f.get("enabled") is not None else f.get("Enabled", True),
                        "RdsServerMaxSessions": f.get("rds_server_max_sessions") or f.get("rdsServerMaxSessions"),
                        "ProvisioningError": f.get("provisioning_error") or f.get("provisioningError") or "",
                    })
        except Exception as e_f:
            self.log(f"   ⚠️ Error consultando farms REST: {e_f}")

        # 6. Application Pools (aplicaciones publicadas)
        apps = []
        app_id_to_name = {}
        app_id_to_farm_id = {}
        try:
            req_a = urllib.request.Request(f"https://{servidor}/rest/inventory/v1/application-pools", headers=headers)
            with urllib.request.urlopen(req_a, context=ctx, timeout=30) as resp_a:
                a_raw = json.loads(resp_a.read().decode("utf-8"))
                a_list = _unwrap_list(a_raw)
                for a in a_list:
                    a_id = a.get("id") or a.get("Id")
                    a_name = a.get("name") or a.get("Name") or a_id or "App"
                    a_farm_id = a.get("farm_id") or a.get("farmId")
                    if a_id:
                        app_id_to_name[a_id] = a_name
                        app_id_to_farm_id[a_id] = a_farm_id
                    apps.append({
                        "Id": a_id,
                        "Name": a_name,
                        "DisplayName": a.get("display_name") or a.get("displayName") or a_name,
                        "FarmName": farm_id_to_name.get(a_farm_id) or "",
                        "ExecutablePath": a.get("executable_path") or a.get("executablePath") or "",
                        "Enabled": a.get("enabled") if a.get("enabled") is not None else a.get("Enabled", True),
                    })
        except Exception as e_a:
            self.log(f"   ⚠️ Error consultando application-pools REST: {e_a}")

        if apps and not app_id_to_name:
            self.log(f"   ⚠️ {len(apps)} application-pools recibidas pero ninguna trajo 'id'/'Id' "
                      f"-- no se pueden consultar entitlements. Item de muestra: {a_list[0] if a_list else '?'}")

        # 7. Entitlements de Application Pools -- confirmado contra la doc oficial (Horizon
        # 8 2309, VMware Horizon Server API): NO viven bajo /rest/inventory/*, son un
        # namespace aparte "/rest/entitlements/v1/application-pools" (bulk, un solo call
        # para todas las apps), y el shape es {"id": <app_pool_id>, "ad_user_or_group_ids":
        # [sid, ...]} -- SIDs crudos, no nombres, hay que resolverlos con _resolver_sids
        # (mismo mecanismo que ya usa este archivo para AssignedUserSid). No distingue
        # Local vs Global ni is_group -- Global Application Entitlements (GAE) es un
        # objeto completamente aparte (/rest/inventory/v1/global-application-entitlements,
        # vinculado a apps locales vía .../local-application-pools) que no se resuelve acá
        # todavía (pendiente, ver docs/analisis_arquitectura).
        app_ent_locales = []
        app_ent_globales = []
        try:
            req_ae = urllib.request.Request(f"https://{servidor}/rest/entitlements/v1/application-pools", headers=headers)
            with urllib.request.urlopen(req_ae, context=ctx, timeout=30) as resp_ae:
                ae_raw = json.loads(resp_ae.read().decode("utf-8"))
                ae_list = _unwrap_list(ae_raw)

            todos_los_sids = set()
            for item in ae_list:
                todos_los_sids.update(item.get("ad_user_or_group_ids") or [])
            sid_to_nombre = self._resolver_sids(servidor, headers, ctx, todos_los_sids)

            for item in ae_list:
                a_id = item.get("id")
                a_name = app_id_to_name.get(a_id)
                if not a_name:
                    continue
                for sid in (item.get("ad_user_or_group_ids") or []):
                    nombre = sid_to_nombre.get(sid)
                    if nombre:
                        app_ent_locales.append({
                            "AplicacionNombre": a_name,
                            "UserOrGroup": nombre,
                            "IsGroup": False,
                        })
            self.log(f"   ℹ️ Entitlements de apps: {len(ae_list)} application-pools con entitlements, "
                      f"{len(todos_los_sids)} SIDs únicos, {len(sid_to_nombre)} resueltos a nombre.")
        except Exception as e_ae:
            self.log(f"   ⚠️ Error consultando /rest/entitlements/v1/application-pools: {e_ae}")

        # 8. RDS Servers -- confirmado contra la doc oficial: recurso plano top-level
        # (/rest/inventory/v1/rds-servers), NO nested bajo farms/{id}/rds-servers (eso da
        # 404 real en producción). Cada item trae su propio farm_id -- se filtra en Python.
        rds_servers = []
        try:
            req_rs = urllib.request.Request(f"https://{servidor}/rest/inventory/v1/rds-servers", headers=headers)
            with urllib.request.urlopen(req_rs, context=ctx, timeout=30) as resp_rs:
                rs_raw = json.loads(resp_rs.read().decode("utf-8"))
                rs_list = _unwrap_list(rs_raw)
                for rs in rs_list:
                    f_id = rs.get("farm_id")
                    f_name = farm_id_to_name.get(f_id) or ""
                    rds_servers.append({
                        "FarmName": f_name,
                        "Name": rs.get("name") or rs.get("dns_name") or "",
                        "Estado": rs.get("state") or "",
                        "SesionesActivas": rs.get("session_count") or 0,
                        "Enabled": rs.get("enabled") if rs.get("enabled") is not None else True,
                    })
        except Exception as e_rs:
            self.log(f"   ⚠️ Error consultando /rest/inventory/v1/rds-servers: {e_rs}")

        self.log(f"[Horizon REST] 🌾 {len(farms)} Farms, {len(apps)} Apps publicadas, "
                  f"{len(app_ent_locales)} autorizaciones de apps y {len(rds_servers)} RDS Servers extraídos.")

        self.log(f"[Horizon REST] 🎉 {len(vms)} VDI Machines, {len(pools)} Pools y {len(ent_locales)} Entitlements extraídos.")
        sesiones_lista = raw_sessions_list if raw_sessions_list else list(sessions_map.values())
        for s in sesiones_lista:
            if not s.get("MachineName") and s.get("name"):
                s["MachineName"] = s["name"]
            if not s.get("UserName") and s.get("username"):
                s["UserName"] = s["username"]
            if not s.get("SessionState") and s.get("State"):
                s["SessionState"] = s["State"]

        return {
            "maquinas": vms,
            "vms": vms,
            "pools": pools,
            "sesiones": sesiones_lista,
            "entitlements_locales": ent_locales,
            "entitlements_globales": ent_globales,
            "master_refs": master_refs,
            "sid_cache": sid_cache,
            "audit_events": audit_events,
            "farms": farms,
            "application_pools": apps,
            "app_entitlements_locales": app_ent_locales,
            "app_entitlements_globales": app_ent_globales,
            "rds_servers": rds_servers,
        }
