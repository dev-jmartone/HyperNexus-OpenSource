"""Tests que documentan hallazgos del informe de seguridad (docs/informe_seguridad_2026-08-10.md).
Los que empiezan con test_VULN_ describen el estado ACTUAL vulnerable a propósito — cuando se
aplique el fix correspondiente, estos tests van a FALLAR y hay que reescribirlos para afirmar
el comportamiento seguro (ver comentario en cada uno)."""
import os


def test_path_traversal_en_descarga_de_reportes_bloqueado(admin_client, tmp_path, monkeypatch):
    """FIX APLICADO — web/routes/reportes.py:70 (/reportes/descargar/<nombre>) ahora usa
    send_from_directory (antes: send_file + os.path.join sin sanitizar). En Windows, un
    nombre con backslashes ('..\\.env') escapaba REPORTES_DIR y leía cualquier archivo
    legible por el proceso — confirmado en vivo contra el .env real durante el audit
    (leyó SECRET_KEY/FERNET_KEY). send_from_directory usa safe_join internamente: un path
    que escapa el directorio permitido siempre 404, sin importar el separador usado."""
    import web.routes.reportes as reportes_mod

    # Archivo "secreto" fuera de REPORTES_DIR, en el padre — simula .env sin tocar el real.
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("CONTENIDO_QUE_NO_DEBERIA_SER_LEGIBLE", encoding="utf-8")
    reportes_dir = tmp_path / "reportes"
    reportes_dir.mkdir()
    monkeypatch.setattr(reportes_mod, "REPORTES_DIR", str(reportes_dir))

    resp = admin_client.get("/reportes/descargar/..%5Csecreto.txt", follow_redirects=True)  # %5C = backslash
    assert b"CONTENIDO_QUE_NO_DEBERIA_SER_LEGIBLE" not in resp.data
    assert resp.status_code == 200  # redirect siguiendo a /reportes/ con flash "no encontrado"


def test_ad_client_usernames_maliciosos_no_llegan_al_texto_del_script(monkeypatch, tmp_path):
    """FIX APLICADO — core/ad_client.py (ADClient.verificar_usuarios). Antes, json.dumps(usernames)
    se interpolaba crudo dentro de un string PowerShell de comillas simples
    ($rawInput = '{json_usernames}'). JSON no escapa comillas simples, así que un username con '
    rompía el contexto del string y el resto se ejecutaba como código PowerShell (RCE),
    alcanzable sin rol admin vía POST /api/importar_extraidos -> username malicioso ->
    se disparaba al correr /api/verificar_ad.

    Ahora los usernames se escriben a un archivo JSON aparte y el script solo lee ESE archivo
    (Get-Content -Raw | ConvertFrom-Json) — nunca forman parte del texto del script en sí.
    Este test ejecuta el método real (con subprocess.run mockeado, sin PowerShell de verdad) e
    inspecciona el .ps1 generado ANTES de que se borre en el finally."""
    import subprocess as subprocess_mod
    from core.ad_client import ADClient

    monkeypatch.delenv("DEMO_MODE", raising=False)
    payload = "a'; Write-Host 'INYECTADO'; $x='b"
    capturado = {}

    def fake_run(cmd, **kwargs):
        script_path = cmd[cmd.index("-File") + 1]
        with open(script_path, "r", encoding="utf-8-sig") as f:
            capturado["script_text"] = f.read()
        return subprocess_mod.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess_mod, "run", fake_run)

    ad = ADClient(domain="corp.local")
    ad.verificar_usuarios([payload])

    assert "script_text" in capturado, "el mock de subprocess.run no se llamó — revisar el test"
    assert payload not in capturado["script_text"], (
        "el payload malicioso apareció en el texto del script — el fix de parametrización se rompió"
    )
    assert "Get-Content" in capturado["script_text"] and "ConvertFrom-Json" in capturado["script_text"]


def test_usuario_se_bloquea_tras_intentos_fallidos_repetidos(client, admin_user):
    """FIX APLICADO — ver test_login_bloquea_tras_intentos_fallidos_repetidos en test_auth.py
    para el mismo hallazgo desde el ángulo de integración HTTP. Acá se valida directo el modelo:
    intentos_fallidos sube con cada fallo y bloqueado_hasta se setea al superar el umbral."""
    from web.routes.auth_routes import MAX_INTENTOS_FALLIDOS

    for _ in range(MAX_INTENTOS_FALLIDOS + 3):
        client.post("/login", data={"username": admin_user.username, "password": "mal"})

    assert admin_user.intentos_fallidos >= MAX_INTENTOS_FALLIDOS
    assert admin_user.bloqueado_hasta is not None


