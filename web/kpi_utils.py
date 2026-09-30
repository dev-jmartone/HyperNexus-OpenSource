"""
web/kpi_utils.py
Fuente única de clasificación de estado/provisionamiento de una Maquina.

Antes había 3 implementaciones independientes de "conectada/disponible/huérfana"
(web/routes/dashboard.py, web/routes/api.py /kpis, web/routes/api.py /kpis/desglose)
que podían dar números distintos para el mismo dataset. Todas usan ahora las funciones
de este módulo, así que dashboard legacy y API nueva siempre coinciden.
"""

_POOLS_SIN_ASIGNAR = {"", "estática", "estatica", "sin pool (vcenter)", "sin pool"}

# Tipos de MaquinaHistorial.campo_modificado que le importan a un admin (feed de
# Actividad/Novedades y widget de conteo). El resto (ip/dns/vcenter_host/folder/
# resource_pool/datastores/so/manager/agent_version/annotation/connection_state/
# hardware_version) es sincronización de infraestructura rutinaria, no un evento —
# se sigue guardando en MaquinaHistorial (auditoría completa vía "ver todo"), pero
# no se muestra por default porque ahogaba a los cambios que sí importan.
TIPOS_EVENTO_IMPORTANTES = {
    "creacion", "eliminacion", "migracion",
    "usuario_asignado", "pool",
    "estado_horizon", "estado_vcenter",
    "tools_status", "estado_horizon_agente",
    "in_error_state", "maintenance_mode", "disco_critico",
}


def clasificar_estado_maquina(m) -> dict:
    """Clasificación única de estado operativo. Regla (la más completa de las 3 viejas):
    - Si hay estado_horizon explícito, manda ese.
    - Si no hay estado_horizon (VM pura de vCenter), se infiere de power_state + usuario asignado.
    """
    h_state = (m.estado_horizon or "").upper()
    p_state = (m.estado_vcenter or "").upper()
    is_on = p_state in ("POWERED_ON", "POWEREDON")
    is_off = p_state in ("POWERED_OFF", "POWEREDOFF")
    tiene_usuario = bool(m.usuario_asignado)

    conectada = h_state == "CONNECTED" or (not h_state and is_on and tiene_usuario)
    disponible = h_state == "AVAILABLE" or (not h_state and is_on and not tiene_usuario)
    huerfana = not tiene_usuario and disponible
    en_error = any(x in h_state for x in ("UNREACHABLE", "ERROR", "PROBLEM")) or bool(getattr(m, "in_error_state", False))
    desconectada = h_state == "DISCONNECTED"

    return {
        "conectada": conectada,
        "disponible": disponible,
        "huerfana": huerfana,
        "en_error": en_error,
        "desconectada": desconectada,
        "encendida": is_on,
        "apagada": is_off,
    }


def es_huerfana(m) -> bool:
    """Unica definicion valida de 'huerfana': VM disponible/encendida sin usuario
    asignado (ver clasificar_estado_maquina). Antes /api/huerfanas, /api/semaforo e
    /api/integridad/summary tenian 3 condiciones booleanas ligeramente distintas
    escritas a mano -- podian (y de hecho daban) numeros distintos para el mismo
    dataset (ej. integridad contaba TODAS las VMs sin usuario, incluidas apagadas,
    templates y masters, infladno el conteo varias veces por encima del real).
    Usar siempre esta funcion en vez de reescribir la condicion."""
    return clasificar_estado_maquina(m)["huerfana"]


def clasificar_provisionamiento(pool_str: str, es_template: bool = False, es_master: bool = False) -> str:
    """MASTER: golden image que Horizon usa para clonar un pool.
    TEMPLATE: template de vCenter (no es una VM en uso).
    VDI_POOL: VDI con pool asignado.
    VM_ESTATICA: sin pool (VM/VDI standalone)."""
    # MASTER antes que TEMPLATE: una golden image casi siempre termina convertida a
    # Template en vCenter para publicarla (es justamente el flujo normal de Horizon
    # Instant Clone) -- con TEMPLATE primero, toda master convertida a template perdía
    # la clasificación MASTER en la ficha/reportes, aunque siguiera siendo la imagen
    # activa de la que cuelgan pools reales. Verificado 2026-08-12: causa confirmada de
    # por qué el conteo de masters activas salía mal.
    if es_master:
        return "MASTER"
    if es_template:
        return "TEMPLATE"
    if (pool_str or "").strip().lower() in _POOLS_SIN_ASIGNAR:
        return "VM_ESTATICA"
    return "VDI_POOL"
