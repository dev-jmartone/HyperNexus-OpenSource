"""
web/auth.py
Sistema de autenticación + decoradores de login/rol.
"""
import functools
from datetime import datetime

from flask import (session, redirect, url_for, request,
                   flash, g, abort)

from web.db import db, Usuario, registrar_auditoria


# ── Session helpers ───────────────────────────────────────────────────

def get_current_user() -> Usuario | None:
    """Retorna el usuario logueado o None."""
    uid = session.get("user_id")
    if uid is None:
        return None
    return db.session.get(Usuario, uid)


def login_user(user: Usuario):
    session.clear()
    session["user_id"]  = user.id
    session["username"] = user.username
    session["rol"]      = user.rol
    user.last_login = datetime.utcnow()
    registrar_auditoria(
        accion="login",
        recurso=None,
        detalle=f"Login exitoso",
        usuario_id=user.id,
        username=user.username,
        ip=request.remote_addr,
    )
    db.session.commit()


def logout_user():
    uid      = session.get("user_id")
    username = session.get("username")
    if uid:
        registrar_auditoria(
            accion="logout",
            usuario_id=uid,
            username=username,
            ip=request.remote_addr,
        )
        db.session.commit()
    session.clear()


# ── Decoradores ───────────────────────────────────────────────────────

def login_required(f):
    """Redirige al login si el usuario no está autenticado."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Devuelve 403 si el usuario no es admin."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login", next=request.url))
        if session.get("rol") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Inyección en templates ────────────────────────────────────────────

def inject_current_user():
    """Disponible como `current_user` en todos los templates."""
    return {"current_user": get_current_user()}


# ── Audit helper (shortcut) ───────────────────────────────────────────

def audit(accion: str, recurso: str = None, detalle: str = None):
    """Registra auditoría usando el usuario de la sesión actual."""
    registrar_auditoria(
        accion=accion,
        recurso=recurso,
        detalle=detalle,
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
