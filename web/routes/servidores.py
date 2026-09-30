"""
web/routes/servidores.py
CRUD de servidores Horizon y vCenter.
"""
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash

from web.db import db, Servidor
from web.auth import login_required, admin_required, audit

bp_servidores = Blueprint("servidores", __name__, url_prefix="/servidores")

ORIGENES  = ["", "dt", "su", "core", "mz"]
TIPOS     = ["horizon", "vcenter", "appvolumes"]
TIPOS_MAQ = ["VDI", "VM", "ambos"]


@bp_servidores.route("/")
@login_required
def index():
    servidores = Servidor.query.order_by(Servidor.tipo, Servidor.nombre).all()
    return render_template(
        "servidores.html",
        servidores=servidores,
        origenes=ORIGENES,
        tipos=TIPOS,
        tipos_maquina=TIPOS_MAQ,
    )


@bp_servidores.route("/crear", methods=["POST"])
@admin_required
def crear():
    try:
        s = Servidor(
            nombre       = request.form["nombre"].strip(),
            host         = request.form["host"].strip(),
            tipo         = request.form["tipo"],
            tipo_maquina = request.form["tipo_maquina"],
            origen       = request.form.get("origen", ""),
            usuario      = request.form.get("usuario", "").strip(),
            dominio      = request.form.get("dominio", "").strip(),
            activo       = True,
        )
        pwd = request.form.get("password", "").strip()
        if pwd:
            s.password = pwd
        db.session.add(s)
        db.session.commit()
        audit("crear_servidor", recurso=s.nombre, detalle=f"host={s.host}, tipo={s.tipo}, origen={s.origen}")
        flash(f"Servidor '{s.nombre}' creado.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al crear servidor: {e}", "error")
    return redirect(url_for("servidores.index"))


@bp_servidores.route("/<int:sid>/editar", methods=["POST"])
@admin_required
def editar(sid: int):
    s = Servidor.query.get_or_404(sid)
    try:
        s.nombre       = request.form["nombre"].strip()
        s.host         = request.form["host"].strip()
        s.tipo         = request.form["tipo"]
        s.tipo_maquina = request.form["tipo_maquina"]
        s.origen       = request.form.get("origen", "")
        s.usuario      = request.form.get("usuario", "").strip()
        s.dominio      = request.form.get("dominio", "").strip()
        pwd = request.form.get("password", "").strip()
        if pwd:
            s.password = pwd
        s.activo = "activo" in request.form
        db.session.commit()
        audit("editar_servidor", recurso=s.nombre, detalle=f"activo={s.activo}")
        flash(f"Servidor '{s.nombre}' actualizado.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "error")
    return redirect(url_for("servidores.index"))


# ── Credenciales en Memoria / Token Clock API ────────────────────────

import time
from flask import session
from web.auth import get_current_user

@bp_servidores.route("/api/credenciales", methods=["POST"])
@login_required
def guardar_credenciales_sesion():
    data = request.get_json(silent=True) or request.form
    password = data.get("password", "").strip()
    ttl = int(data.get("ttl", 1800))  # 30 minutos por defecto

    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "No autorizado"}), 401
    default_email = (user.email.strip() if user and user.email else user.username) if user else ""
    usuario = data.get("usuario", "").strip() or default_email

    if not password:
        return jsonify({"ok": False, "error": "Contraseña de vCenter/Horizon requerida"}), 400

    from web.db import guardar_credencial_encriptada
    guardar_credencial_encriptada(user.id, password, ttl_seconds=ttl)
    session.pop("vc_password", None)
    session["vc_usuario"] = usuario

    audit("set_vcenter_credentials", recurso=usuario, detalle=f"TTL={ttl}s")
    return jsonify({
        "ok": True,
        "usuario": usuario,
        "expires_in": ttl,
    })


@bp_servidores.route("/api/credenciales/status", methods=["GET"])
@login_required
def status_credenciales_sesion():
    user = get_current_user()
    if not user:
        return jsonify({"active": False, "remaining_seconds": 0, "usuario": ""})

    user_email = (user.email.strip() if user and user.email else user.username) if user else ""
    from web.db import obtener_credencial_desencriptada
    pwd = obtener_credencial_desencriptada(user.id)
    is_active = bool(pwd)

    return jsonify({
        "active": is_active,
        "remaining_seconds": 1800 if is_active else 0,
        "usuario": user_email,
    })


@bp_servidores.route("/<int:sid>/eliminar", methods=["POST"])
@admin_required
def eliminar(sid: int):
    s = Servidor.query.get_or_404(sid)
    nombre = s.nombre
    try:
        audit("eliminar_servidor", recurso=nombre)
        db.session.delete(s)
        db.session.commit()
        flash(f"Servidor '{nombre}' eliminado.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "error")
    return redirect(url_for("servidores.index"))


@bp_servidores.route("/api/list")
@login_required
def api_list():
    servidores = Servidor.query.filter_by(activo=True).all()
    return jsonify([s.to_dict() for s in servidores])
