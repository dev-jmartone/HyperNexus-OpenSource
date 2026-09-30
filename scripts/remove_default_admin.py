"""
scripts/remove_default_admin.py
Elimina el usuario 'admin' (el admin/admin sembrado por versiones viejas del sistema).

Uso:
    python scripts/remove_default_admin.py

Requiere que ya exista OTRO usuario admin activo (creado desde la pantalla de Usuarios,
o vía ADMIN_BOOTSTRAP_USER/ADMIN_BOOTSTRAP_PASSWORD en el .env en un arranque limpio) —
si no, aborta para no dejar el sistema sin ningún admin.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import db, Usuario

app = create_app()
with app.app_context():
    otros_admins = Usuario.query.filter(
        Usuario.rol == "admin", Usuario.username != "admin", Usuario.activo == True
    ).count()
    if otros_admins == 0:
        raise SystemExit(
            "Abortado: no hay otro usuario admin activo. Creá uno desde la pantalla de "
            "Usuarios (o con ADMIN_BOOTSTRAP_USER/ADMIN_BOOTSTRAP_PASSWORD en un arranque "
            "limpio) antes de correr este script."
        )

    admin = Usuario.query.filter_by(username="admin").first()
    if not admin:
        print("No existe usuario 'admin' — nada que hacer.")
        raise SystemExit(0)

    from web.db import AuditoriaLog
    AuditoriaLog.query.filter_by(usuario_id=admin.id).update({"usuario_id": None})
    db.session.delete(admin)
    db.session.commit()
    print("Usuario 'admin' eliminado correctamente.")
