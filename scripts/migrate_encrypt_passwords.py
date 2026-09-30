"""
scripts/migrate_encrypt_passwords.py
Re-cifra las contraseñas de Servidor que todavía están en el esquema viejo (base64 plano,
encryption_key_version=1) usando Fernet real (encryption_key_version=2).

IMPORTANTE: correr primero contra una COPIA de data/inventario.db y confirmar que las
contraseñas siguen desencriptando bien antes de tocar la base real. Requiere FERNET_KEY
configurada en .env.

Uso:
    python scripts/migrate_encrypt_passwords.py            # aplica los cambios
    python scripts/migrate_encrypt_passwords.py --dry-run  # solo muestra qué haría
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import db, Servidor

dry_run = "--dry-run" in sys.argv

app = create_app()
with app.app_context():
    pendientes = Servidor.query.filter(Servidor.encryption_key_version < 2).all()
    if not pendientes:
        print("Nada para migrar: todos los servidores ya usan Fernet (encryption_key_version=2).")
        raise SystemExit(0)

    print(f"{len(pendientes)} servidor(es) con contraseña en esquema viejo (base64).")
    for s in pendientes:
        try:
            plano = s.password  # lee con la lógica legacy (encryption_key_version==1 -> base64)
        except Exception as e:
            print(f"  [ERROR] Servidor '{s.nombre}' (id={s.id}): no se pudo leer la contraseña actual: {e}")
            continue

        if dry_run:
            print(f"  [DRY-RUN] Servidor '{s.nombre}' (id={s.id}): se re-cifraría con Fernet.")
            continue

        s.password = plano  # el setter ya cifra con Fernet y sube encryption_key_version a 2
        db.session.add(s)
        print(f"  [OK] Servidor '{s.nombre}' (id={s.id}) re-cifrado.")

    if not dry_run:
        db.session.commit()
        print("Listo. Verificá que cada Servidor siga autenticando bien antes de dar por cerrada la migración.")
