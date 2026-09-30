"""
seed_db.py
Script de inicialización y generación de datos simulados realistas para demostraciones y portfolio.
Crea la base de datos SQLite 'data/inventario.db' completamente poblada con:
- Usuarios de acceso (admin, demo, auditor)
- Servidores virtuales (Horizon Connection Servers, vSphere vCenters, App Volumes Manager)
- Pools de escritorios (Dedicated, Floating, Instant Clone, RDS)
- Entitlements y Granja de aplicaciones publicadas
- Directorio de usuarios de Active Directory (múltiples empresas y departamentos)
- 70+ Máquinas virtuales (VDIs conectadas, disponibles, RPAs, Golden Masters, copias y huérfanas)
- Métricas de telemetría de hardware, datastores y alertas de capacidad de disco
- Historial de cambios, eventos de auditoría y volúmenes App Volumes (Writables)
"""

import os
import sys
import json
import random
from datetime import datetime, timedelta

# Asegurar que el directorio raíz del proyecto esté en sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Asegurar salida UTF-8 en consolas Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configurar variables de entorno mínimas para inicialización si no existen
os.environ.setdefault("SECRET_KEY", "demo-secret-key-vdi-hub-2026-portfolio")
os.environ.setdefault("FERNET_KEY", "bXlzdGVyaW91c2tleWZvcmRlbW9wdXJwb3NlczEyMzQ1Njc=")
os.environ.setdefault("DEMO_MODE", "1")

from web.app import create_app
from web.db import (
    db, Usuario, Origen, Configuracion, Empresa, Servidor, Pool,
    PoolEntitlement, Farm, FarmRdsServer, AplicacionPublicada,
    DirectorioUsuario, Maquina, MaquinaUsuarioDir,
    Datastore, HostEsxi, InfraEvento, VMTareaEvento, MaquinaHistorial,
    AppVolumesAplicacion, AppVolumesPaquete, AppVolumesAsignacion,
    AppVolumesWritable, AuditoriaLog, InventarioSnapshot
)

