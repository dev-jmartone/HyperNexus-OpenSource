"""
core/vcenter_soap.py
Cliente SOAP (pyVmomi) para datos que la REST Automation API de vCenter no expone:
escribir/leer Notes/Annotation, y leer la carpeta real (ruta completa) de cada VM.

Por qué SOAP y no REST: confirmado con una captura HAR real de vSphere Client (2026-08-12)
que Notes NO está expuesto por la vSphere Automation API pública, ni la moderna
(/api/vcenter/vm/{vm}, 7.0+/8.0) ni la legacy (/rest/vcenter/vm/{vm}, 6.7) -- ninguna trae
el campo en el GET. vSphere Client solo puede escribirlo vía una API interna no
documentada de la propia UI (POST /ui/mutation/apply/urn:vmomi:VirtualMachine:{moref}:
{instance_uuid}?propertyObjectType=com.vmware.vsphere.client.vm.VmNotesSpec), que requiere
una sesión de navegador (webclientsessionid + xsrf token) distinta de la sesión REST que
ya usa core/vcenter_rest.py, y que puede romper en cualquier upgrade de vCenter sin aviso.

pyVmomi (SDK oficial de Broadcom/VMware) SÍ es soportado y documentado: ReconfigVM_Task con
VirtualMachineConfigSpec.annotation es el mecanismo real y estable que usa PowerCLI
(Set-VM -Annotation) por debajo. Responde en milisegundos, sin necesitar instance_uuid --
alcanza con el MoRef (Maquina.external_id, ej. "vm-511").
"""
import ssl
import time
from datetime import datetime, timedelta

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl

from web.security_utils import normalizar_username


