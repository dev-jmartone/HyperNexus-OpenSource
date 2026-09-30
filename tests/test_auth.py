"""Tests de autenticación: login/logout, gate de admin, y el gap de fuerza bruta
(test_login_sin_limite_de_intentos documenta el hallazgo del informe de seguridad —
se espera que falle el día que se implemente el lockout, a propósito)."""


def test_login_correcto_redirige_y_crea_sesion(client, admin_user):
    resp = client.post("/login", data={"username": "test_admin", "password": "Sup3rS3cret!2026"})
    assert resp.status_code in (302, 303)
    with client.session_transaction() as sess:
        assert sess.get("user_id") == admin_user.id


def test_login_incorrecto_no_crea_sesion(client, admin_user):
    resp = client.post("/login", data={"username": "test_admin", "password": "clave-incorrecta"})
    assert resp.status_code == 200  # re-renderiza login.html con error, no redirige
    with client.session_transaction() as sess:
        assert sess.get("user_id") is None


def test_login_usuario_inexistente_no_revela_si_el_user_existe(client):
    resp = client.post("/login", data={"username": "no-existe-este-user", "password": "x"})
    assert b"Usuario o contrase" in resp.data  # mismo mensaje genérico que password incorrecta


def test_ruta_sin_login_redirige_a_login(client):
    resp = client.get("/dashboard" if False else "/", follow_redirects=False)
    # cualquier ruta protegida sin sesión → redirect a /login (before_request global en web/app.py)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("Location", "")


def test_api_sin_login_devuelve_401_json(client):
    resp = client.get("/api/kpis")
    assert resp.status_code == 401
    assert resp.get_json()["authenticated"] is False


def test_logout_limpia_sesion(admin_client):
    admin_client.get("/logout")
    with admin_client.session_transaction() as sess:
        assert sess.get("user_id") is None


def test_ruta_admin_only_bloquea_usuario_normal(usuario_client):
    resp = usuario_client.get("/usuarios")
    assert resp.status_code == 403


def test_ruta_admin_only_permite_admin(admin_client):
    resp = admin_client.get("/usuarios")
    assert resp.status_code == 200


def test_config_intervalo_post_bloquea_no_admin(usuario_client):
    resp = usuario_client.post("/api/config/intervalo", json={"intervalo": "off"})
    assert resp.status_code == 403


def test_config_intervalo_post_permite_admin(admin_client):
    resp = admin_client.post("/api/config/intervalo", json={"intervalo": "off"})
    assert resp.status_code == 200
    assert resp.get_json()["key"] == "off"


def test_login_bloquea_tras_intentos_fallidos_repetidos(client, admin_user):
    """FIX APLICADO — ver CRIT/HIGH-1 en el informe de seguridad. Usuario.intentos_fallidos/
    bloqueado_hasta ahora sí se usan: tras MAX_INTENTOS_FALLIDOS (5) seguidos, la cuenta se
    bloquea por BLOQUEO_MINUTOS aunque la contraseña correcta se use después."""
    for _ in range(5):
        client.post("/login", data={"username": "test_admin", "password": "incorrecta"})

    # Con la contraseña CORRECTA, el intento 6º sigue rechazado — la cuenta quedó bloqueada.
    resp = client.post("/login", data={"username": "test_admin", "password": "Sup3rS3cret!2026"})
    assert resp.status_code == 200  # re-renderiza login.html con error, no redirige
    with client.session_transaction() as sess:
        assert sess.get("user_id") is None


def test_login_correcto_antes_del_umbral_resetea_intentos(client, admin_user):
    """Fallar un par de veces y loguear bien después no debe dejar la cuenta a mitad de
    camino hacia un bloqueo accidental en el próximo login legítimo."""
    for _ in range(3):
        client.post("/login", data={"username": "test_admin", "password": "incorrecta"})

    resp = client.post("/login", data={"username": "test_admin", "password": "Sup3rS3cret!2026"})
    assert resp.status_code in (302, 303)
    assert admin_user.intentos_fallidos == 0
    assert admin_user.bloqueado_hasta is None