def run_seed():
    print("================================================================")
    print("[*] VDI Inventory Hub - Sembrador de Datos Demo / Portfolio")
    print("================================================================")

    db_path = os.path.join(BASE_DIR, "data", "inventario.db")
    if os.path.exists(db_path):
        print(f"[*] Base de datos existente detectada en: {db_path}")
        print("[*] Recreando base de datos limpia para demostración...")
        try:
            os.remove(db_path)
        except Exception as e:
            print(f"[!] Aviso al eliminar archivo anterior: {e}")

    app = create_app()

    with app.app_context():
        print("[1/9] Creando tablas e índices...")
        db.create_all()

        print("[2/9] Creando usuarios del sistema...")
        # 1. Usuarios del sistema
        admin = Usuario(
            username="admin",
            nombre_completo="System Administrator",
            email="admin@corp.local",
            rol="admin",
            activo=True,
            must_change_password=False,
        )
        admin.set_password("Admin123!")

        demo = Usuario(
            username="demo",
            nombre_completo="Demo Operator",
            email="demo@corp.local",
            rol="operador",
            activo=True,
            must_change_password=False,
        )
        demo.set_password("Demo123!")

        auditor = Usuario(
            username="auditor",
            nombre_completo="Compliance Auditor",
            email="auditor@corp.local",
            rol="visor",
            activo=True,
            must_change_password=False,
        )
        auditor.set_password("Auditor123!")

        db.session.add_all([admin, demo, auditor])

        print("[3/9] Obteniendo orígenes y catálogos corporativos...")
        # 2. Orígenes (ya sembrados por create_app/init_db)
        origenes = {o.codigo: o for o in Origen.query.all()}

        # 3. Configuraciones
        if not Configuracion.query.filter_by(clave="alerta_disco_umbral").first():
            db.session.add(Configuracion(clave="alerta_disco_umbral", valor="90", descripcion="Umbral porcentual de alerta de disco crítico"))

        # 4. Empresas clientes / unidades de negocio
        empresas = {
            "acme": Empresa(nombre="Acme Corp"),
            "globaltech": Empresa(nombre="GlobalTech Solutions"),
            "cloudops": Empresa(nombre="CloudOps Consulting"),
            "finsvc": Empresa(nombre="FinServices Group"),
        }
        for emp in empresas.values():
            if not Empresa.query.filter_by(nombre=emp.nombre).first():
                db.session.add(emp)

        db.session.commit()

        print("[4/9] Registrando servidores de infraestructura...")
        # 5. Servidores
        srv_horizon_dt = Servidor(
            nombre="Horizon CS 01 (Core VDI)",
            host="cs-horizon-01.corp.local",
            tipo="horizon",
            tipo_maquina="VM",
            origen_id=origenes["dt"].id,
            dominio="CORP",
            activo=True,
            ultimo_chequeo=datetime.utcnow() - timedelta(minutes=15)
        )
        srv_horizon_mz = Servidor(
            nombre="Horizon CS 02 (Secure MZ)",
            host="cs-horizon-02.corp.local",
            tipo="horizon",
            tipo_maquina="VM",
            origen_id=origenes["mz"].id,
            dominio="CORP",
            activo=True,
            ultimo_chequeo=datetime.utcnow() - timedelta(minutes=22)
        )
        srv_vcenter_dt = Servidor(
            nombre="vCenter Cluster DT",
            host="vc-cluster-01.corp.local",
            tipo="vcenter",
            tipo_maquina="VM",
            origen_id=origenes["dt"].id,
            dominio="CORP",
            activo=True,
            ultimo_chequeo=datetime.utcnow() - timedelta(minutes=14)
        )
        srv_vcenter_mz = Servidor(
            nombre="vCenter Cluster MZ",
            host="vc-cluster-02.corp.local",
            tipo="vcenter",
            tipo_maquina="VM",
            origen_id=origenes["mz"].id,
            dominio="CORP",
            activo=True,
            ultimo_chequeo=datetime.utcnow() - timedelta(minutes=20)
        )
        srv_appvolumes = Servidor(
            nombre="App Volumes Manager 01",
            host="appvol-mgr-01.corp.local",
            tipo="appvolumes",
            tipo_maquina="VM",
            origen_id=origenes["core"].id,
            dominio="CORP",
            activo=True,
            ultimo_chequeo=datetime.utcnow() - timedelta(minutes=30)
        )
        db.session.add_all([srv_horizon_dt, srv_horizon_mz, srv_vcenter_dt, srv_vcenter_mz, srv_appvolumes])
        db.session.commit()

        # Snapshots
        snap_dt = InventarioSnapshot(
            servidor_id=srv_horizon_dt.id,
            total_vms=48,
            total_vdi=42,
            total_vm=6,
            estado="completado",
            iniciado_en=datetime.utcnow() - timedelta(minutes=16),
            finalizado_en=datetime.utcnow() - timedelta(minutes=15),
            duracion_segundos=45.2
        )
        snap_mz = InventarioSnapshot(
            servidor_id=srv_horizon_mz.id,
            total_vms=26,
            total_vdi=22,
            total_vm=4,
            estado="completado",
            iniciado_en=datetime.utcnow() - timedelta(minutes=23),
            finalizado_en=datetime.utcnow() - timedelta(minutes=22),
            duracion_segundos=32.8
        )
        db.session.add_all([snap_dt, snap_mz])
        db.session.commit()

        print("[5/9] Creando pools de escritorios, autorizaciones y granjas RDS...")
        # 6. Pools
        pools = {
            "eng": Pool(
                nombre="Engineering-Win11",
                display_name="Engineering Workstations Windows 11",
                tipo="Automated",
                user_assignment="Dedicated",
                enabled=True,
                activo=True,
                master_vm_actual="PC-MST-WIN11-ENG",
                snapshot_actual="v3.2_STABLE_PROD",
                master_moref="vm-1024",
                imagen_actualizada_en=datetime.utcnow() - timedelta(days=5),
                origen="dt"
            ),
            "fin": Pool(
                nombre="Finance-Secure-Desktop",
                display_name="Finance Secure Desktops",
                tipo="Automated",
                user_assignment="Floating",
                enabled=True,
                activo=True,
                master_vm_actual="PC-MST-WIN11-FIN",
                snapshot_actual="v2.1_FIN_COMPLIANT",
                master_moref="vm-1025",
                imagen_actualizada_en=datetime.utcnow() - timedelta(days=12),
                origen="dt"
            ),
            "ops": Pool(
                nombre="Operations-Shift-Workstation",
                display_name="Operations Shift Workstations",
                tipo="Automated",
                user_assignment="Floating",
                enabled=True,
                activo=True,
                master_vm_actual="PC-MST-WIN10-LTS",
                snapshot_actual="v1.0_BASE",
                master_moref="vm-1026",
                imagen_actualizada_en=datetime.utcnow() - timedelta(days=28),
                origen="dt"
            ),
            "devops": Pool(
                nombre="DevOps-Heavy-Dev",
                display_name="DevOps Heavy Compute Desktops",
                tipo="Manual",
                user_assignment="Dedicated",
                enabled=True,
                activo=True,
                master_vm_actual="PC-MST-WIN11-ENG",
                snapshot_actual="v3.2_STABLE_PROD",
                master_moref="vm-1024",
                imagen_actualizada_en=datetime.utcnow() - timedelta(days=5),
                origen="dt"
            ),
            "exec": Pool(
                nombre="Executive-Remote-Suite",
                display_name="Executive Remote Suite",
                tipo="Automated",
                user_assignment="Dedicated",
                enabled=True,
                activo=True,
                master_vm_actual="PC-MST-WIN11-EXEC",
                snapshot_actual="v4.0_EXEC_SECURE",
                master_moref="vm-2048",
                imagen_actualizada_en=datetime.utcnow() - timedelta(days=3),
                origen="mz"
            ),
            "rds": Pool(
                nombre="RDS-Shared-Apps",
                display_name="Shared Hosted RDS Applications",
                tipo="RDS",
                user_assignment="Floating",
                enabled=True,
                activo=True,
                origen="dt"
            ),
            "estatica": Pool(
                nombre="Estática",
                display_name="Servidores y VMs Estáticas",
                tipo="Manual",
                user_assignment="Dedicated",
                enabled=True,
                activo=True,
                origen="dt"
            ),
        }
        for p in pools.values():
            db.session.add(p)
        db.session.commit()

        # Entitlements
        entitlements = [
            PoolEntitlement(pool_id=pools["eng"].id, pool_nombre=pools["eng"].nombre, usuario_o_grupo="CORP\\GRP-Engineering-Staff", tipo_entitlement="Local", es_grupo=True, servidor_id=srv_horizon_dt.id, origen="dt"),
            PoolEntitlement(pool_id=pools["fin"].id, pool_nombre=pools["fin"].nombre, usuario_o_grupo="CORP\\GRP-Financial-Analysts", tipo_entitlement="Local", es_grupo=True, servidor_id=srv_horizon_dt.id, origen="dt"),
            PoolEntitlement(pool_id=pools["ops"].id, pool_nombre=pools["ops"].nombre, usuario_o_grupo="CORP\\GRP-Operations-Floor", tipo_entitlement="Local", es_grupo=True, servidor_id=srv_horizon_dt.id, origen="dt"),
            PoolEntitlement(pool_id=pools["devops"].id, pool_nombre=pools["devops"].nombre, usuario_o_grupo="CORP\\GRP-DevOps-Admins", tipo_entitlement="Local", es_grupo=True, servidor_id=srv_horizon_dt.id, origen="dt"),
            PoolEntitlement(pool_id=pools["exec"].id, pool_nombre=pools["exec"].nombre, usuario_o_grupo="CORP\\GRP-Executive-Board", tipo_entitlement="Local", es_grupo=True, servidor_id=srv_horizon_mz.id, origen="mz"),
        ]
        db.session.add_all(entitlements)

        # Farm RDS y aplicaciones publicadas
        farm = Farm(
            nombre="RDS-Farm-Engineering",
            display_name="Farm Servidores RDS 2022",
            tipo="AUTOMATED",
            horizon_farm_id="farm-9901",
            rds_server_max_sessions=40,
            enabled=True,
            activo=True,
            origen="dt",
            servidor_id=srv_horizon_dt.id
        )
        db.session.add(farm)
        db.session.commit()

        pools["rds"].farm_id = farm.id

        rds_servers = [
            FarmRdsServer(farm_id=farm.id, nombre="SRV-RDS-PROD-01", estado="OK", sesiones_activas=14, enabled=True, activo=True, origen="dt", servidor_id=srv_horizon_dt.id),
            FarmRdsServer(farm_id=farm.id, nombre="SRV-RDS-PROD-02", estado="OK", sesiones_activas=18, enabled=True, activo=True, origen="dt", servidor_id=srv_horizon_dt.id),
        ]
        db.session.add_all(rds_servers)

        app_pub = [
            AplicacionPublicada(nombre="SAP ERP Enterprise Client", display_name="SAP ERP Client", path_ejecutable="C:\\SAP\\FrontEnd\\SAPgui\\saplogon.exe", farm_id=farm.id, enabled=True, activo=True, origen="dt", servidor_id=srv_horizon_dt.id),
            AplicacionPublicada(nombre="PowerBI Desktop Analytics", display_name="PowerBI Desktop", path_ejecutable="C:\\Program Files\\PowerBI\\bin\\PBIDesktop.exe", farm_id=farm.id, enabled=True, activo=True, origen="dt", servidor_id=srv_horizon_dt.id),
            AplicacionPublicada(nombre="Visual Studio Code Remote", display_name="VS Code", path_ejecutable="C:\\Program Files\\VSCode\\Code.exe", farm_id=farm.id, enabled=True, activo=True, origen="dt", servidor_id=srv_horizon_dt.id),
        ]
        db.session.add_all(app_pub)

        # Datastores y Hosts
        datastores = [
            Datastore(servidor_id=srv_vcenter_dt.id, nombre="vsanDatastore-DT-Cluster01", capacidad_gb=45000.0, espacio_libre_gb=14200.0, tipo="vsan", activo=True),
            Datastore(servidor_id=srv_vcenter_dt.id, nombre="NFS-Templates-ISO-01", capacidad_gb=12000.0, espacio_libre_gb=4800.0, tipo="nfs", activo=True),
            Datastore(servidor_id=srv_vcenter_dt.id, nombre="NVMe-FastTier-Pool01", capacidad_gb=8000.0, espacio_libre_gb=620.0, tipo="vmfs", activo=True), # >90% crítico!
            Datastore(servidor_id=srv_vcenter_mz.id, nombre="vsanDatastore-MZ-Cluster01", capacidad_gb=28000.0, espacio_libre_gb=9600.0, tipo="vsan", activo=True),
        ]
        hosts = [
            HostEsxi(servidor_id=srv_vcenter_dt.id, nombre="esx-dt-01.corp.local", connection_state="CONNECTED", power_state="poweredOn", activo=True),
            HostEsxi(servidor_id=srv_vcenter_dt.id, nombre="esx-dt-02.corp.local", connection_state="CONNECTED", power_state="poweredOn", activo=True),
            HostEsxi(servidor_id=srv_vcenter_dt.id, nombre="esx-dt-03.corp.local", connection_state="CONNECTED", power_state="poweredOn", activo=True),
            HostEsxi(servidor_id=srv_vcenter_mz.id, nombre="esx-mz-01.corp.local", connection_state="CONNECTED", power_state="poweredOn", activo=True),
            HostEsxi(servidor_id=srv_vcenter_mz.id, nombre="esx-mz-02.corp.local", connection_state="CONNECTED", power_state="poweredOn", activo=True),
        ]
        db.session.add_all(datastores + hosts)
        db.session.commit()

        print("[6/9] Poblando Directorio Activo (Active Directory)...")
        # 7. Directorio de Usuarios
        user_specs = [
            ("arivera", "Alex Rivera", "Engineering", "Acme Corp", "arivera@acme.com", "+1-555-0101", False),
            ("evance", "Elena Vance", "Engineering", "Acme Corp", "evance@acme.com", "+1-555-0102", False),
            ("mholloway", "Marcus Holloway", "Cybersecurity", "Acme Corp", "mholloway@acme.com", "+1-555-0103", False),
            ("sconnor", "Sarah Connor", "Operations", "Acme Corp", "sconnor@acme.com", "+1-555-0104", False),
            ("dmiller", "David Miller", "Finance", "FinServices Group", "dmiller@finservices.org", "+1-555-0105", False),
            ("rchen", "Robert Chen", "Finance", "FinServices Group", "rchen@finservices.org", "+1-555-0106", False),
            ("ewatson", "Emily Watson", "Financial Analysis", "FinServices Group", "ewatson@finservices.org", "+1-555-0107", False),
            ("mchang", "Michael Chang", "DevOps & Cloud", "CloudOps Consulting", "mchang@cloudops.io", "+1-555-0108", True),
            ("cdiaz", "Carlos Diaz", "DevOps & Cloud", "CloudOps Consulting", "cdiaz@cloudops.io", "+1-555-0109", True),
            ("srossi", "Sofia Rossi", "Cloud Infrastructure", "CloudOps Consulting", "srossi@cloudops.io", "+1-555-0110", True),
            ("lvance", "Lucas Vance", "IT Architecture", "GlobalTech Solutions", "lvance@globaltech.com", "+1-555-0111", False),
            ("jalba", "Jessica Alba", "Customer Support", "GlobalTech Solutions", "jalba@globaltech.com", "+1-555-0112", False),
            ("jwilson", "James Wilson", "Operations Support", "GlobalTech Solutions", "jwilson@globaltech.com", "+1-555-0113", False),
            ("fcastle", "Frank Castle", "Corporate Security", "Acme Corp", "fcastle@acme.com", "+1-555-0114", False),
            ("mgarcia", "Maria Garcia", "Human Resources", "Acme Corp", "mgarcia@acme.com", "+1-555-0115", False),
            ("bwayne", "Bruce Wayne", "Executive Board", "Acme Corp", "bwayne@acme.com", "+1-555-0116", False),
            ("dprince", "Diana Prince", "Executive Board", "Acme Corp", "dprince@acme.com", "+1-555-0117", False),
            ("tanderson", "Thomas Anderson", "Core Architecture", "Acme Corp", "tanderson@acme.com", "+1-555-0118", False),
            ("tortiz", "Trinity Ortiz", "Site Reliability", "CloudOps Consulting", "tortiz@cloudops.io", "+1-555-0119", True),
            ("mreed", "Morpheus Reed", "DevOps Lead", "CloudOps Consulting", "mreed@cloudops.io", "+1-555-0120", True),
            ("lskywalker", "Luke Skywalker", "Flight Operations", "GlobalTech Solutions", "lskywalker@globaltech.com", "+1-555-0121", False),
            ("lorgana", "Leia Organa", "General Management", "Acme Corp", "lorgana@acme.com", "+1-555-0122", False),
            ("hsolo", "Han Solo", "Logistics Operations", "GlobalTech Solutions", "hsolo@globaltech.com", "+1-555-0123", False),
            ("adent", "Arthur Dent", "Risk Management", "FinServices Group", "adent@finservices.org", "+1-555-0124", False),
            ("fprefect", "Ford Prefect", "Auditing", "FinServices Group", "fprefect@finservices.org", "+1-555-0125", False),
            ("ckent", "Clark Kent", "Communications", "Acme Corp", "ckent@acme.com", "+1-555-0126", False),
            ("ballen", "Barry Allen", "Express Dispatch", "GlobalTech Solutions", "ballen@globaltech.com", "+1-555-0127", False),
            ("hpotter", "Harry Potter", "Apprentice Engineering", "Acme Corp", "hpotter@acme.com", "+1-555-0128", False),
            ("hgranger", "Hermione Granger", "Knowledge Engineering", "Acme Corp", "hgranger@acme.com", "+1-555-0129", False),
            ("rwesley", "Ron Wesley", "IT Service Desk", "Acme Corp", "rwesley@acme.com", "+1-555-0130", False),
            ("ptest", "Patricia Test (Inactivo)", "Contractor Old", "CloudOps Consulting", "ptest@cloudops.io", "+1-555-0131", True),
        ]

        dir_users = {}
        for username, nombre, depto, emp, email, tel, externo in user_specs:
            is_active = "Inactivo" not in nombre
            du = DirectorioUsuario(
                username=username,
                sam_account_name=username,
                nombre_completo=nombre,
                departamento=depto,
                empresa=emp,
                email=email,
                telefono=tel,
                activo_ad=is_active,
                notas="Consultor Externo" if externo else ("Usuario inactivo" if not is_active else None)
            )
            db.session.add(du)
            dir_users[username] = du
        db.session.commit()

        print("[7/9] Generando parque de 70+ Máquinas Virtuales (VDIs, RPAs, Masters, Huérfanas)...")
        maquinas_creadas = []

        def vincular(maq_obj, u_name):
            if u_name in dir_users:
                v = MaquinaUsuarioDir(
                    maquina_id=maq_obj.id,
                    directorio_usuario_id=dir_users[u_name].id,
                    tipo="principal",
                    activo=True
                )
                db.session.add(v)

        # ── Grupo A: VDIs Conectadas en Engineering (Instant Clones) ───────────────────
        eng_users = ["arivera", "evance", "mholloway", "tanderson", "hpotter", "hgranger", "rwesley", "ckent"]
        for idx, u_name in enumerate(eng_users, start=1):
            vm_name = f"VDI-ENG-W11-{idx:03d}"
            disk_used = 114.5 if idx == 3 else round(random.uniform(42.0, 78.0), 1)
            m = Maquina(
                servidor_id=srv_horizon_dt.id,
                external_id=f"vm-eng-{idx:03d}",
                nombre=vm_name,
                dns=f"{vm_name.lower()}.corp.local",
                ip_principal=f"10.20.10.{10 + idx}",
                so="Windows 11 Enterprise 64-bit (23H2)",
                cpu=8,
                ram_gb=16.0,
                disk_provisioned_gb=120.0,
                disk_used_gb=disk_used,
                estado_vcenter="PoweredOn",
                estado_horizon="CONNECTED",
                usuario_asignado=u_name,
                fecha_ultimo_ingreso=(datetime.utcnow() - timedelta(hours=random.randint(1, 6))).strftime("%Y-%m-%d %H:%M:%S"),
                pool_id=pools["eng"].id,
                _pool_str=pools["eng"].nombre,
                empresa_id=empresas["acme"].id,
                _empresa_str=empresas["acme"].nombre,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VDI",
                tipo_provisionamiento="INSTANT_CLONE",
                vcenter_host="esx-dt-01.corp.local",
                folder="Workstations/Engineering",
                resource_pool="RP-Desktops-HighPerformance",
                datastores="vsanDatastore-DT-Cluster01",
                hardware_version="vmx-20",
                connection_state="CONNECTED",
                tools_status="toolsOk",
                client_ip=f"192.168.1.{100 + idx}",
                client_name=f"THINCLIENT-ENG-{idx:02d}",
                gateway_name="gw-uag01.corp.local",
                session_protocol="BLAST",
                datos_extra_json=json.dumps({"tiempo_sesion": f"{random.randint(1, 7)}h {random.randint(10, 55)}m"}),
                activo=True
            )
            db.session.add(m)
            maquinas_creadas.append((m, u_name))

        # ── Grupo B: VDIs Disponibles en Engineering (Pool Buffer) ─────────────────────
        for idx in range(9, 15):
            vm_name = f"VDI-ENG-W11-{idx:03d}"
            m = Maquina(
                servidor_id=srv_horizon_dt.id,
                external_id=f"vm-eng-{idx:03d}",
                nombre=vm_name,
                dns=f"{vm_name.lower()}.corp.local",
                ip_principal=f"10.20.10.{10 + idx}",
                so="Windows 11 Enterprise 64-bit (23H2)",
                cpu=8,
                ram_gb=16.0,
                disk_provisioned_gb=120.0,
                disk_used_gb=round(random.uniform(35.0, 45.0), 1),
                estado_vcenter="PoweredOn",
                estado_horizon="AVAILABLE",
                usuario_asignado=None,
                pool_id=pools["eng"].id,
                _pool_str=pools["eng"].nombre,
                empresa_id=empresas["acme"].id,
                _empresa_str=empresas["acme"].nombre,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VDI",
                tipo_provisionamiento="INSTANT_CLONE",
                vcenter_host="esx-dt-02.corp.local",
                folder="Workstations/Engineering",
                resource_pool="RP-Desktops-HighPerformance",
                datastores="vsanDatastore-DT-Cluster01",
                hardware_version="vmx-20",
                connection_state="CONNECTED",
                tools_status="toolsOk",
                activo=True
            )
            db.session.add(m)
            maquinas_creadas.append((m, None))

        # ── Grupo C: Finance Secure Desktops (Floating) ─────────────────────────────────
        fin_users = ["dmiller", "rchen", "ewatson", "adent", "fprefect"]
        for idx, u_name in enumerate(fin_users, start=1):
            vm_name = f"VDI-FIN-SEC-{idx:03d}"
            m = Maquina(
                servidor_id=srv_horizon_dt.id,
                external_id=f"vm-fin-{idx:03d}",
                nombre=vm_name,
                dns=f"{vm_name.lower()}.corp.local",
                ip_principal=f"10.20.20.{20 + idx}",
                so="Windows 11 Pro 64-bit (Compliant Build)",
                cpu=4,
                ram_gb=16.0,
                disk_provisioned_gb=100.0,
                disk_used_gb=round(random.uniform(40.0, 65.0), 1),
                estado_vcenter="PoweredOn",
                estado_horizon="CONNECTED",
                usuario_asignado=u_name,
                fecha_ultimo_ingreso=(datetime.utcnow() - timedelta(hours=random.randint(1, 4))).strftime("%Y-%m-%d %H:%M:%S"),
                pool_id=pools["fin"].id,
                _pool_str=pools["fin"].nombre,
                empresa_id=empresas["finsvc"].id,
                _empresa_str=empresas["finsvc"].nombre,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VDI",
                tipo_provisionamiento="INSTANT_CLONE",
                vcenter_host="esx-dt-02.corp.local",
                folder="Workstations/Finance",
                resource_pool="RP-Finance-Secure",
                datastores="vsanDatastore-DT-Cluster01",
                hardware_version="vmx-20",
                connection_state="CONNECTED",
                tools_status="toolsOk",
                client_ip=f"192.168.2.{50 + idx}",
                gateway_name="gw-uag02.corp.local",
                session_protocol="BLAST",
                datos_extra_json=json.dumps({"tiempo_sesion": f"{random.randint(2, 8)}h {random.randint(5, 50)}m"}),
                activo=True
            )
            db.session.add(m)
            maquinas_creadas.append((m, u_name))

        # Floating disponibles en Finance
        for idx in range(6, 10):
            vm_name = f"VDI-FIN-SEC-{idx:03d}"
            m = Maquina(
                servidor_id=srv_horizon_dt.id,
                external_id=f"vm-fin-{idx:03d}",
                nombre=vm_name,
                dns=f"{vm_name.lower()}.corp.local",
                ip_principal=f"10.20.20.{20 + idx}",
                so="Windows 11 Pro 64-bit (Compliant Build)",
                cpu=4,
                ram_gb=16.0,
                disk_provisioned_gb=100.0,
                disk_used_gb=32.0,
                estado_vcenter="PoweredOn",
                estado_horizon="AVAILABLE",
                usuario_asignado=None,
                pool_id=pools["fin"].id,
                _pool_str=pools["fin"].nombre,
                empresa_id=empresas["finsvc"].id,
                _empresa_str=empresas["finsvc"].nombre,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VDI",
                tipo_provisionamiento="INSTANT_CLONE",
                vcenter_host="esx-dt-03.corp.local",
                folder="Workstations/Finance",
                resource_pool="RP-Finance-Secure",
                datastores="vsanDatastore-DT-Cluster01",
                hardware_version="vmx-20",
                activo=True
            )
            db.session.add(m)
            maquinas_creadas.append((m, None))

        # ── Grupo D: Operations Shift (Win10) ──────────────────────────────────────────
        ops_users = ["sconnor", "jalba", "jwilson", "ballen"]
        for idx, u_name in enumerate(ops_users, start=1):
            vm_name = f"VDI-OPS-W10-{idx:03d}"
            m = Maquina(
                servidor_id=srv_horizon_dt.id,
                external_id=f"vm-ops-{idx:03d}",
                nombre=vm_name,
                dns=f"{vm_name.lower()}.corp.local",
                ip_principal=f"10.20.30.{30 + idx}",
                so="Windows 10 Enterprise LTSC 2021",
                cpu=4,
                ram_gb=8.0,
                disk_provisioned_gb=80.0,
                disk_used_gb=round(random.uniform(30.0, 52.0), 1),
                estado_vcenter="PoweredOn",
                estado_horizon="CONNECTED",
                usuario_asignado=u_name,
                pool_id=pools["ops"].id,
                _pool_str=pools["ops"].nombre,
                empresa_id=empresas["globaltech"].id,
                _empresa_str=empresas["globaltech"].nombre,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VDI",
                tipo_provisionamiento="INSTANT_CLONE",
                vcenter_host="esx-dt-01.corp.local",
                folder="Workstations/Operations",
                resource_pool="RP-Operations-Floor",
                datastores="vsanDatastore-DT-Cluster01",
                hardware_version="vmx-19",
                session_protocol="BLAST",
                datos_extra_json=json.dumps({"tiempo_sesion": f"{random.randint(3, 9)}h {random.randint(1, 40)}m"}),
                activo=True
            )
            db.session.add(m)
            maquinas_creadas.append((m, u_name))

        # ── Grupo E: DevOps Heavy Compute ──────────────────────────────────────────────
        devops_users = ["mchang", "cdiaz", "srossi", "tortiz", "mreed"]
        for idx, u_name in enumerate(devops_users, start=1):
            vm_name = f"DEV-WORKSTATION-{idx:02d}"
            disk_used = 236.0 if idx == 2 else round(random.uniform(110.0, 180.0), 1)
            m = Maquina(
                servidor_id=srv_horizon_dt.id,
                external_id=f"vm-dev-{idx:02d}",
                nombre=vm_name,
                dns=f"{vm_name.lower()}.corp.local",
                ip_principal=f"10.20.40.{10 + idx}",
                so="Windows 11 Enterprise (WSL2 + Docker Preloaded)",
                cpu=16,
                ram_gb=32.0,
                disk_provisioned_gb=250.0,
                disk_used_gb=disk_used,
                estado_vcenter="PoweredOn",
                estado_horizon="CONNECTED",
                usuario_asignado=u_name,
                pool_id=pools["devops"].id,
                _pool_str=pools["devops"].nombre,
                empresa_id=empresas["cloudops"].id,
                _empresa_str=empresas["cloudops"].nombre,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VDI",
                tipo_provisionamiento="FULL",
                vcenter_host="esx-dt-03.corp.local",
                folder="Workstations/DevOps",
                resource_pool="RP-DevOps-Compute",
                datastores="NVMe-FastTier-Pool01",
                hardware_version="vmx-20",
                session_protocol="BLAST",
                activo=True
            )
            db.session.add(m)
            maquinas_creadas.append((m, u_name))

        # ── Grupo F: Executive Remote Suite (DMZ / MZ) ─────────────────────────────────
        exec_users = ["bwayne", "dprince", "lorgana"]
        for idx, u_name in enumerate(exec_users, start=1):
            vm_name = f"VDI-EXEC-MZ-{idx:02d}"
            m = Maquina(
                servidor_id=srv_horizon_mz.id,
                external_id=f"vm-exec-{idx:02d}",
                nombre=vm_name,
                dns=f"{vm_name.lower()}.corp.local",
                ip_principal=f"10.50.10.{10 + idx}",
                so="Windows 11 Enterprise Shielded",
                cpu=8,
                ram_gb=32.0,
                disk_provisioned_gb=150.0,
                disk_used_gb=round(random.uniform(50.0, 85.0), 1),
                estado_vcenter="PoweredOn",
                estado_horizon="CONNECTED",
                usuario_asignado=u_name,
                pool_id=pools["exec"].id,
                _pool_str=pools["exec"].nombre,
                empresa_id=empresas["acme"].id,
                _empresa_str=empresas["acme"].nombre,
                origen_id=origenes["mz"].id,
                _origen_str="mz",
                tipo="VDI",
                tipo_provisionamiento="INSTANT_CLONE",
                vcenter_host="esx-mz-01.corp.local",
                folder="Workstations/Executive",
                resource_pool="RP-DMZ-Executive",
                datastores="vsanDatastore-MZ-Cluster01",
                hardware_version="vmx-20",
                session_protocol="BLAST",
                datos_extra_json=json.dumps({"tiempo_sesion": "4h 15m"}),
                activo=True
            )
            db.session.add(m)
            maquinas_creadas.append((m, u_name))

        # ── Grupo G: VDIs con Estados de Advertencia (Alertas de Salud) ────────────────
        unreachable_vm = Maquina(
            servidor_id=srv_horizon_dt.id,
            external_id="vm-warn-001",
            nombre="VDI-ENG-W11-099",
            dns="vdi-eng-w11-099.corp.local",
            ip_principal="10.20.10.99",
            so="Windows 11 Enterprise 64-bit",
            cpu=8,
            ram_gb=16.0,
            disk_provisioned_gb=120.0,
            disk_used_gb=40.0,
            estado_vcenter="PoweredOn",
            estado_horizon="AGENT_UNREACHABLE",
            usuario_asignado="lvance",
            pool_id=pools["eng"].id,
            _pool_str=pools["eng"].nombre,
            empresa_id=empresas["globaltech"].id,
            _empresa_str=empresas["globaltech"].nombre,
            origen_id=origenes["dt"].id,
            _origen_str="dt",
            tipo="VDI",
            tipo_provisionamiento="INSTANT_CLONE",
            vcenter_host="esx-dt-01.corp.local",
            folder="Workstations/Engineering",
            connection_state="CONNECTED",
            tools_status="toolsNotRunning",
            activo=True
        )
        db.session.add(unreachable_vm)
        maquinas_creadas.append((unreachable_vm, "lvance"))

        disc_vm = Maquina(
            servidor_id=srv_horizon_dt.id,
            external_id="vm-warn-002",
            nombre="VDI-OPS-W10-098",
            dns="vdi-ops-w10-098.corp.local",
            ip_principal="10.20.30.98",
            so="Windows 10 Enterprise LTSC 2021",
            cpu=4,
            ram_gb=8.0,
            disk_provisioned_gb=80.0,
            disk_used_gb=28.0,
            estado_vcenter="PoweredOn",
            estado_horizon="DISCONNECTED",
            usuario_asignado="hsolo",
            pool_id=pools["ops"].id,
            _pool_str=pools["ops"].nombre,
            empresa_id=empresas["globaltech"].id,
            _empresa_str=empresas["globaltech"].nombre,
            origen_id=origenes["dt"].id,
            _origen_str="dt",
            tipo="VDI",
            tipo_provisionamiento="INSTANT_CLONE",
            vcenter_host="esx-dt-02.corp.local",
            session_protocol="BLAST",
            activo=True
        )
        db.session.add(disc_vm)
        maquinas_creadas.append((disc_vm, "hsolo"))

        # ── Grupo H: Bots de Automatización RPA (VM_ESTATICA) ──────────────────────────
        for idx in range(1, 7):
            rpa_name = f"PC-RPA-AUTOMATION-{idx:02d}"
            rpa_vm = Maquina(
                servidor_id=srv_vcenter_dt.id,
                external_id=f"vm-rpa-{idx:02d}",
                nombre=rpa_name,
                dns=f"{rpa_name.lower()}.corp.local",
                ip_principal=f"10.30.50.{10 + idx}",
                so="Windows Server 2022 Datacenter",
                cpu=8,
                ram_gb=32.0,
                disk_provisioned_gb=160.0,
                disk_used_gb=round(random.uniform(55.0, 95.0), 1),
                estado_vcenter="PoweredOn",
                estado_horizon="N/A (vCenter)",
                usuario_asignado="service_rpa_bot",
                pool_id=pools["estatica"].id,
                _pool_str=pools["estatica"].nombre,
                empresa_id=empresas["acme"].id,
                _empresa_str=empresas["acme"].nombre,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VM",
                tipo_provisionamiento="VM_ESTATICA",
                vcenter_host="esx-dt-01.corp.local",
                folder="Automation/UiPath-Bots",
                resource_pool="RP-Automation-RPA",
                datastores="vsanDatastore-DT-Cluster01",
                hardware_version="vmx-20",
                annotation="Bot de automatización contable y conciliación bancaria nocturna",
                datos_extra_json=json.dumps({"categoria_estatica": "RPA"}),
                activo=True
            )
            db.session.add(rpa_vm)
            maquinas_creadas.append((rpa_vm, None))

        # ── Grupo I: Golden Masters y Plantillas de Despliegue ─────────────────────────
        masters = [
            ("PC-MST-WIN11-ENG", "Windows 11 Enterprise 23H2 (Engineering Master Image)", "Master Activa", pools["eng"], True),
            ("PC-MST-WIN11-FIN", "Windows 11 Pro Secure (Finance Master Image)", "Master Activa", pools["fin"], True),
            ("PC-MST-WIN10-LTS", "Windows 10 Enterprise LTSC (Operations Master)", "Master Activa", pools["ops"], True),
            ("PC-MST-WIN11-EXEC", "Windows 11 Shielded (Executive DMZ Master)", "Master Activa", pools["exec"], True),
            ("PC-MST-WIN11-ENG-OLD", "Windows 11 v2.8 (Obsoleta - Desactivada)", "Copia (no activa)", pools["eng"], False),
            ("PC-MST-WIN11-FIN-v1", "Windows 11 v1.4 (Archivada)", "Copia (no activa)", pools["fin"], False),
        ]
        for m_name, note, cat, pool_ref, es_active_master in masters:
            m_master = Maquina(
                servidor_id=srv_vcenter_dt.id if pool_ref.origen == "dt" else srv_vcenter_mz.id,
                external_id=f"vm-mst-{m_name.lower()}",
                nombre=m_name,
                dns=f"{m_name.lower()}.corp.local",
                ip_principal=None,
                so="Windows 11 Enterprise 64-bit",
                cpu=8,
                ram_gb=16.0,
                disk_provisioned_gb=120.0,
                disk_used_gb=42.0,
                estado_vcenter="PoweredOff",
                estado_horizon="N/A (vCenter)",
                usuario_asignado=None,
                pool_id=pools["estatica"].id,
                _pool_str=pools["estatica"].nombre,
                empresa_id=empresas["acme"].id,
                _empresa_str=empresas["acme"].nombre,
                origen_id=origenes[pool_ref.origen].id,
                _origen_str=pool_ref.origen,
                tipo="VM",
                tipo_provisionamiento="MASTER" if es_active_master else "VM_ESTATICA",
                folder="Golden-Images/Templates",
                datastores="NFS-Templates-ISO-01",
                annotation=note,
                datos_extra_json=json.dumps({"categoria_estatica": cat, "es_master": es_active_master}),
                activo=True
            )
            db.session.add(m_master)
            maquinas_creadas.append((m_master, None))

        # ── Grupo J: VDIs Huérfanas (Detector de VMs huérfanas en vCenter) ──────────────
        for idx in range(1, 5):
            o_name = f"VDI-ORPHAN-OLD-{idx:03d}"
            m_orphan = Maquina(
                servidor_id=srv_vcenter_dt.id,
                external_id=f"vm-orphan-{idx:03d}",
                nombre=o_name,
                dns=f"{o_name.lower()}.corp.local",
                ip_principal=f"10.20.99.{idx}",
                so="Windows 10 Enterprise",
                cpu=4,
                ram_gb=8.0,
                disk_provisioned_gb=80.0,
                disk_used_gb=38.0,
                estado_vcenter="PoweredOff",
                estado_horizon="N/A (vCenter)",
                usuario_asignado=None,
                pool_id=pools["estatica"].id,
                _pool_str=pools["estatica"].nombre,
                empresa_id=None,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VM",
                tipo_provisionamiento="VM_ESTATICA",
                folder="Discovered Virtual Machine",
                datastores="vsanDatastore-DT-Cluster01",
                annotation="VM remanente de pool desmantelado en 2025. Pendiente de decomiso.",
                datos_extra_json=json.dumps({"categoria_estatica": "VDI Huérfana (sin pool Horizon)"}),
                activo=True
            )
            db.session.add(m_orphan)
            maquinas_creadas.append((m_orphan, None))

        # ── Grupo K: Infraestructura Interna del Clúster ───────────────────────────────
        infra_vms = [
            ("vCLS-DT-Cluster-01", "vSphere Cluster Services Node 1"),
            ("vCLS-DT-Cluster-02", "vSphere Cluster Services Node 2"),
            ("vCLS-MZ-Cluster-01", "vSphere Cluster Services Node MZ"),
            ("NSX-Edge-Gateway-01", "Software Defined Network Gateway"),
        ]
        for inf_name, inf_desc in infra_vms:
            m_infra = Maquina(
                servidor_id=srv_vcenter_dt.id,
                external_id=f"vm-inf-{inf_name.lower()}",
                nombre=inf_name,
                dns=None,
                ip_principal="10.10.10.15",
                so="Photon OS Linux 64-bit",
                cpu=2,
                ram_gb=4.0,
                disk_provisioned_gb=16.0,
                disk_used_gb=6.0,
                estado_vcenter="PoweredOn",
                estado_horizon="N/A (vCenter)",
                pool_id=pools["estatica"].id,
                _pool_str=pools["estatica"].nombre,
                origen_id=origenes["dt"].id,
                _origen_str="dt",
                tipo="VM",
                tipo_provisionamiento="VM_ESTATICA",
                folder="vSphere Cluster Services",
                annotation=inf_desc,
                datos_extra_json=json.dumps({"categoria_estatica": "Infraestructura"}),
                activo=True
            )
            db.session.add(m_infra)
            maquinas_creadas.append((m_infra, None))

        db.session.commit()

        # Vincular usuarios de directorio con máquinas creadas
        print("[8/9] Vinculando usuarios de Directorio y aprovisionando App Volumes...")
        for m_obj, u_name in maquinas_creadas:
            if u_name:
                vincular(m_obj, u_name)
        db.session.commit()

        # 8. App Volumes (Aplicaciones, Paquetes, Asignaciones, Writables)
        app_suite = AppVolumesAplicacion(
            servidor_id=srv_appvolumes.id,
            av_id=101,
            guid="app-guid-developer-2026",
            nombre="Developer Workstation Suite 2026",
            descripcion="Docker Desktop, Git, NodeJS, PyCharm Professional, DBeaver Enterprise",
            assignment_count=18,
            activo=True
        )
        app_fin = AppVolumesAplicacion(
            servidor_id=srv_appvolumes.id,
            av_id=102,
            guid="app-guid-financial-terminal",
            nombre="Financial Analytics & Bloomberg Terminal",
            descripcion="Herramientas de cálculo financiero y trading compliant",
            assignment_count=8,
            activo=True
        )
        app_corp = AppVolumesAplicacion(
            servidor_id=srv_appvolumes.id,
            av_id=103,
            guid="app-guid-corporate-core",
            nombre="Corporate Productivity Pack",
            descripcion="Office 365, Teams, Acrobat Pro, GlobalProtect VPN",
            assignment_count=45,
            activo=True
        )
        db.session.add_all([app_suite, app_fin, app_corp])
        db.session.commit()

        pkg_dev = AppVolumesPaquete(
            servidor_id=srv_appvolumes.id,
            av_id=201,
            aplicacion_id=app_suite.id,
            guid="pkg-guid-dev-v3",
            nombre="DevSuite-v3.4.1-Prod",
            version="3.4.1",
            status="enabled",
            lifecycle_stage="Published",
            size_mb=18400.0,
            datastore_name="vsanDatastore-DT-Cluster01",
            activo=True
        )
        pkg_fin = AppVolumesPaquete(
            servidor_id=srv_appvolumes.id,
            av_id=202,
            aplicacion_id=app_fin.id,
            guid="pkg-guid-fin-v2",
            nombre="FinTerminal-v2.1-Prod",
            version="2.1.0",
            status="enabled",
            lifecycle_stage="Published",
            size_mb=12200.0,
            datastore_name="vsanDatastore-DT-Cluster01",
            activo=True
        )
        db.session.add_all([pkg_dev, pkg_fin])
        db.session.commit()

        # Asignaciones App Volumes
        asigs = [
            AppVolumesAsignacion(servidor_id=srv_appvolumes.id, av_id=301, aplicacion_id=app_suite.id, paquete_id=pkg_dev.id, entity_type="Group", entity_name="CORP\\GRP-Engineering-Staff", delivery="classic", activo=True),
            AppVolumesAsignacion(servidor_id=srv_appvolumes.id, av_id=302, aplicacion_id=app_suite.id, paquete_id=pkg_dev.id, entity_type="Group", entity_name="CORP\\GRP-DevOps-Admins", delivery="classic", activo=True),
            AppVolumesAsignacion(servidor_id=srv_appvolumes.id, av_id=303, aplicacion_id=app_fin.id, paquete_id=pkg_fin.id, entity_type="Group", entity_name="CORP\\GRP-Financial-Analysts", delivery="classic", activo=True),
        ]
        db.session.add_all(asigs)

        # Writable Volumes (Perfil y Datos persistentes por usuario)
        writables = [
            AppVolumesWritable(
                servidor_id=srv_appvolumes.id,
                av_id=401,
                guid="wrt-arivera-01",
                nombre="Alex Rivera (Writable Profile + UIA)",
                tipo="profile_uia",
                entity_type="User",
                entity_name="arivera",
                owner_display_name="Alex Rivera",
                owner_email="arivera@acme.com",
                estado="attached",
                attached_to="VDI-ENG-W11-001",
                size_mb=20480.0,
                used_mb=13450.0,
                datastore_name="vsanDatastore-DT-Cluster01",
                provisioned_at=datetime.utcnow() - timedelta(days=90),
                activo=True
            ),
            AppVolumesWritable(
                servidor_id=srv_appvolumes.id,
                av_id=402,
                guid="wrt-evance-01",
                nombre="Elena Vance (Writable Profile + UIA)",
                tipo="profile_uia",
                entity_type="User",
                entity_name="evance",
                owner_display_name="Elena Vance",
                owner_email="evance@acme.com",
                estado="attached",
                attached_to="VDI-ENG-W11-002",
                size_mb=20480.0,
                used_mb=15200.0,
                datastore_name="vsanDatastore-DT-Cluster01",
                provisioned_at=datetime.utcnow() - timedelta(days=80),
                activo=True
            ),
            AppVolumesWritable(
                servidor_id=srv_appvolumes.id,
                av_id=403,
                guid="wrt-mchang-01",
                nombre="Michael Chang (DevOps Heavy Volume)",
                tipo="profile_uia",
                entity_type="User",
                entity_name="mchang",
                owner_display_name="Michael Chang",
                owner_email="mchang@cloudops.io",
                estado="attached",
                attached_to="DEV-WORKSTATION-01",
                size_mb=40960.0,
                used_mb=34200.0,
                datastore_name="NVMe-FastTier-Pool01",
                provisioned_at=datetime.utcnow() - timedelta(days=60),
                activo=True
            ),
            AppVolumesWritable(
                servidor_id=srv_appvolumes.id,
                av_id=404,
                guid="wrt-dmiller-01",
                nombre="David Miller (Finance Writable)",
                tipo="profile",
                entity_type="User",
                entity_name="dmiller",
                owner_display_name="David Miller",
                owner_email="dmiller@finservices.org",
                estado="attached",
                attached_to="VDI-FIN-SEC-001",
                size_mb=10240.0,
                used_mb=4200.0,
                datastore_name="vsanDatastore-DT-Cluster01",
                provisioned_at=datetime.utcnow() - timedelta(days=45),
                activo=True
            ),
        ]
        db.session.add_all(writables)

        print("[9/9] Registrando eventos de auditoría y telemetría de hipervisor...")
        # 9. Historial de Máquinas y Eventos
        first_vm = Maquina.query.filter_by(nombre="VDI-ENG-W11-001").first()
        if first_vm:
            db.session.add_all([
                MaquinaHistorial(
                    maquina_id=first_vm.id,
                    snapshot_id=snap_dt.id,
                    campo_modificado="cpu",
                    valor_anterior="4",
                    valor_nuevo="8",
                    detectado_en=datetime.utcnow() - timedelta(days=14)
                ),
                MaquinaHistorial(
                    maquina_id=first_vm.id,
                    snapshot_id=snap_dt.id,
                    campo_modificado="ram_gb",
                    valor_anterior="8.0",
                    valor_nuevo="16.0",
                    detectado_en=datetime.utcnow() - timedelta(days=14)
                ),
            ])

        crit_vm = Maquina.query.filter_by(nombre="VDI-ENG-W11-003").first()
        if crit_vm:
            db.session.add(
                MaquinaHistorial(
                    maquina_id=crit_vm.id,
                    snapshot_id=snap_dt.id,
                    campo_modificado="disco_critico",
                    valor_anterior="76.2%",
                    valor_nuevo="95.4%",
                    detectado_en=datetime.utcnow() - timedelta(hours=3)
                )
            )

        # Eventos vSphere Monitor
        for m_obj, _ in maquinas_creadas[:15]:
            db.session.add(VMTareaEvento(
                maquina_id=m_obj.id,
                tipo="task",
                nombre_evento="VmClonedEvent",
                mensaje=f"Máquina virtual {m_obj.nombre} clonada automáticamente desde Instant Clone master",
                usuario="CORP\\service_vdi_ic",
                estado="success",
                fecha=datetime.utcnow() - timedelta(days=random.randint(1, 10))
            ))
            db.session.add(VMTareaEvento(
                maquina_id=m_obj.id,
                tipo="evento",
                nombre_evento="VmPoweredOnEvent",
                mensaje=f"Máquina virtual {m_obj.nombre} encendida en clúster ESXi",
                usuario="CORP\\service_vdi_ic",
                estado="success",
                fecha=datetime.utcnow() - timedelta(hours=random.randint(1, 24))
            ))

        # Eventos de infraestructura y alertas
        db.session.add_all([
            InfraEvento(
                tipo="datastore_critico",
                entidad_nombre="NVMe-FastTier-Pool01",
                servidor_id=srv_vcenter_dt.id,
                valor_anterior="86.4%",
                valor_nuevo="92.2%",
                mensaje="Datastore NVMe-FastTier-Pool01 superó el umbral crítico (>90%). Espacio libre: 620 GB de 8000 GB.",
                detectado_en=datetime.utcnow() - timedelta(hours=5)
            ),
            InfraEvento(
                tipo="horizon_audit",
                entidad_nombre="Engineering-Win11",
                servidor_id=srv_horizon_dt.id,
                mensaje="Image Publish initiated by SchedulePushImage for Pool Engineering-Win11 succeeded for Image [VM=/DT/vm/Golden-Images/Templates/PC-MST-WIN11-ENG, Snapshot=/Base-Clean/v3.2_STABLE_PROD, State=PUBLISHING]",
                detectado_en=datetime.utcnow() - timedelta(days=5)
            ),
        ])

        # Logs de auditoría
        audit_logs = [
            AuditoriaLog(
                usuario_id=admin.id,
                username="admin",
                accion="login",
                resultado="exito",
                detalle="Inicio de sesión administrativo desde consola web",
                ip_origen="127.0.0.1",
                timestamp=datetime.utcnow() - timedelta(hours=1)
            ),
            AuditoriaLog(
                usuario_id=admin.id,
                username="admin",
                accion="extraccion_completa",
                resultado="exito",
                detalle="Sincronización multi-hipervisor completada para todos los centros de datos",
                ip_origen="127.0.0.1",
                timestamp=datetime.utcnow() - timedelta(minutes=15)
            ),
            AuditoriaLog(
                usuario_id=demo.id,
                username="demo",
                accion="export_csv",
                recurso="inventario",
                resultado="exito",
                detalle="Exportación de parque completo de 70 máquinas a formato CSV",
                ip_origen="192.168.1.150",
                timestamp=datetime.utcnow() - timedelta(minutes=40)
            ),
        ]
        db.session.add_all(audit_logs)

        db.session.commit()

        print("\n================================================================")
        print("[+] Base de datos sembrada exitosamente!")
        print(f"[*] Ubicacion: {db_path}")
        print("[*] Credenciales de prueba disponibles:")
        print("   - Administrador:  admin   / Admin123!")
        print("   - Operador Demo:  demo    / Demo123!")
        print("   - Auditor Visor:  auditor / Auditor123!")
        print("================================================================\n")

if __name__ == "__main__":
    run_seed()
