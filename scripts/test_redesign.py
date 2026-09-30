"""
scripts/test_redesign.py
Pruebas integrales de validación del rediseño del esquema de base de datos.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import (db, Usuario, AuditoriaLog, Servidor, InventarioSnapshot, Maquina,
                    MaquinaHistorial, Origen, Empresa, Pool, TareaExtraccion, Alerta, Configuracion)

def run_tests():
    app = create_app()
    with app.app_context():
        print("--- 1. Verificar Sembrado Inicial y Catálogos ---")
        admin = Usuario.query.filter_by(username="admin").first()
        assert admin is not None, "Usuario admin debe existir"
        assert Origen.query.count() >= 4, "Deben existirlos 4 orígenes por defecto"
        assert Configuracion.query.count() >= 2, "Debe existir configuración por defecto"
        print("OK: Admin y catálogos iniciales verificados.")

        print("--- 2. Crear Servidor y Vinculación con Origen ---")
        dt_origen = Origen.query.filter_by(codigo="dt").first()
        srv = Servidor(
            nombre="vCenter Test Core",
            host="vc-test.empresa.com",
            tipo="vcenter",
            tipo_maquina="VM",
            origen_id=dt_origen.id,
            dominio="CORP",
            activo=True
        )
        db.session.add(srv)
        db.session.commit()
        assert srv.id is not None
        assert srv.origen == "dt"
        print(f"OK: Servidor ID {srv.id} creado con origen '{srv.origen}'.")

        print("--- 3. Extracción 1: Crear Snapshot 1 y Maquinas ---")
        snap1 = InventarioSnapshot(servidor_id=srv.id, total_vms=2, estado="completado")
        db.session.add(snap1)
        db.session.flush()

        from web.routes.inventario import _save_or_update_maquina
        m1, is_new1 = _save_or_update_maquina(
            servidor_id=srv.id, snapshot_id=snap1.id, nombre_vm="VDI-WIN11-001",
            tipo="VDI", origen_str="dt", pool_str="POOL-DESKTOPS", empresa_str="Acme Corp",
            usuario_asignado="jperez", estado_horizon="CONNECTED", estado_vcenter="PoweredOn",
            manager="Carlos Gomez", agent_version="8.12", so="Windows 11", cpu=4, ram_gb=16.0,
            disk_gb=100.0, dns="vdi-001.empresa.com", ip="10.0.0.15", vcenter_host="esx-01", correcciones={}
        )
        assert is_new1 is True
        assert m1.id is not None
        print(f"OK: Maquina {m1.nombre} (ID: {m1.id}) creada en snapshot 1.")

        print("--- 4. Extracción 2: UPDATE In-Place + Registro de Delta en MaquinaHistorial ---")
        snap2 = InventarioSnapshot(servidor_id=srv.id, total_vms=2, estado="completado")
        db.session.add(snap2)
        db.session.flush()

        m1_updated, is_new2 = _save_or_update_maquina(
            servidor_id=srv.id, snapshot_id=snap2.id, nombre_vm="VDI-WIN11-001",
            tipo="VDI", origen_str="dt", pool_str="POOL-DESKTOPS", empresa_str="Acme Corp",
            usuario_asignado="mrodriguez", # Cambio de usuario!
            estado_horizon="CONNECTED", estado_vcenter="PoweredOn",
            manager="Carlos Gomez", agent_version="8.12", so="Windows 11", cpu=8, # Cambio CPU!
            ram_gb=16.0, disk_gb=100.0, dns="vdi-001.empresa.com", ip="10.0.0.15", vcenter_host="esx-01", correcciones={}
        )
        assert is_new2 is False
        assert Maquina.query.filter_by(servidor_id=srv.id).count() == 1, "Debe haber solo 1 fila física en Maquina para este servidor"
        
        historiales = MaquinaHistorial.query.filter_by(maquina_id=m1.id).all()
        assert len(historiales) == 2, f"Debe haber 2 deltas registrados (usuario y cpu), se encontraron {len(historiales)}"
        print(f"OK: Re-extracción actualizada en mismo registro (ID: {m1.id}) y registrados {len(historiales)} deltas en MaquinaHistorial.")

        print("--- 5. Probar Alertas y Tareas ---")
        alerta = Alerta(tipo="desconexion", maquina_id=m1.id, mensaje="VDI desconectada inesperadamente")
        db.session.add(alerta)
        import time
        tarea = TareaExtraccion(job_id=f"job_test_{int(time.time()*1000)}", estado="completado", duracion_segundos=12.5)
        db.session.add(tarea)
        db.session.commit()
        assert alerta.id is not None and tarea.id is not None
        print("OK: Tablas de Alerta y Tareas de Extracción funcionando.")

        print("\n*** TODAS LAS PRUEBAS DEL REDISENO PASARON CORRECTAMENTE. ***")

if __name__ == "__main__":
    run_tests()
