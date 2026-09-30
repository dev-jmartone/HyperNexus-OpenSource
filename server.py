"""
server.py
Entrypoint: python server.py
Levanta Flask y abre el browser automáticamente.
"""
import os
import sys
import webbrowser
import threading

# Agregar raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n{'='*50}")
    print(f"  Inventario VDI — Flask Server")
    print(f"  http://127.0.0.1:{port}")
    print(f"{'='*50}\n")

    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