def test_api_auth_login_se_bloquea_tras_intentos_fallidos_repetidos(client, admin_user):
    """HIGH-1 tenía un agujero: el fix original solo tocó web/routes/auth_routes.py:login()
    (vista Jinja legacy). El SPA React (producto activo, ver CLAUDE.md) autentica contra
    /api/auth/login (web/routes/api.py::auth_login), que NO tenía el chequeo de lockout —
    alguien podía fuerza-bruta indefinidamente vía la API aunque el login Jinja ya estuviera
    protegido. Ahora auth_login reusa MAX_INTENTOS_FALLIDOS/BLOQUEO_MINUTOS de auth_routes."""
    from web.routes.auth_routes import MAX_INTENTOS_FALLIDOS

    for _ in range(MAX_INTENTOS_FALLIDOS):
        resp = client.post("/api/auth/login", json={"username": admin_user.username, "password": "mal"})
        assert resp.status_code == 401

    # Contraseña correcta en el intento siguiente: sigue rechazado, cuenta bloqueada.
    resp = client.post("/api/auth/login", json={"username": admin_user.username, "password": "Sup3rS3cret!2026"})
    assert resp.status_code == 401
    assert resp.get_json()["success"] is False


def test_csrf_bloquea_post_a_api_sin_token(admin_user):
    """FIX APLICADO — antes web/app.py hacía csrf.exempt(bp_api) sobre TODO el blueprint,
    dejando el CRUD completo (servidores/usuarios/máquinas/config) sin protección CSRF real,
    apoyado solo en SameSite=Lax. Ahora CSRFProtect cubre /api/* también: un POST sin el
    header X-CSRFToken se rechaza con 400 JSON (no la página HTML default de Flask-WTF,
    ver csrf_error() en web/app.py).

    Usa una app aparte con WTF_CSRF_ENABLED=True (la fixture de sesión lo desactiva para
    no tener que fabricar tokens en cada test existente)."""
    from web.app import create_app

    app_csrf = create_app()
    app_csrf.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    client = app_csrf.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user.id
        sess["username"] = admin_user.username
        sess["rol"] = admin_user.rol

    resp = client.post("/api/config/intervalo", json={"intervalo": "off"})
    assert resp.status_code == 400
    assert "csrf" in resp.get_json()["error"].lower() or "CSRF" in resp.get_json()["error"]


def test_csrf_token_valido_permite_post_a_api(admin_user):
    """Contraparte del test anterior: pidiendo el token vía GET /api/csrf-token y
    mandándolo en el header X-CSRFToken, el mismo POST que antes se rechazaba pasa."""
    from web.app import create_app

    app_csrf = create_app()
    app_csrf.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    client = app_csrf.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user.id
        sess["username"] = admin_user.username
        sess["rol"] = admin_user.rol

    token = client.get("/api/csrf-token").get_json()["csrf_token"]
    resp = client.post(
        "/api/config/intervalo",
        json={"intervalo": "off"},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200


def test_rate_limit_bloquea_login_tras_muchos_intentos_por_ip(monkeypatch, admin_user):
    """FIX APLICADO — capa extra sobre el lockout por cuenta (que solo actúa DESPUÉS de
    identificar un username válido): Flask-Limiter ahora limita /login y /api/auth/login
    a 10 intentos por minuto POR IP, cubriendo también el escaneo de usernames inexistentes
    (que nunca dispara el lockout porque ese solo cuenta sobre una cuenta real).

    limiter.enabled queda en False durante toda la suite (ver conftest.py) para que otros
    tests que hacen varios POST /login seguidos no choquen con el límite de forma no
    determinística — acá se reactiva puntualmente y se resetea el storage al terminar."""
    from web.extensions import limiter
    from web.app import create_app

    monkeypatch.setattr(limiter, "enabled", True)
    try:
        app_rl = create_app()
        app_rl.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        client = app_rl.test_client()

        ultimo = None
        for _ in range(11):
            ultimo = client.post("/api/auth/login", json={"username": "usuario-inexistente", "password": "x"})

        assert ultimo.status_code == 429
    finally:
        limiter.reset()


def test_session_cookie_secure_off_por_defecto(app):
    """FIX APLICADO — web/app.py ahora setea SESSION_COOKIE_SECURE = (FORCE_HTTPS == "1").
    Default off (FORCE_HTTPS sin definir) para no romper deployments actuales sobre HTTP
    directo — la app fixture de test la crea sin FORCE_HTTPS."""
    assert app.config.get("SESSION_COOKIE_SECURE") is False


def test_session_cookie_secure_se_activa_con_force_https(monkeypatch):
    """FIX APLICADO — con FORCE_HTTPS=1 (deployment real detrás de HTTPS), la cookie de
    sesión sale con flag Secure. Crea una segunda app aparte (misma DB temporal ya
    migrada por la fixture de sesión) solo para inspeccionar el config resultante."""
    monkeypatch.setenv("FORCE_HTTPS", "1")
    from web.app import create_app

    app_https = create_app()
    assert app_https.config.get("SESSION_COOKIE_SECURE") is True
