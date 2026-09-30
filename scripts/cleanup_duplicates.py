"""
scripts/cleanup_duplicates.py
Ejecuta la rutina de desduplicación y fusión limpia sobre la BD SQLite actual.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.routes.inventario import _validar_y_reconciliar_payload

def main():
    app = create_app()
    with app.app_context():
        print("Iniciando deduplicación y fusión de registros duplicados en inventario.db...")
        _validar_y_reconciliar_payload(log_callback=print)
        print("Limpieza de duplicados finalizada con éxito.")

if __name__ == "__main__":
    main()