def _conectar_soap(host: str, user: str, password: str, dominio: str):
    """Conecta por SOAP probando los mismos formatos de usuario que
    core/vcenter_rest.py._autenticar_sesion, para consistencia -- SSO de vCenter
    suele aceptar user@dominio como UPN. Devuelve el ServiceInstance conectado."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    user_clean = user.strip()
    sam_user = normalizar_username(user_clean)
    user_formats = []
    if dominio and "\\" not in user_clean and "@" not in user_clean:
        user_formats.append(f"{user_clean}@{dominio}.intra")
        user_formats.append(f"{dominio}\\{user_clean}")
        user_formats.append(f"{sam_user}@{dominio}")
    user_formats.append(user_clean)

    last_err = None
    for u_fmt in user_formats:
        try:
            return SmartConnect(host=host, user=u_fmt, pwd=password, port=443, sslContext=ctx)
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"Fallo de autenticación SOAP en vCenter {host}: {last_err}")


def _bulk_retrieve(si, entity_type, prop_names: list[str]):
    """PropertyCollector bulk: trae `prop_names` de TODOS los objetos `entity_type` del
    vCenter en un único roundtrip (no per-objeto) -- mismo mecanismo que usa govc/PowerCLI
    por debajo. Compartido por obtener_annotations/obtener_folders para no duplicar el
    boilerplate de ContainerView+TraversalSpec en cada función."""
    content = si.RetrieveContent()
    view_ref = content.viewManager.CreateContainerView(
        container=content.rootFolder, type=[entity_type], recursive=True
    )
    try:
        traversal_spec = vmodl.query.PropertyCollector.TraversalSpec(
            name="traverseEntities", path="view", skip=False, type=vim.view.ContainerView,
        )
        obj_spec = vmodl.query.PropertyCollector.ObjectSpec(
            obj=view_ref, skip=True, selectSet=[traversal_spec]
        )
        prop_spec = vmodl.query.PropertyCollector.PropertySpec(
            type=entity_type, pathSet=prop_names
        )
        filter_spec = vmodl.query.PropertyCollector.FilterSpec(
            objectSet=[obj_spec], propSet=[prop_spec]
        )
        return content.propertyCollector.RetrieveContents([filter_spec])
    finally:
        view_ref.Destroy()


def obtener_annotations(host: str, user: str, password: str, dominio: str,
                         timeout: float = 60) -> dict:
    """Lee el campo Annotation/Notes real de TODAS las VMs de un vCenter en una sola
    llamada bulk vía PropertyCollector -- NO es per-VM como guest-ops (eso se descartó
    en 2026-08-13 por tardar 35-65 min a escala de 1047 VMs). PropertyCollector trae
    config.annotation de toda la flota en un único roundtrip, del orden de segundos.

    Retorna {moref_str: texto} (ej. {"vm-511": "nota real"}) solo para VMs con
    annotation no vacío -- mismo formato de MoRef que Maquina.external_id."""
    si = _conectar_soap(host, user, password, dominio)
    try:
        result = _bulk_retrieve(si, vim.VirtualMachine, ["config.annotation"])
        annotations = {}
        for obj_content in result:
            texto = ""
            for prop in obj_content.propSet:
                if prop.name == "config.annotation":
                    texto = prop.val or ""
            if texto:
                annotations[obj_content.obj._moId] = texto
        return annotations
    finally:
        Disconnect(si)


# Nombres de carpeta que no aportan nada a una ruta visible -- raíz "vm" que vSphere crea
# sola dentro de cada Datacenter, y variantes de idioma/version conocidas. Cortar acá evita
# rutas tipo "vm/Engineering-Pool" cuando lo útil es solo "Engineering-Pool".
_FOLDERS_RAIZ_IGNORAR = {"vm", "discovered virtual machine", "datacenters"}


def obtener_folders(host: str, user: str, password: str, dominio: str,
                     timeout: float = 60) -> dict:
    """Lee la carpeta real (ruta completa) de cada VM en vCenter -- 2 bulk calls por
    PropertyCollector, no per-VM: 1) `parent` (MoRef) de cada VM, 2) `name`+`parent` de
    TODAS las carpetas del vCenter. Con eso arma la ruta completa caminando la cadena de
    padres en memoria, sin más llamadas de red -- mismo espíritu que obtener_annotations.

    Retorna {moref_vm: "Carpeta/Subcarpeta/..."} -- solo para VMs cuya carpeta padre no es
    la raíz "vm" del datacenter (ver _FOLDERS_RAIZ_IGNORAR), esa no aporta información."""
    si = _conectar_soap(host, user, password, dominio)
    try:
        folder_result = _bulk_retrieve(si, vim.Folder, ["name", "parent"])
        folder_names: dict[str, str] = {}
        folder_parents: dict[str, str] = {}
        for obj_content in folder_result:
            moid = obj_content.obj._moId
            for prop in obj_content.propSet:
                if prop.name == "name":
                    folder_names[moid] = prop.val
                elif prop.name == "parent":
                    folder_parents[moid] = getattr(prop.val, "_moId", None)

        def _ruta(folder_moid, _profundidad=0):
            if not folder_moid or _profundidad > 20:  # 20: guarda contra ciclo/dato corrupto, ninguna jerarquía real llega ahí
                return []
            nombre = folder_names.get(folder_moid)
            if nombre is None or nombre.strip().lower() in _FOLDERS_RAIZ_IGNORAR:
                return []
            return _ruta(folder_parents.get(folder_moid), _profundidad + 1) + [nombre]

        vm_result = _bulk_retrieve(si, vim.VirtualMachine, ["parent"])
        rutas = {}
        for obj_content in vm_result:
            moid = obj_content.obj._moId
            for prop in obj_content.propSet:
                if prop.name != "parent":
                    continue
                partes = _ruta(getattr(prop.val, "_moId", None))
                if partes:
                    rutas[moid] = "/".join(partes)
        return rutas
    finally:
        Disconnect(si)


# "Resources" es el Resource Pool raíz implícito que vSphere crea solo en cada
# Cluster/Host -- toda VM que no fue movida a un RP custom cuelga de ahí. Mostrar
# "Resources" como si fuera información real sería tan ruidoso como mostrar la
# carpeta raíz "vm" (ver _FOLDERS_RAIZ_IGNORAR arriba).
_RESOURCE_POOLS_RAIZ_IGNORAR = {"resources"}


def obtener_resource_pools(host: str, user: str, password: str, dominio: str,
                            timeout: float = 60) -> dict:
    """Lee el Resource Pool real asignado a cada VM -- 2 bulk calls por PropertyCollector,
    mismo espíritu que obtener_folders: 1) `resourcePool` (MoRef) de cada VM -- campo
    directo de vim.VirtualMachine, no hay que caminar la cadena de `parent` como con
    folders --, 2) `name` de todos los vim.ResourcePool del vCenter.

    Antes (core/vcenter_rest.py, REST): `rp_str` quedaba hardcodeado en '' siempre --
    la vSphere Automation API sí expone /api/vcenter/resource-pool, pero nunca se llamó
    (hallazgo real, corregido 2026-09-07 agregando esta función en vez de un fetch REST
    nuevo sin poder validarlo en vivo -- mismo mecanismo bulk ya probado por folders).

    Retorna {moref_vm: "nombre_resource_pool"} -- omite el RP raíz "Resources" (ver
    _RESOURCE_POOLS_RAIZ_IGNORAR), no aporta información distinta de "sin agrupar"."""
    si = _conectar_soap(host, user, password, dominio)
    try:
        rp_result = _bulk_retrieve(si, vim.ResourcePool, ["name"])
        rp_names: dict[str, str] = {}
        for obj_content in rp_result:
            moid = obj_content.obj._moId
            for prop in obj_content.propSet:
                if prop.name == "name":
                    rp_names[moid] = prop.val

        vm_result = _bulk_retrieve(si, vim.VirtualMachine, ["resourcePool"])
        resultado = {}
        for obj_content in vm_result:
            moid = obj_content.obj._moId
            for prop in obj_content.propSet:
                if prop.name != "resourcePool":
                    continue
                rp_moid = getattr(prop.val, "_moId", None)
                nombre = rp_names.get(rp_moid)
                if nombre and nombre.strip().lower() not in _RESOURCE_POOLS_RAIZ_IGNORAR:
                    resultado[moid] = nombre
        return resultado
    finally:
        Disconnect(si)


def obtener_topologia_computo(host: str, user: str, password: str, dominio: str,
                               timeout: float = 60) -> dict:
    """Ruta de cómputo real (Datacenter/Cluster/Host) de cada VM -- agregado 2026-09-07
    para la vista 'Cómputo' del Árbol vCenter (hasta ahora solo tenía la vista 'Carpetas',
    ver obtener_folders arriba). Mismo espíritu bulk que el resto de este archivo: 4
    PropertyCollector (Datacenter, ClusterComputeResource, HostSystem, VirtualMachine),
    ningún roundtrip por VM.

    A diferencia de obtener_folders (una sola cadena de `parent` homogénea, todo Folder),
    acá la cadena mezcla tipos distintos (Host -> Cluster o Folder -> ... -> Datacenter),
    así que se resuelve con un solo `entity_parent`/`entity_type` genérico en vez de un
    `_ruta()` especializado por tipo.

    Retorna {moref_vm: "Datacenter/Cluster/Host"} -- mismo formato de string con '/' que
    obtener_folders(), reutilizable tal cual por _build_folder_tree() en web/routes/api.py.
    Hosts standalone (sin cluster) usan el segmento literal 'Sin Cluster' en vez de
    omitirlo, para no confundir "no tiene cluster" con "no se pudo resolver"."""
    si = _conectar_soap(host, user, password, dominio)
    try:
        entity_name: dict[str, str] = {}
        entity_parent: dict[str, str] = {}
        entity_type: dict[str, str] = {}

        for entity_cls, tipo_str in (
            (vim.Datacenter, "datacenter"),
            (vim.ClusterComputeResource, "cluster"),
            (vim.HostSystem, "host"),
        ):
            for obj_content in _bulk_retrieve(si, entity_cls, ["name", "parent"]):
                moid = obj_content.obj._moId
                entity_type[moid] = tipo_str
                for prop in obj_content.propSet:
                    if prop.name == "name":
                        entity_name[moid] = prop.val
                    elif prop.name == "parent":
                        entity_parent[moid] = getattr(prop.val, "_moId", None)

        def _cluster_y_datacenter(host_moid, _profundidad=0):
            """Camina la cadena de padres desde un Host hasta encontrar su Cluster (si
            existe) y su Datacenter -- se detiene apenas tiene ambos o se acaba la cadena."""
            cluster_nombre = None
            datacenter_nombre = None
            moid = host_moid
            while moid and _profundidad < 20:  # guarda contra ciclo/dato corrupto
                tipo = entity_type.get(moid)
                if tipo == "cluster" and cluster_nombre is None:
                    cluster_nombre = entity_name.get(moid)
                elif tipo == "datacenter":
                    datacenter_nombre = entity_name.get(moid)
                    break
                moid = entity_parent.get(moid)
                _profundidad += 1
            return cluster_nombre, datacenter_nombre

        vm_result = _bulk_retrieve(si, vim.VirtualMachine, ["runtime.host"])
        rutas: dict[str, str] = {}
        for obj_content in vm_result:
            vm_moid = obj_content.obj._moId
            for prop in obj_content.propSet:
                if prop.name != "runtime.host":
                    continue
                host_moid = getattr(prop.val, "_moId", None)
                if not host_moid or host_moid not in entity_name:
                    continue
                host_nombre = entity_name[host_moid]
                cluster_nombre, datacenter_nombre = _cluster_y_datacenter(host_moid)
                partes = [datacenter_nombre or "Sin Datacenter", cluster_nombre or "Sin Cluster", host_nombre]
                rutas[vm_moid] = "/".join(partes)
        return rutas
    finally:
        Disconnect(si)


# Nombres de evento de "ruido" de alta frecuencia -- Alarm status changes y reconfig
# menores dominan el volumen (confirmado: eran ~4900 de 7359 filas en la tabla real,
# ver docs/analisis_arquitectura). Se descartan acá, antes de guardar nada, en vez de
# guardarlos y filtrarlos después -- mismo espíritu que "sin valores inventados": no
# tiene sentido persistir lo que ningún dashboard/ficha va a mostrar nunca.
_EVENTOS_RUIDO_IGNORAR = {
    "AlarmStatusChangedEvent", "AlarmActionTriggeredEvent", "AlarmClearedEvent",
    "AlarmAcknowledgedEvent", "TaskEvent", "EventEx", "ExtendedEvent",
    "UserLoginSessionEvent", "UserLogoutSessionEvent",
}


def obtener_eventos_tareas(host: str, user: str, password: str, dominio: str,
                            desde: "datetime | None" = None, timeout: float = 120) -> dict:
    """Eventos y tareas reales de vCenter (pestaña Monitor > Tasks and Events) por VM --
    agregado 2026-09-07. La vSphere Automation REST API (/api/vcenter/*) no tiene
    equivalente real para historial de eventos, por eso esto vive en SOAP igual que
    Notes/folder/resource_pool/topología (ver el resto de este archivo).

    Reemplaza el "Events": [] hardcodeado de core/vcenter_rest.py -- ese nunca trajo
    datos reales (hallazgo real, corregido 2026-09-07: VMTareaEvento no recibía filas
    nuevas desde agosto pese a que el resto de la extracción sí actualizaba a diario).

    Bulk real vía EventManager.QueryEvents con un filtro de tiempo (no per-VM) -- una
    sola llamada trae TODOS los eventos del vCenter en la ventana pedida, se agrupan acá
    por VM. `desde`: piso de tiempo (típicamente el evento más reciente ya guardado, ver
    caller en web/routes/inventario.py) -- sin esto, cada corrida traería el historial
    completo del vCenter, no solo lo nuevo.

    Retorna {"por_vm": {moref_vm: [{nombre_evento, mensaje, usuario, fecha, tipo}, ...]},
    "completo": bool, "cursor_hasta": datetime | None} -- "completo"=False cuando se
    cortó por el techo de tiempo/páginas antes de llegar a `desde`; en ese caso
    "cursor_hasta" es el evento más viejo realmente visto (no None), y el caller debe
    usar ESO como próximo piso en vez de "ahora", para no dejar un agujero permanente
    en la parte del backlog que todavía no se pidió."""
    si = _conectar_soap(host, user, password, dominio)
    try:
        content = si.RetrieveContent()
        event_manager = content.eventManager

        filter_spec = vim.event.EventFilterSpec()
        filter_spec.entity = vim.event.EventFilterSpec.ByEntity(
            entity=content.rootFolder,
            recursion=vim.event.EventFilterSpec.RecursionOption.all,
        )
        filter_spec.time = vim.event.EventFilterSpec.ByTime(
            beginTime=(desde or (datetime.utcnow() - timedelta(days=45))),
        )
        # Acota de entrada a los tipos de evento de vCenter reales que ya se usan en el
        # resto del sistema (ver kpi_utils/reglas de clonado) -- clone/create/deploy/
        # power/remove/destroy -- en vez de traer TODO (incluida la categoría de ruido
        # de arriba) y filtrar recién al guardar.
        # VmReconfiguredEvent SACADO del filtro (2026-09-07, confirmado con 2 backfills
        # reales): es el mismo "ruido de alta frecuencia" que ya documentó
        # docs/analisis_arquitectura (~4900 de 7359 filas viejas eran Reconfig/Alarm/Task) --
        # un solo backfill de 45 días para VCenter DT (588 VMs) llegó a 200.000 eventos
        # (el techo duro de páginas de abajo) con Reconfigured incluido, agrandando la
        # ventana de escritura a SQLite y arriesgando el timeout de 300s por servidor del
        # resto del pipeline. Sin Reconfigured, el volumen esperado es órdenes de magnitud
        # menor (los ~2459 eventos "reales" no-ruido de la tabla vieja, acumulados en
        # meses, no cientos de miles por corrida).
        filter_spec.eventTypeId = [
            "VmClonedEvent", "VmCreatedEvent", "VmDeployedEvent", "VmRegisteredEvent",
            "VmRemovedEvent", "VmBeingDestroyedEvent", "VmPoweredOnEvent", "VmPoweredOffEvent",
            "VmSuspendedEvent", "VmMigratedEvent", "VmRelocatedEvent",
            "VmGuestShutdownEvent", "VmGuestRebootEvent", "VmResettingEvent",
            "VmInstanceUuidChangedEvent", "VmMacChangedEvent", "VmMacAssignedEvent",
        ]

        collector = event_manager.CreateCollectorForEvents(filter=filter_spec)
        try:
            collector.SetCollectorPageSize(1000)
            resultado: dict[str, list] = {}
            fecha_mas_vieja_vista = None
            completo = True
            inicio = time.monotonic()
            # ReadNextEvents pagina hacia atrás en el tiempo desde el punto de partida del
            # collector (más nuevo -> más viejo) -- se repite hasta que no devuelve más
            # filas (llegó al piso `beginTime`, cobertura COMPLETA), hasta un techo duro de
            # páginas, o hasta un techo de tiempo real (90s) -- salvaguarda aparte del
            # filtro de tipos de arriba: si algún entorno real tiene de todos modos mucho
            # volumen en los tipos que sí importan, esto evita que un solo servidor consuma
            # el timeout de 300s del resto del pipeline (confirmado en vivo: un backfill
            # sin este techo tardó 5+ minutos en 1 vCenter). Si se corta por un techo,
            # `completo=False` y el caller NO debe avanzar el cursor hasta "ahora" -- solo
            # hasta el evento más viejo realmente visto, para no crear un agujero
            # permanente en la parte del backlog que todavía no se llegó a pedir.
            for _pagina in range(200):
                if time.monotonic() - inicio > 90:
                    completo = False
                    break
                eventos = collector.ReadNextEvents(1000)
                if not eventos:
                    break
                if _pagina == 199:
                    completo = False
                for ev in eventos:
                    creado = getattr(ev, "createdTime", None)
                    if creado and (fecha_mas_vieja_vista is None or creado < fecha_mas_vieja_vista):
                        fecha_mas_vieja_vista = creado
                    # pyVmomi devuelve el nombre CALIFICADO ("vim.event.VmReconfiguredEvent"),
                    # no el nombre corto -- bug real encontrado 2026-09-07 al purgar: el
                    # filtro de ruido de abajo comparaba contra nombres cortos y nunca
                    # matcheaba nada, dejando pasar exactamente lo que se quería frenar.
                    # Se guarda siempre el nombre corto, consistente con los datos legacy
                    # (VMTareaEvento.nombre_evento="VmClonedEvent", etc, ver kpi_utils y la
                    # atribución de creación/eliminación de VM en web/routes/api.py).
                    nombre_evento = type(ev).__name__.rsplit(".", 1)[-1]
                    if nombre_evento in _EVENTOS_RUIDO_IGNORAR:
                        continue
                    vm_ref = getattr(ev, "vm", None)
                    vm_moref = getattr(vm_ref, "vm", None) if vm_ref else None
                    vm_moid = getattr(vm_moref, "_moId", None)
                    if not vm_moid:
                        continue
                    resultado.setdefault(vm_moid, []).append({
                        "nombre_evento": nombre_evento,
                        "mensaje": getattr(ev, "fullFormattedMessage", "") or "",
                        "usuario": getattr(ev, "userName", "") or "",
                        "fecha": creado.strftime("%Y-%m-%d %H:%M:%S") if creado else "",
                        "tipo": "evento",
                    })
            return {
                "por_vm": resultado,
                "completo": completo,
                "cursor_hasta": None if completo else fecha_mas_vieja_vista,
            }
        finally:
            collector.DestroyCollector()
    finally:
        Disconnect(si)


def actualizar_annotation(host: str, user: str, password: str, dominio: str,
                           external_id: str, texto: str, timeout: float = 20) -> None:
    """Escribe el campo Annotation/Notes real de una VM en vCenter vía SOAP (ReconfigVM_Task).
    Levanta la excepción real si falla -- no se traga errores en silencio."""
    si = _conectar_soap(host, user, password, dominio)

    try:
        vm_ref = vim.VirtualMachine(external_id, si._stub)
        _ = vm_ref.name  # fuerza resolución -- si el MoRef es inválido/viejo, falla acá con un error claro

        spec = vim.vm.ConfigSpec(annotation=texto or "")
        task = vm_ref.ReconfigVM_Task(spec=spec)

        deadline = time.monotonic() + timeout
        while task.info.state not in (vim.TaskInfo.State.success, vim.TaskInfo.State.error):
            if time.monotonic() > deadline:
                raise TimeoutError(f"ReconfigVM_Task no terminó en {timeout}s")
            time.sleep(0.2)

        if task.info.state == vim.TaskInfo.State.error:
            raise RuntimeError(str(task.info.error.msg if task.info.error else task.info.error))
    finally:
        Disconnect(si)
