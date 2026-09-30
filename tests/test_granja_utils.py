"""Tests de los helpers derivados de Granja RDS: cruce con Directorio, rollup por Farm,
cruce por usuario con sus VDI-VMs existentes."""


def _setup_farm_app_entitlement(db_session, usuario="jperez", es_grupo=False, sufijo="01"):
    from web.db import Farm, AplicacionPublicada, AplicacionEntitlement

    farm = Farm(nombre=f"Farm-Utils-{sufijo}", origen="dt")
    db_session.add(farm)
    db_session.commit()

    app_db = AplicacionPublicada(nombre=f"Word-{sufijo}", farm_id=farm.id, origen="dt")
    db_session.add(app_db)
    db_session.commit()

    ent = AplicacionEntitlement(aplicacion_id=app_db.id, aplicacion_nombre=f"Word-{sufijo}",
                                 usuario_o_grupo=usuario, tipo_entitlement="Local",
                                 es_grupo=es_grupo, origen="dt")
    db_session.add(ent)
    db_session.commit()
    return farm, app_db, ent


def test_enriquecer_entitlements_con_directorio_matchea_usuario(app, db_session):
    from web.db import DirectorioUsuario
    from web.granja_utils import enriquecer_entitlements_con_directorio

    u = DirectorioUsuario(username="jperez", nombre_completo="Juan Pérez", activo_ad=True)
    db_session.add(u)
    db_session.commit()

    entitlements = [{"usuario_o_grupo": "jperez", "es_grupo": False}]
    out = enriquecer_entitlements_con_directorio(entitlements)

    assert out[0]["directorio"]["nombre_completo"] == "Juan Pérez"
    assert out[0]["directorio"]["activo_ad"] is True


def test_enriquecer_entitlements_con_directorio_no_encontrado(app, db_session):
    from web.granja_utils import enriquecer_entitlements_con_directorio

    entitlements = [{"usuario_o_grupo": "usuario_fantasma", "es_grupo": False}]
    out = enriquecer_entitlements_con_directorio(entitlements)

    assert out[0]["directorio"] is None


def test_enriquecer_entitlements_con_directorio_grupo_no_matchea(app, db_session):
    from web.granja_utils import enriquecer_entitlements_con_directorio

    entitlements = [{"usuario_o_grupo": "GG_Contabilidad", "es_grupo": True}]
    out = enriquecer_entitlements_con_directorio(entitlements)

    assert out[0]["directorio"] is None


def test_autorizados_por_farm_incluye_apps_y_pool_rds(app, db_session):
    from web.db import Pool, PoolEntitlement
    from web.granja_utils import autorizados_por_farm

    farm, app_db, ent = _setup_farm_app_entitlement(db_session, usuario="jperez", sufijo="02")

    pool = Pool(nombre="RDS_Desktop_utils", tipo="RDS", origen="dt", farm_id=farm.id)
    db_session.add(pool)
    db_session.commit()
    pool_ent = PoolEntitlement(pool_id=pool.id, pool_nombre=pool.nombre,
                                usuario_o_grupo="mlopez", tipo_entitlement="Local", es_grupo=False)
    db_session.add(pool_ent)
    db_session.commit()

    autorizados = autorizados_por_farm(farm)
    usuarios = {a["usuario_o_grupo"] for a in autorizados}
    assert usuarios == {"jperez", "mlopez"}


def test_autorizaciones_granja_para_usuario_junta_apps_y_vdi_vms(app, db_session):
    from web.db import DirectorioUsuario, Maquina, Servidor, Origen
    from web.granja_utils import autorizaciones_granja_para_usuario

    _, app_db, ent = _setup_farm_app_entitlement(db_session, usuario="mgarcia", sufijo="03")

    orig = Origen.query.filter_by(codigo="dt").first()
    if not orig:
        orig = Origen(codigo="dt")
        db_session.add(orig)
        db_session.commit()
    srv = Servidor(nombre="Horizon DT utils", host="wapp-utils900.local", tipo="horizon",
                    tipo_maquina="VDI", origen_id=orig.id)
    db_session.add(srv)
    db_session.commit()
    maq = Maquina(servidor_id=srv.id, nombre="VDI-MGARCIA-01", tipo="VDI",
                   origen_id=orig.id, usuario_asignado="mgarcia", activo=True)
    db_session.add(maq)
    db_session.commit()

    u = DirectorioUsuario(username="mgarcia", nombre_completo="María García", activo_ad=True)
    db_session.add(u)
    db_session.commit()

    resultado = autorizaciones_granja_para_usuario(u)

    assert len(resultado["aplicaciones"]) == 1
    assert resultado["aplicaciones"][0]["aplicacion_nombre"] == "Word-03"
    assert len(resultado["vdi_vms"]) == 1
    assert resultado["vdi_vms"][0]["nombre"] == "VDI-MGARCIA-01"
