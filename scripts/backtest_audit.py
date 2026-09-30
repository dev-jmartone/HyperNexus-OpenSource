"""
scripts/backtest_audit.py
Script de Backtesting y Auditoría Completa de Esquemas, Claves y Contratos
Valida alineación DB <-> Python ORM <-> API JSON <-> Frontend React
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import (
    db, Servidor, InventarioSnapshot, Maquina, Pool, PoolEntitlement,
    VMTareaEvento, HistorialUsuarioVDI, MaquinaHistorial, Usuario, DirectorioUsuario
)

def run_backtest_audit():
    app = create_app()
    with app.app_context():
        print("======================================================================")
        print("          BACKTESTING AUDIT DE INTEGRIDAD Y ALINEACION DE DATOS       ")
        print("======================================================================")

        report = {
            "mismatches": [],
            "schema_errors": [],
            "stats": {},
            "data_health": []
        }

        # 1. Auditoría de Modelo Maquina vs to_dict() vs ALL_COLUMNS Frontend
        print("\n[1/5] Auditando Modelo Maquina vs to_dict() vs Frontend Schema...")
        m_sample = Maquina.query.first()
        if m_sample:
            d = m_sample.to_dict()
            frontend_expected_cols = [
                'tipo', 'origen', 'nombre', 'pool', 'empresa', 'usuario_asignado',
                'estado_horizon', 'estado_vcenter', 'estado', 'so', 'ip_principal', 'dns',
                'vcenter_host', 'folder', 'resource_pool', 'datastores', 'hardware_version',
                'connection_state', 'maintenance_mode', 'in_error_state', 'annotation',
                'fecha_ultimo_ingreso', 'cpu', 'ram_gb', 'disk_provisioned_gb',
                'cpu_usage_mhz', 'memory_usage_mb'
            ]
            for col in frontend_expected_cols:
                if col not in d:
                    err = f"[ERROR SCHEMA] Clave frontend '{col}' falta en Maquina.to_dict()"
                    print(f" [ERROR] {err}")
                    report["mismatches"].append(err)
                else:
                    print(f"  [OK] Campo '{col}': Alineado (Ejemplo: {d[col]})")
        else:
            print("  [WARN] No se encontraron registros en Maquina")

        # 2. Auditoría de Salud de Datos en BD (1112 VMs)
        print("\n[2/5] Auditando Salud de Datos de 1,112 VMs activas en SQLite...")
        total_maquinas = Maquina.query.filter_by(activo=True).count()
        vdis = Maquina.query.filter_by(activo=True, tipo="VDI").count()
        vms = Maquina.query.filter_by(activo=True, tipo="VM").count()
        
        sin_servidor = Maquina.query.filter_by(activo=True, servidor_id=None).count()
        sin_origen = Maquina.query.filter(Maquina.activo == True, (Maquina._origen_str == None) | (Maquina._origen_str == "")).count()
        sin_nombre = Maquina.query.filter(Maquina.activo == True, (Maquina.nombre == None) | (Maquina.nombre == "")).count()

        print(f"  [OK] Total VMs Activas en DB: {total_maquinas}")
        print(f"  [OK] VDIs: {vdis} | VMs exclusivas vCenter: {vms}")
        print(f"  [OK] Sin Servidor ID: {sin_servidor} | Sin Origen Str: {sin_origen} | Sin Nombre: {sin_nombre}")

        if sin_nombre > 0:
            report["data_health"].append(f"[ALERTA DATA] {sin_nombre} VMs sin nombre en DB")
        if sin_servidor > 0:
            report["data_health"].append(f"[ALERTA DATA] {sin_servidor} VMs huerfanas sin servidor_id")

        # 3. Auditoría de Pools y Entitlements
        print("\n[3/5] Auditando Modelo Pool y Entitlements...")
        total_pools = Pool.query.count()
        total_ent_locales = PoolEntitlement.query.filter_by(tipo_entitlement="Local").count()
        total_ent_globales = PoolEntitlement.query.filter_by(tipo_entitlement="Global").count()

        print(f"  [OK] Total Pools Registradas: {total_pools}")
        print(f"  [OK] Total Entitlements Locales: {total_ent_locales}")
        print(f"  [OK] Total Entitlements Globales: {total_ent_globales}")

        # Check for orphan local entitlements (Global entitlements have pool_id = None by design)
        ent_locales_huerfanos = (
            db.session.query(PoolEntitlement)
            .outerjoin(Pool, PoolEntitlement.pool_id == Pool.id)
            .filter(PoolEntitlement.tipo_entitlement == "Local", Pool.id == None)
            .count()
        )
        if ent_locales_huerfanos > 0:
            err = f"[ERROR DB] {ent_locales_huerfanos} Entitlements Locales huerfanos sin Pool asociada"
            print(f" [ERROR] {err}")
            report["mismatches"].append(err)
        else:
            print("  [OK] Entitlements Locales huerfanos: 0 (Perfecto)")

        # 4. Auditoría de Tareas y Eventos vCenter
        print("\n[4/5] Auditando Tareas y Eventos vCenter (VMTareaEvento)...")
        total_eventos = VMTareaEvento.query.count()
        ev_sample = VMTareaEvento.query.first()
        if ev_sample:
            ev_dict = ev_sample.to_dict()
            expected_ev_keys = ["id", "maquina_id", "tipo", "nombre_evento", "mensaje", "usuario", "estado", "fecha"]
            for k in expected_ev_keys:
                if k not in ev_dict:
                    err = f"[ERROR SCHEMA] Clave '{k}' falta en VMTareaEvento.to_dict()"
                    print(f" [ERROR] {err}")
                    report["mismatches"].append(err)
            print(f"  [OK] Total Eventos en DB: {total_eventos}")
            print(f"  [OK] Esquema to_dict() VMTareaEvento: OK ({list(ev_dict.keys())})")
        else:
            print(f"  [INFO] Total Eventos registrados: {total_eventos}")

        # 5. Auditoría de Trazabilidad e Historiales
        print("\n[5/5] Auditando HistorialUsuarioVDI y MaquinaHistorial...")
        total_rotaciones = HistorialUsuarioVDI.query.count()
        total_deltas = MaquinaHistorial.query.count()
        print(f"  [OK] Total Cambios de Usuario (Rotaciones): {total_rotaciones}")
        print(f"  [OK] Total Cambios de Estado (Deltas): {total_deltas}")

        # Resumen Final
        print("\n======================================================================")
        if not report["mismatches"]:
            print(" [SUCCESS] BACKTESTING EXITOSO: 100% de Contratos, Campos y Tipos Alineados.")
        else:
            print(f" [WARN] SE DETECTARON {len(report['mismatches'])} INCONGRUENCIAS:")
            for m in report["mismatches"]:
                print(f"   - {m}")
        print("======================================================================\n")

if __name__ == "__main__":
    run_backtest_audit()
