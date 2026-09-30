"""
core/vcenter_rest.py
Cliente de extracción 100% PURE REST API para VMware vCenter Server.
Elimina la dependencia de PowerShell/PowerCLI y recupera la información de VMs
y eventos en paralelo vía endpoints HTTPS REST (/api/vcenter/vm y /rest/vcenter/vm).
"""
import ssl
import json
import time
import random
import threading
import contextlib
import urllib.request
import urllib.error
import base64
import re
from concurrent.futures import ThreadPoolExecutor

from web.security_utils import normalizar_username

# Backoff exponencial (segundos) para reintentos ante 503 en llamadas guest-ops.
_RETRY_BACKOFF = (0.5, 1.5, 3.0)


def _texto_vsphere(valor) -> str:
    """Ciertos campos de vSphere 7.0+ REST (guest_OS del detalle, full_name de guest/identity)
    vienen a veces como un objeto de mensaje localizado -- {"id": "...", "default_message":
    "Microsoft Windows 10 (64-bit)", "args": []} -- en vez de un string plano; depende del
    guest OS/localización del vCenter. Bug real encontrado 2026-08-12: sin esto, el dict
    crudo se pasaba directo como parámetro de un UPDATE a SQLite ("Error binding parameter:
    type 'dict' is not supported"), rompiendo el guardado COMPLETO de esa VM en silencio
    (autoflush) -- la causa real de por qué disco/tools/SO nunca persistían pese a que el
    fetch a vCenter traía todo bien.
    """
    if isinstance(valor, dict):
        return str(valor.get("default_message") or valor.get("id") or "")
    return str(valor) if valor else ""


