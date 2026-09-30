"""
server_prod.py
Entrypoint de producción WSGI con Waitress para inventario-vdi.
"""
import os
import sys
import webbrowser
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from waitress import serve
from web.app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    threads = int(os.environ.get("THREADS", 16))

    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n{'='*55}")
    print(f"  Inventario VDI — Servidor Producción (Waitress WSGI)")
    print(f"  http://127.0.0.1:{port} / http://0.0.0.0:{port}")
    print(f"  Threads concurrentes: {threads}")
    print(f"{'='*55}\n")

    serve(app, host=host, port=port, threads=threads)
