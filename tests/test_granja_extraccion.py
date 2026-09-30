"""Tests de persistencia de Granja RDS: upsert, desactivación y enlace Pool<->Farm."""


def _servidor_horizon_dt(db_session):
    from web.db import Servidor, Origen
    orig = Origen.query.filter_by(codigo="dt").first()
    if not orig:
        orig = Origen(codigo="dt")
        db_session.add(orig)
        db_session.commit()
    srv = Servidor(nombre="Horizon DT test", host="wapp-test900.local", tipo="horizon",
                    tipo_maquina="VDI", origen_id=orig.id)
    db_session.add(srv)
    db_session.commit()
    srv.origen = "dt"
    return srv


def test_guardar_granja_horizon_crea_farm_app_y_entitlement(app, db_session):
    from web.routes.inventario import _guardar_granja_horizon
    from web.db import Farm, AplicacionPublicada, AplicacionEntitlement

    srv = _servidor_horizon_dt(db_session)
    datos_raw = {
        "farms": [{"Name": "Farm-DT-01", "DisplayName": "Farm DT 01", "Type": "AUTOMATED",
                    "Id": "farm-1", "Enabled": True}],
        "application_pools": [{"Name": "Excel", "DisplayName": "Microsoft Excel",
                                 "FarmName": "Farm-DT-01", "Enabled": True}],
        "app_entitlements_locales": [{"AplicacionNombre": "Excel", "UserOrGroup": "jperez", "IsGroup": False}],
        "app_entitlements_globales": [],
        "rds_servers": [{"FarmName": "Farm-DT-01", "Name": "RDSHOST01", "Estado": "OK", "SesionesActivas": 2}],
        "pools": [],
    }

    _guardar_granja_horizon(srv, datos_raw)

    farm = Farm.query.filter_by(nombre="Farm-DT-01").first()
    assert farm is not None
    assert farm.horizon_farm_id == "farm-1"
    assert farm.activo is True

    app_db = AplicacionPublicada.query.filter_by(nombre="Excel").first()
    assert app_db is not None
    assert app_db.farm_id == farm.id

    ent = AplicacionEntitlement.query.filter_by(aplicacion_nombre="Excel", usuario_o_grupo="jperez").first()
    assert ent is not None
    assert ent.tipo_entitlement == "Local"
    assert ent.aplicacion_id == app_db.id


def test_guardar_granja_horizon_desactiva_no_vistos(app, db_session):
    from web.routes.inventario import _guardar_granja_horizon
    from web.db import Farm

    srv = _servidor_horizon_dt(db_session)
    _guardar_granja_horizon(srv, {
        "farms": [{"Name": "Farm-DT-02", "Id": "farm-2"}],
        "application_pools": [], "app_entitlements_locales": [], "app_entitlements_globales": [],
        "rds_servers": [], "pools": [],
    })
    assert Farm.query.filter_by(nombre="Farm-DT-02").first().activo is True

    # Segunda corrida sin Farm-DT-02 -- debe desactivarse, no borrarse
    _guardar_granja_horizon(srv, {
        "farms": [], "application_pools": [], "app_entitlements_locales": [],
        "app_entitlements_globales": [], "rds_servers": [], "pools": [],
    })
    assert Farm.query.filter_by(nombre="Farm-DT-02").first().activo is False


def test_guardar_granja_horizon_enlaza_pool_rds_con_farm(app, db_session):
    from web.routes.inventario import _guardar_granja_horizon
    from web.db import Farm, Pool

    srv = _servidor_horizon_dt(db_session)
    pool = Pool(nombre="RDS_Desktop", tipo="RDS", origen="dt")
    db_session.add(pool)
    db_session.commit()

    _guardar_granja_horizon(srv, {
        "farms": [{"Name": "Farm-DT-03", "Id": "farm-3"}],
        "application_pools": [], "app_entitlements_locales": [], "app_entitlements_globales": [],
        "rds_servers": [],
        "pools": [{"Name": "RDS_Desktop", "FarmId": "farm-3"}],
    })

    farm = Farm.query.filter_by(nombre="Farm-DT-03").first()
    pool_reloaded = Pool.query.filter_by(nombre="RDS_Desktop").first()
    assert pool_reloaded.farm_id == farm.id


def test_vincular_farm_rds_server_matchea_por_nombre(app, db_session):
    from web.routes.inventario import _vincular_farm_rds_server
    from web.db import Farm, FarmRdsServer, Maquina, Servidor, Origen

    orig = Origen.query.filter_by(codigo="dt").first()
    if not orig:
        orig = Origen(codigo="dt")
        db_session.add(orig)
        db_session.commit()

    srv = Servidor(nombre="VCenter DT test2", host="vcentertest2.local", tipo="vcenter",
                    tipo_maquina="ambos", origen_id=orig.id)
    db_session.add(srv)
    db_session.commit()

    maq = Maquina(servidor_id=srv.id, nombre="RDSHOST02", tipo="VM", origen_id=orig.id)
    db_session.add(maq)
    db_session.commit()

    farm = Farm(nombre="Farm-DT-05", origen="dt")
    db_session.add(farm)
    db_session.commit()

    rs = FarmRdsServer(farm_id=farm.id, nombre="RDSHOST02", origen="dt")
    db_session.add(rs)
    db_session.commit()

    _vincular_farm_rds_server("dt", "RDSHOST02", maq.id)
    db_session.commit()

    rs_reloaded = FarmRdsServer.query.filter_by(nombre="RDSHOST02").first()
    assert rs_reloaded.maquina_id == maq.id


def test_vincular_farm_rds_server_sin_match_no_falla(app, db_session):
    from web.routes.inventario import _vincular_farm_rds_server
    # Nombre que no existe en FarmRdsServer -- no debe lanzar excepción.
    _vincular_farm_rds_server("dt", "NO-EXISTE-XYZ", 999)
