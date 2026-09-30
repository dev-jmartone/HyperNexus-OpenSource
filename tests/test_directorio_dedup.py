"""
tests/test_directorio_dedup.py
Tests unitarios y de integración para la detección y fusión de usuarios duplicados en DirectorioUsuario.
"""
import pytest
from unittest.mock import MagicMock
from web.db import db, DirectorioUsuario, Maquina, MaquinaUsuarioDir, AuditoriaLog
from web.directorio_dedup_utils import (
    es_candidato_duplicado,
    filtrar_candidatos_duplicados,
    elegir_canonico,
    detectar_duplicados_confirmados_ad,
    fusionar_directorio_usuarios,
)


def test_es_candidato_duplicado(app, db_session):
    u1 = DirectorioUsuario(username="marivas_cand1", nombre_completo="Mauricio Rivas Candidate", email="cand1@partner.com")
    u2 = DirectorioUsuario(username="mrivas_cand2", nombre_completo="Mauricio Rivas Candidate", email="cand1@partner.com")
    u3 = DirectorioUsuario(username="jdoe_cand3", nombre_completo="John Doe Candidate", email="jdoe_cand3@example.com")

    db_session.add_all([u1, u2, u3])
    db_session.commit()

    assert es_candidato_duplicado(u1, u2) is True
    assert es_candidato_duplicado(u1, u3) is False


def test_elegir_canonico(app, db_session):
    u_obs = DirectorioUsuario(username="marivas_ec1", sam_account_name=None, nombre_completo="Mauricio Rivas EC", email="marivas_ec@partner.com", activo_ad=True)
    u_can = DirectorioUsuario(username="mrivas_ec2", sam_account_name="mrivas_ec2", nombre_completo="Mauricio Rivas EC", email="marivas_ec@partner.com", activo_ad=True)

    db_session.add_all([u_obs, u_can])
    db_session.commit()

    info_ad = {
        "encontrado_ad": True,
        "sam_account_name": "mrivas_ec2",
        "email": "marivas_ec@partner.com",
        "nombre_completo": "Mauricio Rivas EC",
    }

    canonico, absorbido = elegir_canonico(u_obs, u_can, info_ad, info_ad)
    assert canonico.id == u_can.id
    assert absorbido.id == u_obs.id


def test_detectar_duplicados_confirmados_ad(app, db_session):
    u1 = DirectorioUsuario(username="marivas_det1", sam_account_name=None, nombre_completo="Mauricio Test Rivas Det", email="mrivas_det@example.com", activo_ad=True)
    u2 = DirectorioUsuario(username="mrivas_det2", sam_account_name="mrivas_det2", nombre_completo="Mauricio Test Rivas Det", email="mrivas_det@example.com", activo_ad=True)

    db_session.add_all([u1, u2])
    db_session.commit()

    mock_ad = MagicMock()
    mock_ad.verificar_usuarios.return_value = {
        "marivas_det1": {
            "encontrado_ad": True,
            "sam_account_name": "mrivas_det2",
            "email": "mrivas_det@example.com",
            "nombre_completo": "Mauricio Test Rivas Det",
        },
        "mrivas_det2": {
            "encontrado_ad": True,
            "sam_account_name": "mrivas_det2",
            "email": "mrivas_det@example.com",
            "nombre_completo": "Mauricio Test Rivas Det",
        },
    }

    duplicados = detectar_duplicados_confirmados_ad(ad_client=mock_ad)
    assert len(duplicados) >= 1
    target_pair = next((d for d in duplicados if d["canonico"]["username"] == "mrivas_det2"), None)
    assert target_pair is not None
    assert target_pair["absorbido"]["username"] == "marivas_det1"


from web.db import db, DirectorioUsuario, Maquina, MaquinaUsuarioDir, AuditoriaLog, Servidor


def test_fusionar_directorio_usuarios(app, db_session):
    srv = Servidor(nombre="SRV-TEST-FUS", host="127.0.0.1", tipo="horizon", origen="dt")
    db_session.add(srv)
    db_session.flush()

    u_can = DirectorioUsuario(username="can_user_fus", sam_account_name="can_user_fus", nombre_completo="Canónico Test Fus", email="can_fus@example.com")
    u_abs = DirectorioUsuario(username="abs_user_fus", sam_account_name=None, departamento="IT", empresa="PartnerCorp", notas="Nota vieja")
    m1 = Maquina(nombre="VM-TEST-1", servidor_id=srv.id, pool_id=None, empresa_id=None)
    m2 = Maquina(nombre="VM-TEST-2", servidor_id=srv.id, pool_id=None, empresa_id=None)

    db_session.add_all([u_can, u_abs, m1, m2])
    db_session.commit()

    # m1 tiene vínculo con u_can y u_abs (duplicado)
    v1_can = MaquinaUsuarioDir(maquina_id=m1.id, directorio_usuario_id=u_can.id)
    v1_abs = MaquinaUsuarioDir(maquina_id=m1.id, directorio_usuario_id=u_abs.id)
    # m2 solo tiene vínculo con u_abs
    v2_abs = MaquinaUsuarioDir(maquina_id=m2.id, directorio_usuario_id=u_abs.id)

    db_session.add_all([v1_can, v1_abs, v2_abs])
    db_session.commit()

    res = fusionar_directorio_usuarios(canonico_id=u_can.id, absorbido_id=u_abs.id, user_id=1, username_req="admin", ip="127.0.0.1")
    assert res["ok"] is True

    # u_abs debe haber sido eliminado de la DB
    assert DirectorioUsuario.query.get(u_abs.id) is None

    # u_can debe conservar los campos y haber heredado departamento y empresa
    u_can_updated = DirectorioUsuario.query.get(u_can.id)
    assert u_can_updated.departamento == "IT"
    assert u_can_updated.empresa == "PartnerCorp"
    assert u_can_updated.notas == "Nota vieja"

    # Los vínculos de m2 deben estar en u_can ahora
    m2_links = MaquinaUsuarioDir.query.filter_by(maquina_id=m2.id).all()
    assert len(m2_links) == 1
    assert m2_links[0].directorio_usuario_id == u_can.id

    # Auditar que la acción fue registrada
    aud = AuditoriaLog.query.filter_by(accion="fusionar_directorio_usuario", recurso_id=u_can.id).first()
    assert aud is not None


def test_api_duplicados_endpoints(admin_client, app, db_session):
    u1 = DirectorioUsuario(username="api_user1_ep", nombre_completo="API Test User Endpoints", email="api_ep@test.com")
    u2 = DirectorioUsuario(username="api_user2_ep", nombre_completo="API Test User Endpoints", email="api_ep@test.com")

    db_session.add_all([u1, u2])
    db_session.commit()

    # GET /api/directorio/duplicados
    resp_get = admin_client.get("/api/directorio/duplicados")
    assert resp_get.status_code == 200
    json_get = resp_get.get_json()
    assert json_get["ok"] is True

    # POST /api/directorio/duplicados/fusionar
    resp_post = admin_client.post("/api/directorio/duplicados/fusionar", json={
        "canonico_id": u1.id,
        "absorbido_id": u2.id
    })
    assert resp_post.status_code == 200
    json_post = resp_post.get_json()
    assert json_post["ok"] is True
    assert json_post["canonico_id"] == u1.id
    assert DirectorioUsuario.query.get(u2.id) is None
