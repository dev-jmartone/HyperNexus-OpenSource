"""
scripts/migrate_catalogs.py
Script de migración de datos y población de catálogos (origenes, empresas, pools, datastores).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import db, Origen, Empresa, Pool, Maquina, Servidor, MaquinaHistorial, seed_catalogos

def run_migration():
    app = create_app()
    with app.app_context():
        print("=== Iniciando migración y verificación de datos ===")
        
        # 1. Asegurar catálogos base
        seed_catalogos()
        
        # 2. Poblar empresas desde Maquina
        count_emp_before = Empresa.query.count()
        distinct_empresas = db.session.query(Maquina._empresa_str).filter(Maquina._empresa_str.isnot(None), Maquina._empresa_str != "").distinct().all()
        for row in distinct_empresas:
            nombre = row[0].strip()
            if nombre and not Empresa.query.filter_by(nombre=nombre).first():
                db.session.add(Empresa(nombre=nombre))
        db.session.commit()
        count_emp_after = Empresa.query.count()
        print(f"Catálogo Empresas: {count_emp_before} -> {count_emp_after} agregadas")

        # 3. Poblar pools desde Maquina
        count_pool_before = Pool.query.count()
        distinct_pools = db.session.query(Maquina._pool_str).filter(Maquina._pool_str.isnot(None), Maquina._pool_str != "").distinct().all()
        for row in distinct_pools:
            nombre = row[0].strip()
            if nombre and not Pool.query.filter_by(nombre=nombre).first():
                db.session.add(Pool(nombre=nombre))
        db.session.commit()
        count_pool_after = Pool.query.count()
        print(f"Catálogo Pools: {count_pool_before} -> {count_pool_after} agregadas")

        # 4. Vincular FKs en Maquina
        maquinas = Maquina.query.all()
        linked_emp = linked_pool = linked_origen = 0
        for m in maquinas:
            if m._empresa_str:
                emp = Empresa.query.filter_by(nombre=m._empresa_str.strip()).first()
                if emp:
                    m.empresa_id = emp.id
                    linked_emp += 1
            if m._pool_str:
                p = Pool.query.filter_by(nombre=m._pool_str.strip()).first()
                if p:
                    m.pool_id = p.id
                    linked_pool += 1
            if m._origen_str:
                o = Origen.query.filter_by(codigo=m._origen_str.strip().lower()).first()
                if o:
                    m.origen_id = o.id
                    linked_origen += 1

        # 5. Vincular FKs en Servidor
        for s in Servidor.query.all():
            if s._origen_str:
                o = Origen.query.filter_by(codigo=s._origen_str.strip().lower()).first()
                if o:
                    s.origen_id = o.id

        db.session.commit()
        print(f"Vínculos FK Maquina actualizados: Empresa={linked_emp}, Pool={linked_pool}, Origen={linked_origen}")
        print("=== Migración de datos completada exitosamente ===")

if __name__ == "__main__":
    run_migration()
