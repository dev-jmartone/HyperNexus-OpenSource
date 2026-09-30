"""Tests de guardar_credencial_encriptada / obtener_credencial_desencriptada
(web/db.py) — bóveda temporal de credenciales vCenter/Horizon."""
from datetime import datetime, timedelta


def test_guardar_y_obtener_roundtrip(app, db_session, admin_user):
    from web.db import guardar_credencial_encriptada, obtener_credencial_desencriptada
    with app.app_context():
        guardar_credencial_encriptada(admin_user.id, "MiClaveSecreta123", ttl_seconds=1800)
        pwd = obtener_credencial_desencriptada(admin_user.id)
    assert pwd == "MiClaveSecreta123"


def test_no_se_guarda_en_texto_plano_en_la_columna(app, db_session, admin_user):
    from web.db import guardar_credencial_encriptada, SesionCredencialTemp
    with app.app_context():
        guardar_credencial_encriptada(admin_user.id, "OtraClaveDistinta", ttl_seconds=1800)
        row = SesionCredencialTemp.query.filter_by(usuario_id=admin_user.id).first()
        assert row is not None
        assert "OtraClaveDistinta" not in row.clave_encriptada


def test_credencial_expirada_devuelve_none_y_se_borra(app, db_session, admin_user):
    from web.db import guardar_credencial_encriptada, obtener_credencial_desencriptada, SesionCredencialTemp
    with app.app_context():
        guardar_credencial_encriptada(admin_user.id, "ClaveQueVence", ttl_seconds=1800)
        row = SesionCredencialTemp.query.filter_by(usuario_id=admin_user.id).first()
        row.expira_en = datetime.utcnow() - timedelta(seconds=1)
        db_session.commit()

        pwd = obtener_credencial_desencriptada(admin_user.id)
        assert pwd is None
        assert SesionCredencialTemp.query.filter_by(usuario_id=admin_user.id).first() is None


def test_guardar_de_nuevo_sobreescribe_no_duplica(app, db_session, admin_user):
    from web.db import guardar_credencial_encriptada, obtener_credencial_desencriptada, SesionCredencialTemp
    with app.app_context():
        guardar_credencial_encriptada(admin_user.id, "Primera", ttl_seconds=1800)
        guardar_credencial_encriptada(admin_user.id, "Segunda", ttl_seconds=1800)
        filas = SesionCredencialTemp.query.filter_by(usuario_id=admin_user.id).count()
        assert filas == 1
        assert obtener_credencial_desencriptada(admin_user.id) == "Segunda"


def test_usuario_sin_credencial_devuelve_none(app, db_session):
    from web.db import obtener_credencial_desencriptada
    with app.app_context():
        assert obtener_credencial_desencriptada(999999) is None
