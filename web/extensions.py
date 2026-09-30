"""
web/extensions.py
Instancias de extensiones Flask compartidas entre web/app.py (que las inicializa vía
init_app) y los blueprints de rutas (que las usan como decoradores) — separadas en su
propio módulo para evitar el import circular routes -> app -> routes.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Sin default_limits: solo se limitan explícitamente /login y /api/* (ver create_app()
# en web/app.py y los decoradores @limiter.limit en auth_routes.py / api.py). Storage en
# memoria del proceso — coherente con el resto del sistema (threading, no multi-worker;
# ver web/scheduler.py y CLAUDE.md).
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://", default_limits=[])
