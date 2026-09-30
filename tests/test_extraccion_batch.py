"""
tests/test_extraccion_batch.py
Cobertura del rediseño batch del motor de extracción (2026-09-07): el índice en
memoria que reemplaza el fallback O(N) de _save_or_update_maquina_impl, y la
deduplicación en memoria de _guardar_tareas_eventos_vcenter. Ninguno de los dos
tenía test antes -- exactamente la superficie donde vivían los bugs reales de
la sesión de agosto (matching Horizon<->vCenter).
"""
from datetime import datetime

from web.db import db, Servidor, Maquina, VMTareaEvento
from web.routes.inventario import (
    _save_or_update_maquina,
    _construir_indice_nombre_limpio,
    _guardar_tareas_eventos_vcenter,
)


def _crear_servidor(db_session, nombre="Horizon Test"):
    srv = Servidor(nombre=nombre, host="fake.local", tipo="horizon")
    db_session.add(srv)
    db_session.commit()
    return srv


def _kwargs_base(servidor_id, nombre_vm):
    return dict(
        servidor_id=servidor_id,
        snapshot_id=None,
        nombre_vm=nombre_vm,
        tipo="VDI",
        origen_str="dt",
        pool_str="Pool-Test",
        empresa_str="",
        usuario_asignado="",
        estado_horizon="AVAILABLE",
        estado_vcenter=None,
        manager="",
        agent_version="",
        so="",
        cpu=2,
        ram_gb=4.0,
        disk_gb=60.0,
        dns="",
        ip="",
        vcenter_host=None,
        correcciones={},
    )


def test_indice_nombre_limpio_encuentra_fila_existente(app, db_session):
    """El índice batch debe encontrar una VM ya guardada por su nombre limpio,
    igual que el fallback O(N) viejo (sin índice) -- mismo resultado, otro camino."""
    srv = _crear_servidor(db_session)

    # Se guarda una vez SIN índice (camino viejo) con el nombre "PC-01.corp.local"
    maq1, is_new1 = _save_or_update_maquina(**_kwargs_base(srv.id, "PC-01.corp.local"))
    assert is_new1 is True

    # Construir el índice DESPUÉS de que la fila ya existe (simula el inicio de una
    # corrida nueva) y guardar la MISMA VM con el nombre formateado distinto
    # ("PC-01" sin sufijo FQDN) -- debe reencontrar la fila, no duplicarla.
    indice = _construir_indice_nombre_limpio(srv.id)
    assert "PC-01" in indice

    maq2, is_new2 = _save_or_update_maquina(
        **_kwargs_base(srv.id, "PC-01"), indice_nombre_limpio=indice
    )
    assert is_new2 is False
    assert maq2.id == maq1.id
    assert Maquina.query.filter_by(servidor_id=srv.id).count() == 1


def test_indice_nombre_limpio_se_actualiza_en_vivo_dentro_del_mismo_batch(app, db_session):
    """Una VM creada a mitad de un batch debe ser visible para las siguientes
    llamadas del MISMO batch sin volver a consultar la DB (el índice se actualiza
    en el momento de crear la fila, ver _save_or_update_maquina_impl)."""
    srv = _crear_servidor(db_session, nombre="vCenter Test")
    indice = _construir_indice_nombre_limpio(srv.id)  # vacío, servidor recién creado
    assert indice == {}

    maq1, is_new1 = _save_or_update_maquina(
        **_kwargs_base(srv.id, "PC-NUEVA.corp.local"), indice_nombre_limpio=indice
    )
    assert is_new1 is True
    # El índice en memoria (mismo dict pasado arriba) ya debe tener la fila nueva,
    # sin volver a golpear la DB.
    assert indice.get("PC-NUEVA") is not None
    assert indice["PC-NUEVA"].id == maq1.id

    maq2, is_new2 = _save_or_update_maquina(
        **_kwargs_base(srv.id, "PC-NUEVA"), indice_nombre_limpio=indice
    )
    assert is_new2 is False
    assert maq2.id == maq1.id
    assert Maquina.query.filter_by(servidor_id=srv.id).count() == 1


def test_camino_sin_indice_sigue_funcionando_igual(app, db_session):
    """indice_nombre_limpio=None (default) debe seguir dando el mismo resultado que
    antes de 2026-09-07 -- es el rollback en caliente si el camino batch da problemas."""
    srv = _crear_servidor(db_session, nombre="Horizon Sin Indice")
    maq1, _ = _save_or_update_maquina(**_kwargs_base(srv.id, "PC-LEGACY.corp.local"))
    maq2, is_new2 = _save_or_update_maquina(**_kwargs_base(srv.id, "PC-LEGACY"))
    assert is_new2 is False
    assert maq2.id == maq1.id
    assert Maquina.query.filter_by(servidor_id=srv.id).count() == 1


def test_guardar_eventos_vcenter_deduplica_en_memoria(app, db_session):
    """_guardar_tareas_eventos_vcenter no debe insertar el mismo (nombre_evento,
    fecha) dos veces -- ni dentro de una misma lista de eventos, ni entre dos
    llamadas separadas (misma máquina, evento ya persistido)."""
    srv = _crear_servidor(db_session, nombre="vCenter Eventos")
    maq, _ = _save_or_update_maquina(**_kwargs_base(srv.id, "PC-EVENTOS"))

    fecha_evento = "2026-09-07 10:00:00"
    eventos = [
        {"nombre_evento": "VmPoweredOnEvent", "mensaje": "encendida", "usuario": "corp\\user", "fecha": fecha_evento},
        {"nombre_evento": "VmPoweredOnEvent", "mensaje": "encendida (dup)", "usuario": "corp\\user", "fecha": fecha_evento},
    ]
    _guardar_tareas_eventos_vcenter(maq.id, eventos)
    db.session.commit()

    assert VMTareaEvento.query.filter_by(maquina_id=maq.id).count() == 1

    # Segunda llamada, mismo evento -- no debe duplicar contra lo ya persistido.
    _guardar_tareas_eventos_vcenter(maq.id, eventos[:1])
    db.session.commit()
    assert VMTareaEvento.query.filter_by(maquina_id=maq.id).count() == 1

    # Evento genuinamente nuevo -- sí debe insertarse.
    _guardar_tareas_eventos_vcenter(maq.id, [
        {"nombre_evento": "VmPoweredOffEvent", "mensaje": "apagada", "fecha": "2026-09-07 11:00:00"},
    ])
    db.session.commit()
    assert VMTareaEvento.query.filter_by(maquina_id=maq.id).count() == 2