class vCenterRestClient:
    """Cliente HTTPS REST API para VMware vCenter Server (vSphere 6.7 / 7.0 / 8.0)."""

    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda msg: print(msg, flush=True))

    def log(self, msg: str):
        self._log(msg)

    @staticmethod
    def _get_json_reintentos(url: str, headers: dict, ctx, timeout: float, intentos: int = 3) -> dict:
        """GET con reintento + backoff exponencial y jitter, SOLO ante HTTP 503.

        El subsistema guest-ops de vCenter (tools/identity/networking, enrutado a
        hostd/vmx por VM) se satura bajo ráfaga paralela mucho antes que la API
        general de listado — un 503 ahí es "vCenter tirando el freno", transitorio,
        no un error real de la VM. Otros códigos (404/400/etc) fallan directo: no
        son transitorios, reintentarlos solo demora la extracción sin cambiar nada.
        """
        for intento in range(intentos):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code != 503 or intento == intentos - 1:
                    raise
                time.sleep(_RETRY_BACKOFF[min(intento, len(_RETRY_BACKOFF) - 1)] + random.uniform(0, 0.3))

    def _autenticar_sesion(self, srv: str, user: str, password: str, dominio: str, ctx) -> tuple[str, str]:
        user_formats = []
        user_clean = user.strip()
        sam_user = normalizar_username(user_clean)

        if dominio and "\\" not in user_clean and "@" not in user_clean:
            user_formats.append(f"{user_clean}@{dominio}.intra")
            user_formats.append(f"{dominio}\\{user_clean}")
            user_formats.append(f"{sam_user}@{dominio}")
        user_formats.append(user_clean)

        # Fallo esperado en la mayoría de los intentos -- se prueban varios formatos de
        # usuario x 2 endpoints hasta encontrar el que funciona, no tiene sentido loggear
        # cada uno. Pero si TODOS fallan, antes se perdía el motivo real (credencial mala,
        # red inalcanzable, certificado, etc.) -- el RuntimeError final no decía nada más
        # que "falló". Ahora arrastra el último error real para el mensaje final
        # (hallazgo de calidad de código, corregido 2026-09-07).
        ultimo_error: Exception | None = None
        for u_fmt in user_formats:
            # Intento 1: vSphere 7.0/8.0 /api/session
            try:
                url_sess = f"https://{srv}/api/session"
                req = urllib.request.Request(url_sess, method="POST")
                creds = base64.b64encode(f"{u_fmt}:{password}".encode("utf-8")).decode("ascii")
                req.add_header("Authorization", f"Basic {creds}")
                with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                    token = json.loads(resp.read().decode("utf-8"))
                    session_id = token if isinstance(token, str) else token.get("value")
                    if session_id:
                        return session_id, "vSphere 7.0+"
            except Exception as e:
                ultimo_error = e

            # Intento 2: vSphere 6.7 /rest/com/vmware/cis/session
            try:
                url_sess = f"https://{srv}/rest/com/vmware/cis/session"
                req = urllib.request.Request(url_sess, method="POST")
                creds = base64.b64encode(f"{u_fmt}:{password}".encode("utf-8")).decode("ascii")
                req.add_header("Authorization", f"Basic {creds}")
                with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    session_id = data.get("value")
                    if session_id:
                        return session_id, "vSphere 6.7"
            except Exception as e:
                ultimo_error = e

        detalle = f" (último error: {ultimo_error})" if ultimo_error else ""
        raise RuntimeError(f"Fallo de autenticación HTTPS REST en vCenter {srv}.{detalle}")

    # NOTA: existió acá un método actualizar_annotation() que hacía PATCH a
    # /api/vcenter/vm/{vm} y /rest/vcenter/vm/{vm} -- se sacó porque se confirmó con un
    # HAR real (2026-08-12) que Notes/Annotation NO está expuesto por la REST Automation
    # API pública en NINGUNA versión, ni para lectura ni para escritura. El único write
    # real que usa vSphere Client es una API interna no documentada de la propia UI. La
    # escritura real de Annotation vive en core/vcenter_soap.py (pyVmomi/SOAP, oficial).

    def obtener_vms(self, servidor: str, usuario: str, password: str, dominio: str, progress_callback=None) -> dict:
        """
        Obtiene la lista completa de VMs desde vCenter usando REST API puro en paralelo:
        - GET /api/vcenter/vm
        - GET /api/vcenter/vm/{vm_id}
        - GET /api/vcenter/vm/{vm_id}/guest/identity

        Retorna {"vms": [...], "hosts": [...], "datastores": [...]}. hosts/datastores
        ya se pedían para armar un lookup de nombre (mostrar "Host: esx-01" en la VM) y
        se descartaba el resto — la misma respuesta ya trae capacity/free_space
        (datastore) y connection_state/power_state (host), sin llamada extra.
        """
        servidores_lista = [s.strip() for s in servidor.split(",") if s.strip()]
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        vms_result = []
        hosts_result = []
        datastores_result = []

        for srv in servidores_lista:
            self.log(f"[vCenter REST] Conectando a https://{srv} ...")
            session_id, api_flavor = self._autenticar_sesion(srv, usuario, password, dominio, ctx)
            self.log(f"   ✅ Sesión vCenter REST ({api_flavor}) activa. Obteniendo lista general de VMs...")

            headers = {
                "vmware-api-session-id": session_id,
                "Accept": "application/json"
            }

            url_vms = f"https://{srv}/api/vcenter/vm" if "7.0+" in api_flavor else f"https://{srv}/rest/vcenter/vm"
            req_vms = urllib.request.Request(url_vms, headers=headers)
            with urllib.request.urlopen(req_vms, context=ctx, timeout=60) as resp:
                data_vms = json.loads(resp.read().decode("utf-8"))
                # "value" solo existe en respuestas estilo /rest/vcenter (6.x) -- /api/vcenter
                # (7.0+, lo que usamos acá) devuelve el objeto/lista sin envolver. Antes se
                # llamaba .get("value") siempre, que en 7.0+ da None para respuestas dict sin
                # esa clave -- bug real encontrado 2026-08-12, mismo patrón en los 4 helpers
                # de abajo y en las 5 llamadas guest-ops/detalle más abajo (ahí es donde más
                # dolía: disco/tools/hardware quedaban vacíos sin ninguna excepción ni fallo
                # registrado, indistinguible de "no había dato").
                vm_list = data_vms.get("value") if isinstance(data_vms, dict) and "value" in data_vms else data_vms

            self.log(f"   [vCenter REST] {len(vm_list)} VMs encontradas. Enriqueciendo detalles (CPU, RAM, Disco, IP, Host, OS) en paralelo...")

            # Prefetch ESXi Hosts y Datastores
            hosts_lookup = {}
            ds_lookup = {}
            try:
                url_h = f"https://{srv}/api/vcenter/host" if "7.0+" in api_flavor else f"https://{srv}/rest/vcenter/host"
                req_h = urllib.request.Request(url_h, headers=headers)
                with urllib.request.urlopen(req_h, context=ctx, timeout=15) as resp_h:
                    h_data = json.loads(resp_h.read().decode("utf-8"))
                    h_val = h_data.get("value") if isinstance(h_data, dict) and "value" in h_data else h_data
                    if isinstance(h_val, list):
                        for h in h_val:
                            h_name = h.get("name")
                            hosts_lookup[h.get("host")] = h_name
                            hosts_result.append({
                                "Name": h_name,
                                "ConnectionState": h.get("connection_state"),
                                "PowerState": h.get("power_state"),
                                "Servidor": srv,
                            })
            except Exception as e:
                self.log(f"   ⚠️ [vCenter] No se pudo prefetchear la lista de hosts ESXi: {e}")

            try:
                url_d = f"https://{srv}/api/vcenter/datastore" if "7.0+" in api_flavor else f"https://{srv}/rest/vcenter/datastore"
                req_d = urllib.request.Request(url_d, headers=headers)
                with urllib.request.urlopen(req_d, context=ctx, timeout=15) as resp_d:
                    d_data = json.loads(resp_d.read().decode("utf-8"))
                    d_val = d_data.get("value") if isinstance(d_data, dict) and "value" in d_data else d_data
                    if isinstance(d_val, list):
                        for d in d_val:
                            d_name = d.get("name")
                            ds_lookup[d.get("datastore")] = d_name
                            cap = d.get("capacity")
                            free = d.get("free_space")
                            datastores_result.append({
                                "Name": d_name,
                                "CapacityGB": round(cap / (1024**3), 2) if cap else None,
                                "FreeGB": round(free / (1024**3), 2) if free is not None else None,
                                "Type": d.get("type"),
                                "Servidor": srv,
                            })
            except Exception as e:
                self.log(f"   ⚠️ [vCenter] No se pudo prefetchear la lista de datastores: {e}")

            # Templates de Content Library (golden images / plantillas VDI publicadas ahí).
            # NOTA: solo cubre templates de Content Library. Un "Convert to Template" clásico
            # de vCenter (no-Content-Library) no es visible vía REST — requeriría la API SOAP
            # (pyVmomi/PowerCLI, fuera de alcance acá porque la web ya no usa PowerCLI).
            template_names = set()
            try:
                url_t = f"https://{srv}/api/vcenter/vm-template/library-items"
                req_t = urllib.request.Request(url_t, headers=headers)
                with urllib.request.urlopen(req_t, context=ctx, timeout=15) as resp_t:
                    t_data = json.loads(resp_t.read().decode("utf-8"))
                    t_ids = t_data.get("value") if isinstance(t_data, dict) and "value" in t_data else t_data
                    if isinstance(t_ids, list):
                        for t_id in t_ids:
                            item_id = t_id.get("library_item") if isinstance(t_id, dict) else t_id
                            if not item_id:
                                continue
                            try:
                                req_ti = urllib.request.Request(f"{url_t}/{item_id}", headers=headers)
                                with urllib.request.urlopen(req_ti, context=ctx, timeout=10) as resp_ti:
                                    ti_data = json.loads(resp_ti.read().decode("utf-8"))
                                    ti_val = ti_data.get("value") if isinstance(ti_data, dict) and "value" in ti_data else ti_data
                                    src_vm = ti_val.get("source_vm") if isinstance(ti_val, dict) else None
                                    if src_vm:
                                        template_names.add(src_vm)
                            except Exception:
                                pass
            except Exception:
                pass  # Endpoint no disponible en esta versión de vSphere: sin templates detectados, no rompe la extracción.

            # Semáforo aparte del paralelismo de VMs (max_workers=16 más abajo): limita
            # cuántas llamadas guest-ops (tools/detalle/identity/interfaces) están en
            # vuelo al mismo tiempo, que es lo que satura vpxd->hostd y dispara 503 —
            # bajarlo no reduce cuántas VMs se procesan en paralelo, solo cuántas
            # de ellas están golpeando el subsistema guest-ops en el mismo instante.
            # Bajado de 8 a 4 el 2026-08-12: se detectó que ~99% de la flota tenía
            # disk_gb/disk_used_gb con valores fabricados viejos (100GB/40GB fijos)
            # nunca refrescados -- sospecha de que el 503 seguía tumbando "detalle"/
            # "disco" en la mayoría de las corridas incluso con 8. Bajar a 4 y correr
            # una extracción real para confirmar si el % de VMs con dato real sube.
            _guest_sem = threading.Semaphore(4)

            def _enrich_vm(vm_raw, solo_calls: set | None = None, previo: dict | None = None):
                """Trae los datos de detalle/guest-ops de una VM.

                solo_calls=None (pase 1, paralelo con semáforo): hace las 5 llamadas de
                siempre y devuelve (resultado, fallas) -- fallas es el set de nombres de
                llamada ("tools"/"disco"/"detalle"/"identity"/"interfaces") que no se
                pudieron completar.

                solo_calls={...} (pase 2, secuencial de uno en uno, SIN semáforo -- ya no
                hace falta, es 1 a la vez): parte de 'previo' (lo que ya se consiguió en el
                pase 1) y reintenta solo esas llamadas puntuales, sin pisar lo que ya estaba bien.
                """
                v_id = vm_raw.get("vm") or ""
                name = vm_raw.get("name") or vm_raw.get("Name") or ""
                # Sin valores inventados (mismo criterio que disco/OS/IP más abajo, auditoría
                # 2026-08-12): power_state/cpu_count/memory_size_MiB ausentes se dejaban en
                # "POWERED_OFF"/2 vCPU/4GB fijos, indistinguibles de un dato real. Quedan en
                # None -- una VM con power_state None simplemente no dispara is_powered_on.
                p_state = vm_raw.get("power_state") or vm_raw.get("PowerState") or None
                cpu_cnt = vm_raw.get("cpu_count") or vm_raw.get("NumCpu") or None
                ram_mib = vm_raw.get("memory_size_MiB")
                ram_gb = round(ram_mib / 1024.0, 2) if ram_mib else None

                pase2 = solo_calls is not None
                previo = previo or {}

                # Sin valores inventados: si una llamada de detalle falla, el campo queda
                # vacío/None (visible como "falta" en la UI) en vez de un default plausible
                # pero falso (antes: "Windows 11", 100GB de disco, carpeta "Produccion" fijos
                # para CUALQUIER VM cuyo detalle no se pudo traer — indistinguible de un dato real).
                # En pase 2 arrancamos de lo que ya se consiguió, no de cero.
                os_str = previo.get("OS", "")
                ip_str = previo.get("IPAddress", "")
                dns_str = previo.get("DnsName") or name
                disk_gb = previo.get("ProvisionedSpaceGB")
                disk_used_gb = previo.get("UsedSpaceGB")
                hw_ver = previo.get("HardwareVersion", "")
                tools_status = previo.get("ToolsStatus", "")
                # Agregados 2026-09-07 -- misma llamada de detalle que ya trae hw_ver/disco,
                # ver más abajo. Sin valores inventados: quedan None si el detalle falla.
                cpu_cores_per_socket = previo.get("CpuCoresPerSocket")
                cpu_hot_add = previo.get("CpuHotAddEnabled")
                mem_hot_add = previo.get("MemoryHotAddEnabled")
                boot_firmware = previo.get("BootFirmware", "")
                secure_boot = previo.get("SecureBootEnabled")
                hw_upgrade_status = previo.get("HardwareUpgradeStatus", "")
                esxi_host = hosts_lookup.get(vm_raw.get("host")) or srv
                folder_str = ""
                rp_str = ""
                # Antes: primeros 2 datastores GLOBALES del vCenter, iguales para toda la
                # flota (dato inventado -- hallazgo de seguridad/calidad de datos, 2026-09-07).
                # Ahora: se completa más abajo con los datastores REALES de los discos de
                # esta VM puntual, parseados de "detalle" -> disks[].backing.vmdk_file
                # ("[datastore] carpeta/archivo.vmdk"). Si esa llamada falla o esta VM
                # está apagada, queda "" -- mismo criterio "sin valores inventados" que
                # el resto de esta función.
                ds_str = previo.get("Datastores", "")

                api_prefix = "/api/vcenter" if "7.0+" in api_flavor else "/rest/vcenter"

                is_powered_on = str(p_state).upper() in ("POWERED_ON", "POWEREDON")
                fallas = set()

                def _quiere(llamada: str) -> bool:
                    return llamada in solo_calls if pase2 else True

                def _fallo(llamada: str, motivo: str, e: Exception, solo_si_encendida: bool = False):
                    fallas.add(llamada)
                    # Guest identity/networking fallan seguido y de forma normal en VMs apagadas
                    # o sin VMware Tools — no llenar el log con eso. Sí interesa cuando la VM
                    # está encendida (ahí "no se pudo enriquecer" es una falla real a investigar).
                    if solo_si_encendida and not is_powered_on:
                        return
                    code = getattr(e, "code", None)
                    if code == 503:
                        # vCenter saturado por el burst de llamadas guest/* en paralelo (16 workers).
                        # NO significa Tools caído — mal etiquetarlo así ocultaba el motivo real.
                        detalle = "HTTP 503 (vCenter saturado por el volumen de consultas, no es Tools caído)"
                    else:
                        detalle = f"HTTP {code}" if code else str(e)
                    prefijo = "   🔁 [vCenter, reintento secuencial]" if pase2 else "   ⚠️ [vCenter]"
                    self.log(f"{prefijo} '{name}' ({motivo}): {detalle}")

                if v_id:
                    # Estado real de VMware Tools (RUNNING/NOT_RUNNING/...) — se pide aparte de
                    # guest/identity para poder distinguir "Tools realmente caído" de "vCenter
                    # tiró 503 por saturación" en vez de asumir lo primero cuando falla lo segundo.
                    if is_powered_on and _quiere("tools"):
                        try:
                            url_tools = f"https://{srv}{api_prefix}/vm/{v_id}/tools"
                            ctx_mgr = _guest_sem if not pase2 else contextlib.nullcontext()
                            with ctx_mgr:
                                tools_j = self._get_json_reintentos(url_tools, headers, ctx, 10, intentos=1 if pase2 else 3)
                            tools_v = tools_j.get("value") if isinstance(tools_j, dict) and "value" in tools_j else tools_j
                            if isinstance(tools_v, dict):
                                tools_status = str(tools_v.get("run_state") or "")
                        except Exception as e:
                            _fallo("tools", "estado VMware Tools", e, solo_si_encendida=True)

                        # Espacio en disco REALMENTE usado (no inventado): requiere Tools
                        # corriendo, si no el guest no puede reportar el filesystem. Sin
                        # esto UsedSpaceGB era None siempre — nunca se pedía.
                        if tools_status == "RUNNING" and _quiere("disco"):
                            try:
                                url_fs = f"https://{srv}{api_prefix}/vm/{v_id}/guest/local-filesystem"
                                ctx_mgr = _guest_sem if not pase2 else contextlib.nullcontext()
                                with ctx_mgr:
                                    fs_j = self._get_json_reintentos(url_fs, headers, ctx, 10, intentos=1 if pase2 else 3)
                                fs_v = fs_j.get("value") if isinstance(fs_j, dict) and "value" in fs_j else fs_j
                                if isinstance(fs_v, dict):
                                    fs_v = list(fs_v.values())
                                if isinstance(fs_v, list):
                                    cap_total = 0
                                    free_total = 0
                                    for mount in fs_v:
                                        if not isinstance(mount, dict):
                                            continue
                                        cap = mount.get("capacity", mount.get("Capacity"))
                                        free = mount.get("free_space", mount.get("freeSpace", mount.get("FreeSpace")))
                                        if cap is not None and free is not None:
                                            cap_total += cap
                                            free_total += free
                                    if cap_total > 0:
                                        disk_used_gb = round((cap_total - free_total) / (1024**3), 2)
                            except Exception as e:
                                _fallo("disco", "espacio en disco (guest/local-filesystem)", e, solo_si_encendida=True)

                    # Detalle profundo hardware (CPU/RAM ya vienen de la lista general; esto es disco+SO+HW version)
                    if _quiere("detalle"):
                        try:
                            url_det = f"https://{srv}{api_prefix}/vm/{v_id}"
                            ctx_mgr = _guest_sem if not pase2 else contextlib.nullcontext()
                            with ctx_mgr:
                                det_j = self._get_json_reintentos(url_det, headers, ctx, 12, intentos=1 if pase2 else 3)
                            det_v = det_j.get("value") if isinstance(det_j, dict) and "value" in det_j else det_j
                            if isinstance(det_v, dict):
                                os_str = _texto_vsphere(det_v.get("guest_OS")) or os_str
                                hw = det_v.get("hardware")
                                if isinstance(hw, dict):
                                    hw_ver = str(hw.get("version") or "")
                                    hw_upgrade_status = str(hw.get("upgrade_status") or hw_upgrade_status or "")

                                # Topología de CPU/RAM -- mismo /vm/{vm} de detalle, sub-objetos
                                # "cpu"/"memory" del schema de vSphere Automation API.
                                cpu_info = det_v.get("cpu")
                                if isinstance(cpu_info, dict):
                                    cpu_cores_per_socket = cpu_info.get("cores_per_socket")
                                    if cpu_info.get("hot_add_enabled") is not None:
                                        cpu_hot_add = bool(cpu_info.get("hot_add_enabled"))
                                mem_info = det_v.get("memory")
                                if isinstance(mem_info, dict) and mem_info.get("hot_add_enabled") is not None:
                                    mem_hot_add = bool(mem_info.get("hot_add_enabled"))

                                # Firmware de arranque y Secure Boot -- sub-objeto "boot". No
                                # confirmado contra un HAR real todavía (a diferencia de disco/OS
                                # de arriba) -- si el nombre de campo no matchea, queda "" / None,
                                # mismo criterio defensivo del resto de este archivo.
                                boot_info = det_v.get("boot")
                                if isinstance(boot_info, dict):
                                    boot_firmware = str(boot_info.get("type") or boot_info.get("firmware") or boot_firmware or "")
                                    sb = boot_info.get("efi_secure_boot_enabled")
                                    if sb is not None:
                                        secure_boot = bool(sb)

                                disks = det_v.get("disks")
                                disks_iter = disks.values() if isinstance(disks, dict) else (disks if isinstance(disks, list) else [])
                                disk_dicts = [dk for dk in disks_iter if isinstance(dk, dict)]
                                if disk_dicts:
                                    tot_b = sum([dk.get("capacity", 0) for dk in disk_dicts])
                                    if tot_b > 0: disk_gb = round(tot_b / (1024**3), 2)

                                    # Datastore real por disco -- vmdk_file viene con formato
                                    # "[nombre_datastore] carpeta/archivo.vmdk", el nombre entre
                                    # corchetes es el datastore real de ESE disco de ESTA VM (no
                                    # una lista global). Una VM puede tener discos en más de un
                                    # datastore (ej. OS en uno, datos en otro) -- se listan todos.
                                    datastores_vm = set()
                                    for dk in disk_dicts:
                                        vmdk_path = (dk.get("backing") or {}).get("vmdk_file", "")
                                        m = re.match(r"^\[([^\]]+)\]", vmdk_path or "")
                                        if m:
                                            datastores_vm.add(m.group(1))
                                    if datastores_vm:
                                        ds_str = ", ".join(sorted(datastores_vm))
                        except Exception as e:
                            _fallo("detalle", "detalle hardware/disco", e)

                    # Identidad guest (IP, Hostname, SO completo) — requiere VMware Tools corriendo
                    if _quiere("identity"):
                        try:
                            url_net = f"https://{srv}{api_prefix}/vm/{v_id}/guest/identity"
                            ctx_mgr = _guest_sem if not pase2 else contextlib.nullcontext()
                            with ctx_mgr:
                                net_j = self._get_json_reintentos(url_net, headers, ctx, 10, intentos=1 if pase2 else 3)
                            net_v = net_j.get("value") if isinstance(net_j, dict) and "value" in net_j else net_j
                            if isinstance(net_v, dict):
                                if net_v.get("host_name"): dns_str = net_v["host_name"]
                                if net_v.get("full_name"): os_str = _texto_vsphere(net_v["full_name"]) or os_str
                                if net_v.get("ip_address"): ip_str = net_v["ip_address"]
                        except Exception as e:
                            _fallo("identity", "guest identity (¿VMware Tools corriendo?)", e, solo_si_encendida=True)

                    # Interfaces de red guest fallback para obtener IP si no venía en identity
                    if not ip_str and _quiere("interfaces"):
                        try:
                            url_if = f"https://{srv}{api_prefix}/vm/{v_id}/guest/networking/interfaces"
                            ctx_mgr = _guest_sem if not pase2 else contextlib.nullcontext()
                            with ctx_mgr:
                                if_j = self._get_json_reintentos(url_if, headers, ctx, 8, intentos=1 if pase2 else 3)
                            if_v = if_j.get("value") if isinstance(if_j, dict) and "value" in if_j else if_j
                            if isinstance(if_v, list):
                                for iface in if_v:
                                    if isinstance(iface, dict):
                                        ip_arr = iface.get("ip", {}).get("ip_addresses", [])
                                        for ip_obj in ip_arr:
                                            ip_val = ip_obj.get("ip_address") if isinstance(ip_obj, dict) else str(ip_obj)
                                            if ip_val and not ip_val.startswith("127.") and not ip_val.startswith("fe80"):
                                                ip_str = ip_val
                                                break
                                    if ip_str: break
                        except Exception as e:
                            _fallo("interfaces", "interfaces de red guest", e, solo_si_encendida=True)

                    if pase2 and is_powered_on and not ip_str and not fallas:
                        if tools_status and tools_status != "RUNNING":
                            self.log(f"   ⚠️ [vCenter] '{name}': encendida pero sin IP (Tools NO corriendo, estado real: {tools_status}).")
                        else:
                            self.log(f"   ⚠️ [vCenter] '{name}': encendida pero sin IP detectada (Tools sin IP reportada aún, o guest sin red).")

                resultado = {
                    "Name": name,
                    "PowerState": p_state,
                    "NumCpu": cpu_cnt,
                    "MemoryGB": ram_gb,
                    "ProvisionedSpaceGB": disk_gb,
                    # UsedSpaceGB real vía guest/local-filesystem (requiere Tools corriendo).
                    # Si no se pudo obtener, queda None — mejor eso que inventar un número.
                    "UsedSpaceGB": disk_used_gb,
                    "IPAddress": ip_str,
                    "Host": esxi_host,
                    "OS": os_str,
                    "DnsName": dns_str,
                    "Folder": folder_str,
                    "ResourcePool": rp_str,
                    "Datastores": ds_str,
                    "HardwareVersion": hw_ver,
                    "HardwareUpgradeStatus": hw_upgrade_status,
                    "CpuCoresPerSocket": cpu_cores_per_socket,
                    "CpuHotAddEnabled": cpu_hot_add,
                    "MemoryHotAddEnabled": mem_hot_add,
                    "BootFirmware": boot_firmware,
                    "SecureBootEnabled": secure_boot,
                    "ToolsStatus": tools_status,
                    "Annotation": "",  # REST no lo expone (ver nota arriba) -- valor real se lee aparte por SOAP en _extraer_vcenter_cred (core/vcenter_soap.obtener_annotations) y pisa esto.
                    # "connected" fijo para el 100% de las VMs -- la REST API de vCenter usada
                    # acá (/api/vcenter/vm/{id}) no expone connection_state por VM (solo existe
                    # para hosts ESXi, ver HostEsxi.connection_state más abajo). Nunca hubo un
                    # intento real de leerlo. None hasta que se agregue un fetch real (SOAP
                    # runtime.connectionState) si algún día hace falta.
                    "ConnectionState": None,
                    "CpuUsageMhz": None,
                    "MemoryUsageMB": None,
                    "ExternalId": v_id,
                    "LastPowerOnTime": "",
                    "Events": [],
                    "EsTemplate": v_id in template_names,
                }
                return resultado, fallas

            with ThreadPoolExecutor(max_workers=min(16, max(1, len(vm_list)))) as ex:
                resultados_pase1 = list(ex.map(_enrich_vm, vm_list))

            enriched = []
            for r, f in resultados_pase1:
                if f:
                    r["EnrichmentFallas"] = sorted(f)
                enriched.append(r)

            vms_result.extend(enriched)

        self.log(f"[vCenter REST] 🎉 {len(vms_result)} VMs extraídas mediante REST API en {servidores_lista}.")
        return {"vms": vms_result, "hosts": hosts_result, "datastores": datastores_result}
