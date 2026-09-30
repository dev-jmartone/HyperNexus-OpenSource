"""
web/routes/auth_routes.py
Login, logout y gestión de usuarios.
"""
from datetime import datetime

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, session, abort)

from datetime import timedelta

from web.db import db, Usuario, AuditoriaLog, registrar_auditoria
from web.auth import login_user, logout_user, login_required, admin_required, audit
from web.extensions import limiter

bp_auth = Blueprint("auth", __name__)

# Fuerza bruta: tras MAX_INTENTOS_FALLIDOS seguidos, la cuenta se bloquea por
# BLOQUEO_MINUTOS. Las columnas ya existían en Usuario (intentos_fallidos,
# bloqueado_hasta) pero login() nunca las usaba — cualquiera podía probar
# contraseñas indefinidamente contra un username conocido.
MAX_INTENTOS_FALLIDOS = 5
BLOQUEO_MINUTOS = 15


# ── Login / Logout ────────────────────────────────────────────────────

@bp_auth.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard.index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Mismo mensaje genérico para user inexistente, contraseña incorrecta Y cuenta
        # bloqueada — no distinguir evita que un atacante use la respuesta para
        # enumerar qué usernames existen o cuáles están bloqueados.
        error = "Usuario o contraseña incorrectos."
        user = Usuario.query.filter_by(username=username, activo=True).first()
        bloqueado = bool(user and user.bloqueado_hasta and user.bloqueado_hasta > datetime.utcnow())

        if user and not bloqueado and user.check_password(password):
            user.intentos_fallidos = 0
            user.bloqueado_hasta = None
            login_user(user)
            next_url = request.args.get("next") or url_for("dashboard.index")
            return redirect(next_url)

        if user and not bloqueado:
            user.intentos_fallidos = (user.intentos_fallidos or 0) + 1
            if user.intentos_fallidos >= MAX_INTENTOS_FALLIDOS:
                user.bloqueado_hasta = datetime.utcnow() + timedelta(minutes=BLOQUEO_MINUTOS)

        registrar_auditoria(
            accion="login_bloqueado" if bloqueado else "login_fallido",
            recurso=username,
            detalle="Intento de login sobre cuenta bloqueada" if bloqueado else "Intento de login fallido",
            ip=request.remote_addr,
        )
        db.session.commit()

    return render_template("login.html", error=error)


@bp_auth.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# ── Gestión de usuarios (admin only) ─────────────────────────────────

@bp_auth.route("/usuarios")
@admin_required
def usuarios():
    users = Usuario.query.order_by(Usuario.username).all()
    return render_template("usuarios.html", usuarios=users)


@bp_auth.route("/usuarios/crear", methods=["POST"])
@admin_required
def crear_usuario():
    try:
        username = request.form["username"].strip()
        if Usuario.query.filter_by(username=username).first():
            flash(f"El usuario '{username}' ya existe.", "error")
            return redirect(url_for("auth.usuarios"))

        pwd = request.form.get("password", "").strip() or "1234"
        u = Usuario(
            username=username,
            rol=request.form.get("rol", "usuario"),
            nombre_completo=request.form.get("nombre_completo", "").strip(),
            email=request.form.get("email", "").strip(),
            activo=True,
            must_change_password=True,
        )
        u.set_password(pwd)
        db.session.add(u)
        audit("crear_usuario", recurso=username, detalle=f"rol={u.rol}")
        db.session.commit()
        flash(f"Usuario '{username}' creado (Contraseña: {pwd}).", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "error")
    return redirect(url_for("auth.usuarios"))


# ── Cambiar Contraseña ──────────────────────────────────────────────

@bp_auth.route("/cambiar-password", methods=["GET", "POST"])
@login_required
def cambiar_password():
    error = None
    if request.method == "POST":
        actual = request.form.get("password_actual", "")
        nueva = request.form.get("password_nueva", "").strip()
        confirmacion = request.form.get("password_confirmacion", "").strip()

        from web.auth import get_current_user
        user = get_current_user()

        if not user or not user.check_password(actual):
            error = "La contraseña actual es incorrecta."
        elif len(nueva) < 4:
            error = "La nueva contraseña debe tener al menos 4 caracteres."
        elif nueva != confirmacion:
            error = "La nueva contraseña y la confirmación no coinciden."
        elif nueva == "1234":
            error = "Debes elegir una contraseña diferente a la predeterminada (1234)."
        else:
            user.set_password(nueva)
            user.must_change_password = False
            audit("cambiar_password", recurso=user.username, detalle="Cambio de contraseña exitoso")
            db.session.commit()
            flash("Contraseña actualizada con éxito.", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("cambiar_password.html", error=error)


@bp_auth.route("/usuarios/<int:uid>/editar", methods=["POST"])
@admin_required
def editar_usuario(uid: int):
    u = Usuario.query.get_or_404(uid)
    try:
        u.rol            = request.form.get("rol", u.rol)
        u.nombre_completo= request.form.get("nombre_completo", u.nombre_completo or "").strip()
        u.email          = request.form.get("email", u.email or "").strip()
        u.activo         = "activo" in request.form
        pwd = request.form.get("password", "").strip()
        if pwd:
            u.set_password(pwd)
        audit("editar_usuario", recurso=u.username, detalle=f"rol={u.rol}, activo={u.activo}")
        db.session.commit()
        flash(f"Usuario '{u.username}' actualizado.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "error")
    return redirect(url_for("auth.usuarios"))


@bp_auth.route("/usuarios/<int:uid>/eliminar", methods=["POST"])
@admin_required
def eliminar_usuario(uid: int):
    u = Usuario.query.get_or_404(uid)
    if u.rol == "admin" and Usuario.query.filter(Usuario.rol == "admin", Usuario.id != u.id, Usuario.activo == True).count() == 0:
        flash("No se puede eliminar: es el único usuario admin activo.", "error")
        return redirect(url_for("auth.usuarios"))
    username = u.username
    try:
        audit("eliminar_usuario", recurso=username)
        # Desvincular registros de auditoría para no romper la FK
        AuditoriaLog.query.filter_by(usuario_id=u.id).update({"usuario_id": None})
        db.session.delete(u)
        db.session.commit()
        flash(f"Usuario '{username}' eliminado.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al eliminar usuario: {e}", "error")
    return redirect(url_for("auth.usuarios"))


# ── Auditoría ─────────────────────────────────────────────────────────

@bp_auth.route("/auditoria")
@admin_required
def auditoria():
    page = int(request.args.get("page", 1))
    per_page = 50
    accion_filter  = request.args.get("accion", "")
    usuario_filter = request.args.get("username", "")

    q = AuditoriaLog.query.order_by(AuditoriaLog.timestamp.desc())
    if accion_filter:
        q = q.filter(AuditoriaLog.accion == accion_filter)
    if usuario_filter:
        q = q.filter(AuditoriaLog.username.ilike(f"%{usuario_filter}%"))

    total = q.count()
    logs  = q.offset((page - 1) * per_page).limit(per_page).all()
    acciones_disponibles = [r[0] for r in db.session.query(AuditoriaLog.accion).distinct().all()]

    return render_template(
        "auditoria.html",
        logs=logs,
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, (total + per_page - 1) // per_page),
        acciones_disponibles=sorted(acciones_disponibles),
        filtros={"accion": accion_filter, "username": usuario_filter},
    )
