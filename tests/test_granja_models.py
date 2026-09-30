"""Tests de los modelos de Granja RDS: creación, relaciones y to_dict()."""
import pytest


def test_farm_se_crea_y_to_dict(app, db_session):
    from web.db import Farm

    f = Farm(nombre="Farm-Models-01", display_name="Farm DT 01", tipo="AUTOMATED",
              horizon_farm_id="farm-123", origen="dt", enabled=True)
    db_session.add(f)
    db_session.commit()

    assert f.id is not None
    d = f.to_dict()
    assert d["nombre"] == "Farm-Models-01"
    assert d["tipo"] == "AUTOMATED"
    assert d["origen"] == "dt"


def test_aplicacion_publicada_enlaza_con_farm(app, db_session):
    from web.db import Farm, AplicacionPublicada

    f = Farm(nombre="Farm-Models-02", origen="dt")
    db_session.add(f)
    db_session.commit()

    a = AplicacionPublicada(nombre="Notepad++", farm_id=f.id, origen="dt")
    db_session.add(a)
    db_session.commit()

    assert a.farm.nombre == "Farm-Models-02"
    assert f.aplicaciones[0].nombre == "Notepad++"
    d = a.to_dict()
    assert d["farm_nombre"] == "Farm-Models-02"


def test_aplicacion_entitlement_to_dict(app, db_session):
    from web.db import AplicacionPublicada, AplicacionEntitlement

    a = AplicacionPublicada(nombre="Excel-Models", origen="dt")
    db_session.add(a)
    db_session.commit()

    e = AplicacionEntitlement(aplicacion_id=a.id, aplicacion_nombre="Excel-Models",
                               usuario_o_grupo="jperez", tipo_entitlement="Local",
                               es_grupo=False, origen="dt")
    db_session.add(e)
    db_session.commit()

    d = e.to_dict()
    assert d["usuario_o_grupo"] == "jperez"
    assert d["tipo_entitlement"] == "Local"
    assert d["es_grupo"] is False


def test_farm_rds_server_enlaza_con_maquina(app, db_session):
    from web.db import Farm, FarmRdsServer, Maquina, Servidor, Origen

    orig = Origen.query.filter_by(codigo="dt").first()
    if not orig:
        orig = Origen(codigo="dt")
        db_session.add(orig)
        db_session.commit()

    srv = Servidor(nombre="VCenter DT test", host="vcentertest.local", tipo="vcenter",
                    tipo_maquina="ambos", origen_id=orig.id)
    db_session.add(srv)
    db_session.commit()

    maq = Maquina(servidor_id=srv.id, nombre="RDSHOST01", tipo="VM", origen_id=orig.id)
    db_session.add(maq)
    db_session.commit()

    f = Farm(nombre="Farm-Models-03", origen="dt")
    db_session.add(f)
    db_session.commit()

    rs = FarmRdsServer(farm_id=f.id, nombre="RDSHOST01", maquina_id=maq.id, origen="dt")
    db_session.add(rs)
    db_session.commit()

    d = rs.to_dict()
    assert d["maquina"]["nombre"] == "RDSHOST01"
    assert f.rds_servers[0].nombre == "RDSHOST01"


def test_pool_farm_id_columna_existe(app, db_session):
    from web.db import Pool, Farm

    f = Farm(nombre="Farm-Models-04", origen="dt")
    db_session.add(f)
    db_session.commit()

    p = Pool(nombre="RDS_Desktop_test", tipo="RDS", origen="dt", farm_id=f.id)
    db_session.add(p)
    db_session.commit()

    assert p.farm_id == f.id
    assert p.to_dict()["farm_id"] == f.id
