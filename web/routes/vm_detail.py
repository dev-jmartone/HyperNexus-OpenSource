"""
web/routes/vm_detail.py
Página de detalle de una VM/VDI: estado actual + historial de usuarios.
"""
from flask import Blueprint, render_template, abort
from sqlalchemy import func

from web.db import db, Maquina, InventarioSnapshot, HistorialUsuarioVDI, Servidor
from web.auth import login_required

bp_vm = Blueprint("vm", __name__, url_prefix="/vm")


@bp_vm.route("/<path:nombre>")
@login_required
def detalle(nombre: str):
    """Página de detalle de una VM/VDI por nombre."""

    # Obtener la instancia más reciente de esta VM
    subq = (
        db.session.query(
            InventarioSnapshot.servidor_id,
            func.max(InventarioSnapshot.id).label("max_id")
        )
        .filter(InventarioSnapshot.estado.in_(("ok", "completado")))
        .group_by(InventarioSnapshot.servidor_id)
        .subquery()
    )

    maquina = (
        Maquina.query
        .join(InventarioSnapshot)
        .filter(
            Maquina.nombre == nombre,
            InventarioSnapshot.id == db.session.query(subq.c.max_id)
            .filter(subq.c.servidor_id == Maquina.servidor_id)
            .scalar_subquery()
        )
        .first()
    )

    if not maquina:
        # Intentar encontrar cualquier registro histórico
        maquina = Maquina.query.filter_by(nombre=nombre).order_by(Maquina.id.desc()).first()
        if not maquina:
            abort(404)

    # Historial completo de usuarios de esta VM
    historial = (
        HistorialUsuarioVDI.query
        .filter_by(nombre_vm=nombre)
        .order_by(HistorialUsuarioVDI.detectado_en.desc())
        .all()
    )

    # Todos los snapshots que contienen esta VM (timeline)
    timeline = (
        Maquina.query
        .join(InventarioSnapshot)
        .filter(Maquina.nombre == nombre)
        .order_by(InventarioSnapshot.timestamp.desc())
        .limit(50)
        .all()
    )

    servidor = Servidor.query.get(maquina.servidor_id) if maquina.servidor_id else None

    # Usuarios únicos históricos
    usuarios_unicos = list(dict.fromkeys(
        h.usuario_nuevo for h in historial if h.usuario_nuevo
    ))

    # Historial de cambios detectados (Deltas en atributos)
    from web.db import MaquinaHistorial
    cambios_historial = (
        MaquinaHistorial.query
        .filter_by(maquina_id=maquina.id)
        .order_by(MaquinaHistorial.detectado_en.desc())
        .limit(100)
        .all()
    )

    return render_template(
        "vm_detalle.html",
        maquina=maquina,
        servidor=servidor,
        historial=historial,
        timeline=timeline,
        usuarios_unicos=usuarios_unicos,
        cambios_historial=cambios_historial,
    )
