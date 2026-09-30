"""Tests de web/kpi_utils.py — clasificación de estado y provisionamiento.
Son funciones puras (reciben un objeto tipo Maquina), no necesitan DB ni app.
"""
from types import SimpleNamespace

from web.kpi_utils import clasificar_estado_maquina, clasificar_provisionamiento


def _maquina(**kwargs):
    """Construye un stand-in liviano de Maquina con los atributos que
    clasificar_estado_maquina() lee vía getattr."""
    base = dict(estado_horizon="", estado_vcenter="", usuario_asignado="", in_error_state=False)
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_conectada_por_estado_horizon_connected():
    m = _maquina(estado_horizon="CONNECTED", usuario_asignado="jdoe")
    r = clasificar_estado_maquina(m)
    assert r["conectada"] is True
    assert r["disponible"] is False


def test_disponible_por_estado_horizon_available():
    m = _maquina(estado_horizon="AVAILABLE")
    r = clasificar_estado_maquina(m)
    assert r["disponible"] is True
    assert r["conectada"] is False


def test_huerfana_disponible_sin_usuario():
    m = _maquina(estado_horizon="AVAILABLE", usuario_asignado="")
    r = clasificar_estado_maquina(m)
    assert r["huerfana"] is True


def test_no_huerfana_si_tiene_usuario():
    m = _maquina(estado_horizon="AVAILABLE", usuario_asignado="jdoe")
    r = clasificar_estado_maquina(m)
    assert r["huerfana"] is False


def test_vm_vcenter_pura_sin_estado_horizon_infiere_por_power_state():
    # Sin estado_horizon (VM exclusiva de vCenter): se infiere de power_state + usuario.
    m = _maquina(estado_horizon="", estado_vcenter="POWERED_ON", usuario_asignado="jdoe")
    r = clasificar_estado_maquina(m)
    assert r["conectada"] is True
    assert r["encendida"] is True


def test_en_error_por_in_error_state():
    m = _maquina(estado_horizon="AVAILABLE", in_error_state=True)
    r = clasificar_estado_maquina(m)
    assert r["en_error"] is True


def test_en_error_por_texto_unreachable():
    m = _maquina(estado_horizon="AGENT_UNREACHABLE")
    r = clasificar_estado_maquina(m)
    assert r["en_error"] is True


def test_apagada_por_power_state():
    m = _maquina(estado_vcenter="POWERED_OFF")
    r = clasificar_estado_maquina(m)
    assert r["apagada"] is True
    assert r["encendida"] is False


# ── clasificar_provisionamiento ─────────────────────────────────────────

def test_master_tiene_prioridad_sobre_template():
    # Antes TEMPLATE pisaba a MASTER -- una golden image real casi siempre termina
    # convertida a Template en vCenter para publicarla (flujo normal de Horizon Instant
    # Clone), así que con esa prioridad vieja una master real nunca podía verse como
    # MASTER. Confirmado como causa raíz real de conteo de masters mal en 2026-08-12.
    assert clasificar_provisionamiento("cualquier-pool", es_template=True, es_master=True) == "MASTER"


def test_master_sin_template():
    assert clasificar_provisionamiento("cualquier-pool", es_template=False, es_master=True) == "MASTER"


def test_vm_estatica_sin_pool():
    assert clasificar_provisionamiento("", es_template=False, es_master=False) == "VM_ESTATICA"
    assert clasificar_provisionamiento("Estática") == "VM_ESTATICA"
    assert clasificar_provisionamiento("Sin Pool (vCenter)") == "VM_ESTATICA"


def test_vdi_pool_con_pool_real():
    assert clasificar_provisionamiento("Engineering-Pool") == "VDI_POOL"
