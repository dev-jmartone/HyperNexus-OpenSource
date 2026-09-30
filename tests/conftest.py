"""
tests/conftest.py
Fixtures compartidas. IMPORTANTE: nunca corre contra data/inventario.db real —
INVENTARIO_DB_PATH apunta a un sqlite temporal que se borra al terminar la sesión,
e INVENTARIO_SKIP_SCHEDULER evita que arranquen los hilos de fondo (AutoScheduler,
RetentionPurger) durante los tests.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY", "test-secret-key-solo-para-tests-no-usar-en-produccion")
os.environ["INVENTARIO_SKIP_SCHEDULER"] = "1"
# String vacío, NO pop(): web/app.py hace load_dotenv() al importarse, que rellena
# cualquier var AUSENTE desde .env — un pop() acá se deshace apenas se importa create_app.
# Con la key presente (aunque vacía) load_dotenv() no la toca, y web/jobs.py._get_redis()
# la trata como "no configurada" → fuerza fallback en memoria (nunca pegarle al Redis real).
os.environ["REDIS_URL"] = ""

# El Limiter de Flask-Limiter es un singleton (web/extensions.py) compartido por todas las
# apps que create_app() instancia durante la sesión de tests — su storage de conteos NO se
# resetea entre create_app() calls. Si quedara habilitado, tests que golpean /login o
# /api/auth/login varias veces seguidas (los de lockout) podrían chocar con el límite de
# tasa y fallar de forma no determinística según el orden de ejecución. Deshabilitado acá
# por default; el test dedicado a rate limiting (test_security_findings.py) lo reactiva
# puntualmente con monkeypatch y llama limiter.reset() al terminar.
from web.extensions import limiter as _limiter
_limiter.enabled = False


@pytest.fixture(scope="session")
def app():
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="inventario_test_")
    os.environ["INVENTARIO_DB_PATH"] = db_path

    from web.app import create_app
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    yield flask_app

    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_session(app):
    """Da acceso a la sesión de SQLAlchemy dentro de un app_context activo."""
    with app.app_context():
        from web.db import db
        yield db.session


@pytest.fixture()
def admin_user(app, db_session):
    """Usuario admin de prueba — get_or_create para no chocar entre tests. Resetea
    intentos_fallidos/bloqueado_hasta en cada uso: la fila persiste entre tests (mismo
    username), y sin este reset un test de lockout dejaba la cuenta bloqueada para el
    siguiente test que pidiera este mismo fixture."""
    from web.db import Usuario
    u = Usuario.query.filter_by(username="test_admin").first()
    if not u:
        u = Usuario(username="test_admin", rol="admin", activo=True, must_change_password=False)
        u.set_password("Sup3rS3cret!2026")
        db_session.add(u)
    u.intentos_fallidos = 0
    u.bloqueado_hasta = None
    db_session.commit()
    return u


@pytest.fixture()
def usuario_normal(app, db_session):
    from web.db import Usuario
    u = Usuario.query.filter_by(username="test_usuario").first()
    if not u:
        u = Usuario(username="test_usuario", rol="usuario", activo=True, must_change_password=False)
        u.set_password("OtraClave!2026")
        db_session.add(u)
    u.intentos_fallidos = 0
    u.bloqueado_hasta = None
    db_session.commit()
    return u


@pytest.fixture()
def admin_client(client, admin_user):
    """Cliente con sesión de admin ya iniciada (evita repetir el POST /login en cada test)."""
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user.id
        sess["username"] = admin_user.username
        sess["rol"] = admin_user.rol
    return client


@pytest.fixture()
def usuario_client(client, usuario_normal):
    with client.session_transaction() as sess:
        sess["user_id"] = usuario_normal.id
        sess["username"] = usuario_normal.username
        sess["rol"] = usuario_normal.rol
    return client
