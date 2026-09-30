"""
web/app.py
Aplicación Flask principal del sistema Inventario VDI.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from flask import Flask, session, redirect, url_for, request
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError
from web.db import db, init_db, get_db_path
from web.extensions import limiter

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

migrate = Migrate()


def create_app() -> Flask:
    """Crea y configura la app Flask."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        raise RuntimeError(
            "SECRET_KEY no configurada. Copiá .env.example a .env y completá los valores "
            "(ver instrucciones ahí para generar SECRET_KEY y FERNET_KEY)."
        )
    app.config["SECRET_KEY"] = secret_key
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{get_db_path()}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FORCE_HTTPS", "0") == "1"

    # Inicializar extensiones
    db.init_app(app)
    migrate.init_app(app, db)

    # journal_mode=DELETE (no WAL): WAL requiere mmap del archivo -shm, que los
    # recursos de red SMB/CIFS no soportan de forma confiable — con WAL sobre una
    # ruta de red SMB (ej. \\fileserver\share\...) esto puede generar locking issues
    # bajo acceso concurrente (ver scheduler.py + requests web al mismo tiempo).
    # DELETE usa locking por rangos de bytes, que SMB soporta mejor.
    # synchronous=FULL (no NORMAL) porque NORMAL solo es seguro ante pérdida de
    # energía en modo WAL — en DELETE, NORMAL puede perder transacciones.
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=DELETE;")
            cursor.execute("PRAGMA synchronous=FULL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()
        except Exception:
            pass

    init_db(app)

    # CSRF (double-submit token): protege también /api/* — el SPA React pide el token vía
    # GET /api/csrf-token y lo manda en header X-CSRFToken en cada request mutante (ver
    # interceptor en web/frontend/src/services/api.js). Antes /api/* estaba con
    # csrf.exempt(bp_api), lo que dejaba todo el CRUD (crear/editar/eliminar servidores,
    # usuarios, máquinas, etc.) sin protección CSRF real, apoyado solo en SameSite=Lax.
    csrf = CSRFProtect(app)

    # Rate limiting: capa extra sobre el lockout por cuenta (que solo actúa después de
    # loguear un username válido) — acá se limita por IP, cubriendo también el escaneo
    # de usernames inexistentes. Límite estricto en /login vía @limiter.limit en las
    # vistas (auth_routes.py, api.py); límite general razonable en todo /api/* más abajo.
    limiter.init_app(app)

    # Inyectar current_user en todos los templates
    from web.auth import inject_current_user
    app.context_processor(inject_current_user)

    # Registrar blueprints
    from web.routes.auth_routes import bp_auth
    from web.routes.dashboard import bp_dashboard
    from web.routes.servidores import bp_servidores
    from web.routes.inventario import bp_inventario
    from web.routes.reportes import bp_reportes
    from web.routes.api import bp_api
    from web.routes.vm_detail import bp_vm
    from web.routes.directorio import bp_directorio

    app.register_blueprint(bp_auth)
    app.register_blueprint(bp_dashboard)
    app.register_blueprint(bp_servidores)
    app.register_blueprint(bp_inventario)
    app.register_blueprint(bp_reportes)
    app.register_blueprint(bp_api)
    app.register_blueprint(bp_vm)
    app.register_blueprint(bp_directorio)

    limiter.limit("300 per minute")(bp_api)

    # Servir assets del frontend Vite React en dist/assets
    @app.route("/assets/<path:filename>")
    def serve_assets(filename):
        from flask import send_from_directory
        dist_assets = os.path.join(os.path.dirname(__file__), "frontend", "dist", "assets")
        return send_from_directory(dist_assets, filename)

    # Servir favicon.svg
    @app.route("/favicon.svg")
    @app.route("/favicon.ico")
    def serve_favicon():
        from flask import send_from_directory
        public_dir = os.path.join(os.path.dirname(__file__), "frontend", "public")
        return send_from_directory(public_dir, "favicon.svg")

    # Proteger todas las rutas (excepto login/static/api.auth_*) con login_required global
    @app.before_request
    def require_login():
        allowed_endpoints = {"auth.login", "auth.logout", "api.auth_login", "api.auth_me", "api.csrf_token", "static", "serve_assets", "serve_favicon"}
        if request.endpoint in allowed_endpoints:
            return
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                from flask import jsonify
                return jsonify({"error": "No autorizado", "authenticated": False}), 401
            return redirect(url_for("auth.login", next=request.url))
        
        # Verificar si el usuario requiere cambio obligatorio de contraseña
        from web.auth import get_current_user
        user = get_current_user()
        if user and user.must_change_password and request.endpoint != "auth.cambiar_password" and not request.path.startswith("/api/"):
            return redirect(url_for("auth.cambiar_password"))

    # Página 403
    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template("403.html"), 403

    # Token CSRF ausente/inválido: el SPA consume JSON, no la página de error HTML default.
    @app.errorhandler(CSRFError)
    def csrf_error(e):
        if request.path.startswith("/api/"):
            from flask import jsonify
            return jsonify({"error": "Token CSRF inválido o expirado. Recargá la página e intentá de nuevo."}), 400
        from flask import render_template
        return render_template("403.html", mensaje=e.description), 400

    # Página 404
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template("404.html"), 404

    # Iniciar planificador de extracción automática en segundo plano (cada 5 min).
    # Se salta en tests (ver tests/conftest.py) — no tiene sentido un hilo de fondo
    # sondeando credenciales/DB real en cada test que crea una app nueva.
    if not os.environ.get("INVENTARIO_SKIP_SCHEDULER"):
        try:
            from web.scheduler import start_auto_scheduler, start_retention_purger
            start_auto_scheduler(app, default_key="5m")
            start_retention_purger(app)
        except Exception as e_sched:
            print(f"[App Warning] No se pudo iniciar el planificador automático: {e_sched}")

    return app
