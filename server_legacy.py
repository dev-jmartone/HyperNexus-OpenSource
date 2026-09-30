"""
server_legacy.py
Servidor con la interfaz Jinja Flask original (Legacy Mode) en el puerto 3001.
"""
import os
import sys
import webbrowser
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Forzar interfaz Jinja antigua
os.environ["LEGACY_UI"] = "1"
os.environ["PORT"] = "3001"

from waitress import serve
from web.app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = 3001
    threads = 16

    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n{'='*60}")
    print(f"  Inventario VDI — Servidor Interfaz Anterior (Legacy Jinja)")
    print(f"  URL: http://127.0.0.1:{port} / http://0.0.0.0:{port}")
    print(f"  Modo: LEGACY_UI=1")
    print(f"{'='*60}\n")

    serve(app, host=host, port=port, threads=threads)
