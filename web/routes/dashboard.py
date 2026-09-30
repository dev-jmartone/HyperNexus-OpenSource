import os
from flask import Blueprint, render_template, send_from_directory, make_response
from sqlalchemy import func

from web.db import db, Servidor, InventarioSnapshot, Maquina
from web.kpi_utils import clasificar_estado_maquina

bp_dashboard = Blueprint("dashboard", __name__)

# Estados válidos de snapshot completado
_ESTADOS_OK = ("ok", "completado")


@bp_dashboard.route("/")
def index():
    dist_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
    if os.environ.get("LEGACY_UI") != "1" and os.path.exists(os.path.join(dist_dir, "index.html")):
        # send_from_directory no fuerza revalidación acá -- el navegador puede quedarse
        # con un index.html viejo (que apunta al bundle JS de un build anterior) sin que
        # un F5 normal lo note, porque el archivo referenciado adentro SÍ tiene hash
        # nuevo pero el HTML que lo referencia quedó cacheado. Confirmado real
        # 2026-09-04: cambios de frontend no se veían pese a build+restart correctos.
        # Los assets con hash (/assets/*.js|css) sí pueden cachearse largo, ESTE archivo no.
        resp = make_response(send_from_directory(dist_dir, "index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp


    # KPIs globales desde último snapshot de cada servidor (Fallback Jinja)
    subq = (
        db.session.query(
            InventarioSnapshot.servidor_id,
            func.max(InventarioSnapshot.id).label("max_id")
        )
        .filter(InventarioSnapshot.estado.in_(_ESTADOS_OK))
        .group_by(InventarioSnapshot.servidor_id)
        .subquery()
    )

    maquinas = (
        Maquina.query
        .join(InventarioSnapshot)
        .filter(
            InventarioSnapshot.id == db.session.query(subq.c.max_id)
            .filter(subq.c.servidor_id == Maquina.servidor_id)
            .scalar_subquery()
        )
        .all()
    )

    estados = [clasificar_estado_maquina(m) for m in maquinas]

    total        = len(maquinas)
    total_vdi    = sum(1 for m in maquinas if m.tipo == "VDI")
    total_vm     = sum(1 for m in maquinas if m.tipo == "VM")
    conectadas   = sum(1 for e in estados if e["conectada"])
    disponibles  = sum(1 for e in estados if e["disponible"])
    huerfanas    = sum(1 for e in estados if e["huerfana"])
    desconectadas= sum(1 for e in estados if e["desconectada"])
    error_count  = sum(1 for e in estados if e["en_error"])

    # Distribución por empresa
    emp_count: dict[str, int] = {}
    for m in maquinas:
        emp = m.empresa or "Sin asignar"
        emp_count[emp] = emp_count.get(emp, 0) + 1
    emp_count = dict(sorted(emp_count.items(), key=lambda x: -x[1]))

    # Distribución por origen
    origen_count: dict[str, int] = {}
    for m in maquinas:
        o = m.origen or "—"
        origen_count[o] = origen_count.get(o, 0) + 1

    # Distribución por pool (top 10)
    pool_count: dict[str, int] = {}
    for m in maquinas:
        p = m.pool or "Sin Pool"
        pool_count[p] = pool_count.get(p, 0) + 1
    pool_count = dict(sorted(pool_count.items(), key=lambda x: -x[1])[:10])

    # Snapshots recientes
    snapshots_recientes = (
        InventarioSnapshot.query
        .order_by(InventarioSnapshot.timestamp.desc())
        .limit(10)
        .all()
    )

    # Estado de servidores
    total_servidores = Servidor.query.filter_by(activo=True).count()

    kpis = {
        "total":         total,
        "total_vdi":     total_vdi,
        "total_vm":      total_vm,
        "conectadas":    conectadas,
        "disponibles":   disponibles,
        "huerfanas":     huerfanas,
        "desconectadas": desconectadas,
        "error_count":   error_count,
        "servidores":    total_servidores,
    }

    return render_template(
        "dashboard.html",
        kpis=kpis,
        emp_count=emp_count,
        origen_count=origen_count,
        pool_count=pool_count,
        snapshots_recientes=snapshots_recientes,
    )

