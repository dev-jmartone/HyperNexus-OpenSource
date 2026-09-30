"""Tests de los endpoints /api/granja/* y de la extensión de /api/directorio/usuarios/<id>."""


def test_granja_farms_api_devuelve_apps_rds_servers_y_autorizados(app, db_session, admin_client):
    from web.db import Farm, AplicacionPublicada, AplicacionEntitlement, FarmRdsServer

    farm = Farm(nombre="Farm-API-01", display_name="Farm API 01", origen="dt")
    db_session.add(farm)
    db_session.commit()

    a = AplicacionPublicada(nombre="Paint", farm_id=farm.id, origen="dt")
    db_session.add(a)
    db_session.commit()
    ent = AplicacionEntitlement(aplicacion_id=a.id, aplicacion_nombre="Paint",
                                 usuario_o_grupo="jperez", tipo_entitlement="Local",
                                 es_grupo=False, origen="dt")
    db_session.add(ent)

    rs = FarmRdsServer(farm_id=farm.id, nombre="RDSHOST-API-01", origen="dt")
    db_session.add(rs)
    db_session.commit()

    resp = admin_client.get("/api/granja/farms")
    assert resp.status_code == 200
    data = resp.get_json()
    farm_item = next(f for f in data["items"] if f["nombre"] == "Farm-API-01")
    assert len(farm_item["aplicaciones"]) == 1
    assert len(farm_item["rds_servers"]) == 1
    assert len(farm_item["autorizados"]) == 1
    assert farm_item["autorizados"][0]["usuario_o_grupo"] == "jperez"


def test_granja_aplicaciones_api_enriquece_con_directorio(app, db_session, admin_client):
    from web.db import AplicacionPublicada, AplicacionEntitlement, DirectorioUsuario

    u = DirectorioUsuario(username="jperez2", nombre_completo="Juan Pérez 2", activo_ad=True)
    db_session.add(u)

    a = AplicacionPublicada(nombre="Chrome", origen="dt")
    db_session.add(a)
    db_session.commit()
    ent = AplicacionEntitlement(aplicacion_id=a.id, aplicacion_nombre="Chrome",
                                 usuario_o_grupo="jperez2", tipo_entitlement="Local",
                                 es_grupo=False, origen="dt")
    db_session.add(ent)
    db_session.commit()

    resp = admin_client.get("/api/granja/aplicaciones")
    assert resp.status_code == 200
    data = resp.get_json()
    app_item = next(x for x in data["items"] if x["nombre"] == "Chrome")
    assert app_item["autorizaciones_locales"][0]["directorio"]["nombre_completo"] == "Juan Pérez 2"


def test_directorio_usuario_ficha_incluye_granja(app, db_session, admin_client):
    from web.db import DirectorioUsuario, AplicacionPublicada, AplicacionEntitlement

    u = DirectorioUsuario(username="jperez3", nombre_completo="Juan Pérez 3", activo_ad=True)
    db_session.add(u)
    db_session.commit()

    a = AplicacionPublicada(nombre="Teams", origen="dt")
    db_session.add(a)
    db_session.commit()
    ent = AplicacionEntitlement(aplicacion_id=a.id, aplicacion_nombre="Teams",
                                 usuario_o_grupo="jperez3", tipo_entitlement="Local",
                                 es_grupo=False, origen="dt")
    db_session.add(ent)
    db_session.commit()

    resp = admin_client.get(f"/api/directorio/usuarios/{u.id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "granja_aplicaciones" in data
    assert data["granja_aplicaciones"][0]["aplicacion_nombre"] == "Teams"
    assert "granja_vdi_vms" in data
