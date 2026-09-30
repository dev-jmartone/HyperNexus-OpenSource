"""
web/db.py
Modelos SQLAlchemy profesionalizados, normalizados y portables para inventario-vdi.
"""
import os
import base64
import json
import enum
import logging
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import event, func
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        row = cursor.fetchone()
        journal_mode = str(row[0]).lower() if row and len(row) > 0 and row[0] is not None else ""
        if journal_mode != "wal":
            logging.warning(
                "SQLite journal_mode no pudo activarse en WAL (modo efectivo: '%s'). "
                "Esto es tipico cuando la base de datos reside en un filesystem de red (ej. perfil VDI redirigido), "
                "donde WAL no es confiable. Se recomienda usar la variable de entorno INVENTARIO_DB_PATH "
                "para mover la base de datos a un disco local.",
                row[0] if row and len(row) > 0 else "desconocido",
            )
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception as e:
        logging.warning("Error configurando SQLite PRAGMAs: %s", e)


# ── Enums ─────────────────────────────────────────────────────────────

class RolEnum(str, enum.Enum):
    ADMIN = "admin"
    USUARIO = "usuario"

class TipoServidorEnum(str, enum.Enum):
    HORIZON = "horizon"
    VCENTER = "vcenter"
    APP_VOLUMES = "appvolumes"

class TipoMaquinaServidorEnum(str, enum.Enum):
    VDI = "VDI"
    VM = "VM"
    AMBOS = "ambos"

class TipoMaquinaEnum(str, enum.Enum):
    VDI = "VDI"
    VM = "VM"

class EstadoSnapshotEnum(str, enum.Enum):
    PENDIENTE = "pendiente"
    EN_PROGRESO = "en_progreso"
    COMPLETADO = "completado"
    ERROR = "error"
    CANCELADO = "cancelado"


# ── Tablas Catálogo ───────────────────────────────────────────────────

class Origen(db.Model):
    """Catálogo de segmentos (dt, su, core, mz)."""
    __tablename__ = "origenes"

    id          = db.Column(db.Integer, primary_key=True)
    codigo      = db.Column(db.String(20), unique=True, nullable=False, index=True)
    descripcion = db.Column(db.String(100), nullable=True)
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {"id": self.id, "codigo": self.codigo, "descripcion": self.descripcion or ""}


class Empresa(db.Model):
    """Catálogo normalizado de empresas."""
    __tablename__ = "empresas"

    id         = db.Column(db.Integer, primary_key=True)
    nombre     = db.Column(db.String(120), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {"id": self.id, "nombre": self.nombre}


class Pool(db.Model):
    """Catálogo de pools de Horizon con propiedades extendidas."""
    __tablename__ = "pools"

    id              = db.Column(db.Integer, primary_key=True)
    nombre          = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name    = db.Column(db.String(255), nullable=True)
    tipo            = db.Column(db.String(50), nullable=True, default="Automated") # Automated, Manual, RDS
    user_assignment = db.Column(db.String(50), nullable=True, default="Dedicated") # Dedicated, Floating
    enabled         = db.Column(db.Boolean, nullable=False, default=True)  # habilitada/deshabilitada por un admin (setting de Horizon)
    activo          = db.Column(db.Boolean, nullable=False, default=True)  # sigue existiendo en Horizon (distinto de "enabled")
    origen          = db.Column(db.String(20), nullable=True)
    provisioning_error = db.Column(db.Text, nullable=True)  # último error de clonado/provisioning, vacío = sin error

    # Imagen (master VM + snapshot) actualmente publicada en el pool -- se derivan
    # parseando los eventos "Image Publish...State=PUBLISHING" de horizon_audit
    # (InfraEvento), único lugar donde Horizon reporta esto (ver
    # web/routes/inventario.py:_parsear_evento_imagen). No viene de un campo directo
    # de la API de desktop-pools.
    master_vm_actual     = db.Column(db.String(255), nullable=True)
    snapshot_actual       = db.Column(db.Text, nullable=True)
    imagen_actualizada_en = db.Column(db.DateTime, nullable=True)

    # MoRef real del master configurado (provisioning_settings.parent_vm_id de la API de
    # desktop-pools de Horizon, viene siempre en pools instant-clone, a diferencia de
    # master_vm_actual de arriba que depende de que haya un audit-event capturado). Fuente
    # confiable para saber si un master sigue en uso -- bug real encontrado 2026-08-13:
    # solo 3 de 48 pools tenían master_vm_actual seteado, haciendo que /pools/masters
    # mostrara casi todo como "en desuso" y subcontara VMs impactadas.
    master_moref = db.Column(db.String(50), nullable=True)

    # FK a Farm cuando tipo=='RDS' -- seteado desde el campo farm_id del payload de
    # desktop-pools (ver core/horizon_rest.py). Enlaza el Pool RDS existente (ej.
    # RDS_Desktop/POC_RDS) con su Farm real de Horizon.
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=True)

    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "display_name": self.display_name or self.nombre,
            "tipo": self.tipo or "Automated",
            "user_assignment": self.user_assignment or "Dedicated",
            "enabled": self.enabled if self.enabled is not None else True,
            "activo": self.activo if self.activo is not None else True,
            "origen": self.origen or "—",
            "provisioning_error": self.provisioning_error or "",
            "master_vm_actual": self.master_vm_actual or "",
            "master_moref": self.master_moref or "",
            "snapshot_actual": self.snapshot_actual or "",
            "imagen_actualizada_en": self.imagen_actualizada_en.strftime("%d/%m/%Y %H:%M") if self.imagen_actualizada_en else "",
            "farm_id": self.farm_id,
        }


class PoolEntitlement(db.Model):
    """
    Autorizaciones Locales y Globales de Usuarios y Grupos por Pool en Horizon.
    """
    __tablename__ = "pool_entitlements"

    id               = db.Column(db.Integer, primary_key=True)
    pool_id          = db.Column(db.Integer, db.ForeignKey("pools.id", ondelete="CASCADE"), nullable=True, index=True)
    pool_nombre      = db.Column(db.String(255), nullable=False, index=True)
    usuario_o_grupo  = db.Column(db.String(255), nullable=False, index=True)
    tipo_entitlement = db.Column(db.String(50), nullable=False, default="Local") # "Local" o "Global"
    es_grupo         = db.Column(db.Boolean, nullable=False, default=False)
    servidor_id      = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=True)
    origen           = db.Column(db.String(20), nullable=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pool_id": self.pool_id,
            "pool_nombre": self.pool_nombre,
            "usuario_o_grupo": self.usuario_o_grupo,
            "tipo_entitlement": self.tipo_entitlement,
            "es_grupo": self.es_grupo,
            "origen": self.origen or "",
            "fecha": self.created_at.strftime("%d/%m/%Y %H:%M") if self.created_at else "",
        }


class Farm(db.Model):
    """Catálogo de Farms (granjas RDS) de Horizon -- backend de Application Pools y,
    opcionalmente, de un Desktop Pool tipo RDS (ver Pool.farm_id)."""
    __tablename__ = "farms"

    id                      = db.Column(db.Integer, primary_key=True)
    nombre                  = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name            = db.Column(db.String(255), nullable=True)
    tipo                    = db.Column(db.String(50), nullable=True, default="AUTOMATED")  # AUTOMATED, MANUAL
    # id externo de Horizon -- usado para matchear application-pools[].farm_id y
    # desktop-pools[].farm_id contra esta Farm (ver _guardar_granja_horizon).
    horizon_farm_id         = db.Column(db.String(100), nullable=True, index=True)
    rds_server_max_sessions = db.Column(db.Integer, nullable=True)
    enabled                 = db.Column(db.Boolean, nullable=False, default=True)
    provisioning_error      = db.Column(db.Text, nullable=True)
    activo                  = db.Column(db.Boolean, nullable=False, default=True)
    origen                  = db.Column(db.String(20), nullable=True)
    servidor_id             = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=True)
    created_at              = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at              = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    aplicaciones = db.relationship("AplicacionPublicada", backref="farm", lazy=True)
    rds_servers  = db.relationship("FarmRdsServer", backref="farm", lazy=True, cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "display_name": self.display_name or self.nombre,
            "tipo": self.tipo or "AUTOMATED",
            "enabled": self.enabled if self.enabled is not None else True,
            "activo": self.activo if self.activo is not None else True,
            "origen": self.origen or "—",
            "rds_server_max_sessions": self.rds_server_max_sessions,
            "provisioning_error": self.provisioning_error or "",
        }


class AplicacionPublicada(db.Model):
    """Application Pool (aplicación publicada) de Horizon, opcionalmente respaldada por una Farm."""
    __tablename__ = "aplicaciones_publicadas"

    id               = db.Column(db.Integer, primary_key=True)
    nombre           = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name     = db.Column(db.String(255), nullable=True)
    farm_id          = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=True, index=True)
    path_ejecutable  = db.Column(db.String(500), nullable=True)
    enabled          = db.Column(db.Boolean, nullable=False, default=True)
    activo           = db.Column(db.Boolean, nullable=False, default=True)
    origen           = db.Column(db.String(20), nullable=True)
    servidor_id      = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    entitlements = db.relationship("AplicacionEntitlement", backref="aplicacion", lazy=True, cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "display_name": self.display_name or self.nombre,
            "farm_id": self.farm_id,
            "farm_nombre": self.farm.nombre if self.farm else "",
            "path_ejecutable": self.path_ejecutable or "",
            "enabled": self.enabled if self.enabled is not None else True,
            "activo": self.activo if self.activo is not None else True,
            "origen": self.origen or "—",
        }


class AplicacionEntitlement(db.Model):
    """Autorizaciones Locales y Globales de Usuarios y Grupos por Aplicación Publicada en
    Horizon. Clon de PoolEntitlement, mismos campos, FK a AplicacionPublicada."""
    __tablename__ = "aplicacion_entitlements"

    id                = db.Column(db.Integer, primary_key=True)
    aplicacion_id     = db.Column(db.Integer, db.ForeignKey("aplicaciones_publicadas.id", ondelete="CASCADE"), nullable=True, index=True)
    aplicacion_nombre = db.Column(db.String(255), nullable=False, index=True)
    usuario_o_grupo   = db.Column(db.String(255), nullable=False, index=True)
    tipo_entitlement  = db.Column(db.String(50), nullable=False, default="Local")  # "Local" o "Global"
    es_grupo          = db.Column(db.Boolean, nullable=False, default=False)
    servidor_id       = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=True)
    origen            = db.Column(db.String(20), nullable=True)
    created_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "aplicacion_id": self.aplicacion_id,
            "aplicacion_nombre": self.aplicacion_nombre,
            "usuario_o_grupo": self.usuario_o_grupo,
            "tipo_entitlement": self.tipo_entitlement,
            "es_grupo": self.es_grupo,
            "origen": self.origen or "",
            "fecha": self.created_at.strftime("%d/%m/%Y %H:%M") if self.created_at else "",
        }


class FarmRdsServer(db.Model):
    """RDS Servers (hosts) que corren una Farm. El endpoint /machines de Horizon no los
    devuelve -- son un objeto aparte de la API (/farms/{id}/rds-servers). maquina_id se
    setea cuando el merge Horizon<->vCenter de Fase 2 matchea el nombre contra una VM
    real (ver _vincular_farm_rds_server en web/routes/inventario.py)."""
    __tablename__ = "farm_rds_servers"
    __table_args__ = (
        db.UniqueConstraint("farm_id", "nombre", name="uq_farm_rds_server_farm_nombre"),
    )

    id               = db.Column(db.Integer, primary_key=True)
    farm_id          = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=False, index=True)
    nombre           = db.Column(db.String(255), nullable=False, index=True)
    estado           = db.Column(db.String(50), nullable=True)
    sesiones_activas = db.Column(db.Integer, nullable=True, default=0)
    maquina_id       = db.Column(db.Integer, db.ForeignKey("maquinas.id"), nullable=True, index=True)
    enabled          = db.Column(db.Boolean, nullable=False, default=True)
    activo           = db.Column(db.Boolean, nullable=False, default=True)
    origen           = db.Column(db.String(20), nullable=True)
    servidor_id      = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    maquina = db.relationship("Maquina", foreign_keys=[maquina_id], lazy="joined")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "farm_id": self.farm_id,
            "nombre": self.nombre,
            "estado": self.estado or "",
            "sesiones_activas": self.sesiones_activas or 0,
            "maquina_id": self.maquina_id,
            "maquina": self.maquina.to_dict() if self.maquina else None,
            "enabled": self.enabled if self.enabled is not None else True,
            "activo": self.activo if self.activo is not None else True,
            "origen": self.origen or "—",
        }


class Datastore(db.Model):
    """Datastores de almacenamiento de vCenter. Tabla existía pero nunca se poblaba —
    nombre único global rompía con 4 vCenters distintos (DT/MZ/SU/Core pueden repetir
    nombre de datastore), por eso la unicidad ahora es (servidor_id, nombre)."""
    __tablename__ = "datastores"
    __table_args__ = (db.UniqueConstraint("servidor_id", "nombre", name="uq_datastore_servidor_nombre"),)

    id               = db.Column(db.Integer, primary_key=True)
    servidor_id      = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=True)
    nombre           = db.Column(db.String(255), nullable=False, index=True)
    capacidad_gb     = db.Column(db.Float, nullable=True)
    espacio_libre_gb = db.Column(db.Float, nullable=True)
    tipo             = db.Column(db.String(50), nullable=True)
    activo           = db.Column(db.Boolean, nullable=False, default=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        pct = None
        if self.capacidad_gb and self.espacio_libre_gb is not None:
            pct = round((1 - self.espacio_libre_gb / self.capacidad_gb) * 100, 1)
        return {
            "id": self.id, "nombre": self.nombre, "servidor_id": self.servidor_id,
            "capacidad_gb": self.capacidad_gb, "espacio_libre_gb": self.espacio_libre_gb,
            "espacio_usado_pct": pct, "tipo": self.tipo, "activo": self.activo,
        }


class HostEsxi(db.Model):
    """Hosts ESXi por vCenter — estado de conexión/energía. Antes solo se guardaba el
    nombre (para mostrarlo en la VM), el estado se pedía y se descartaba."""
    __tablename__ = "hosts_esxi"
    __table_args__ = (db.UniqueConstraint("servidor_id", "nombre", name="uq_host_servidor_nombre"),)

    id               = db.Column(db.Integer, primary_key=True)
    servidor_id      = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=True)
    nombre           = db.Column(db.String(255), nullable=False, index=True)
    connection_state = db.Column(db.String(30), nullable=True)
    power_state      = db.Column(db.String(30), nullable=True)
    activo           = db.Column(db.Boolean, nullable=False, default=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "nombre": self.nombre, "servidor_id": self.servidor_id,
            "connection_state": self.connection_state, "power_state": self.power_state,
            "activo": self.activo,
        }


class InfraEvento(db.Model):
    """Eventos de infraestructura NO atados a una VM puntual (datastore casi lleno,
    host desconectado, pool con errores de provisioning). MaquinaHistorial exige
    maquina_id — no sirve para alertas a nivel datastore/host/pool."""
    __tablename__ = "infra_eventos"

    id              = db.Column(db.Integer, primary_key=True)
    tipo            = db.Column(db.String(50), nullable=False, index=True)
    entidad_nombre  = db.Column(db.String(255), nullable=False)
    servidor_id     = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=True)
    valor_anterior  = db.Column(db.String(255), nullable=True)
    valor_nuevo     = db.Column(db.String(255), nullable=True)
    mensaje         = db.Column(db.Text, nullable=True)
    detectado_en    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "tipo": self.tipo, "entidad_nombre": self.entidad_nombre,
            "servidor_id": self.servidor_id, "valor_anterior": self.valor_anterior,
            "valor_nuevo": self.valor_nuevo, "mensaje": self.mensaje,
            "detectado_en": self.detectado_en.isoformat() if self.detectado_en else None,
        }


# ── Entidades Principales ─────────────────────────────────────────────

class Usuario(db.Model):
    """Usuario de la aplicación web con control de intentos y auditoría."""
    __tablename__ = "usuarios"

    id                   = db.Column(db.Integer,     primary_key=True)
    username             = db.Column(db.String(80),  unique=True, nullable=False, index=True)
    password_hash        = db.Column(db.String(256), nullable=False)
    rol                  = db.Column(db.String(20),  nullable=False, default="usuario")
    nombre_completo      = db.Column(db.String(150), nullable=True)
    email                = db.Column(db.String(150), nullable=True)
    activo               = db.Column(db.Boolean,     nullable=False, default=True)
    must_change_password = db.Column(db.Boolean,     nullable=False, default=True)
    intentos_fallidos    = db.Column(db.Integer,     nullable=False, default=0)
    bloqueado_hasta      = db.Column(db.DateTime,    nullable=True)
    created_by_id        = db.Column(db.Integer,     db.ForeignKey("usuarios.id"), nullable=True)
    created_at           = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login           = db.Column(db.DateTime,    nullable=True)
    dashboard_prefs      = db.Column(db.Text,        nullable=True)  # JSON: [{id, visible, size, order}]
    filter_presets       = db.Column(db.Text,        nullable=True)  # JSON: [{id, name, rules}]
    inventario_columnas  = db.Column(db.Text,        nullable=True)  # JSON: [column_key, ...] visibles en la tabla de Inventario

    auditoria = db.relationship("AuditoriaLog", backref="usuario_rel", foreign_keys="AuditoriaLog.usuario_id", lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "username":        self.username,
            "rol":             self.rol if isinstance(self.rol, str) else self.rol.value,
            "nombre_completo": self.nombre_completo or "",
            "email":           self.email or "",
            "activo":          self.activo,
            "must_change_password": self.must_change_password,
            "created_at":      self.created_at.isoformat() if self.created_at else "",
            "last_login":      self.last_login.isoformat() if self.last_login else "",
        }


class AuditoriaLog(db.Model):
    """Registro de auditoría: quién hizo qué y cuándo."""
    __tablename__ = "auditoria_logs"

    id          = db.Column(db.Integer,  primary_key=True)
    timestamp   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    usuario_id  = db.Column(db.Integer,  db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    username    = db.Column(db.String(80), nullable=True)
    accion      = db.Column(db.String(80), nullable=False, index=True)
    recurso     = db.Column(db.String(255), nullable=True)
    recurso_id  = db.Column(db.Integer,  nullable=True)
    resultado   = db.Column(db.String(20), nullable=False, default="exito")
    detalle     = db.Column(db.Text,       nullable=True)
    ip_origen   = db.Column(db.String(50), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "timestamp": self.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
            "username":  self.username or "—",
            "accion":    self.accion,
            "recurso":   self.recurso or "—",
            "recurso_id": self.recurso_id,
            "resultado": self.resultado,
            "detalle":   self.detalle or "",
            "ip_origen": self.ip_origen or "",
        }


class Servidor(db.Model):
    """Servidor Horizon o vCenter registrado."""
    __tablename__ = "servidores"

    id                     = db.Column(db.Integer, primary_key=True)
    nombre                 = db.Column(db.String(120), nullable=False)
    host                   = db.Column(db.String(255), nullable=False)
    tipo                   = db.Column(db.String(20),  nullable=False)   # "horizon" | "vcenter"
    tipo_maquina           = db.Column(db.String(20),  nullable=False, default="VDI")
    origen_id              = db.Column(db.Integer,     db.ForeignKey("origenes.id"), nullable=True)
    _origen_str            = db.Column("origen", db.String(20), nullable=False, default="")
    usuario                = db.Column(db.String(120), nullable=True, default="")
    password_enc           = db.Column(db.Text,        nullable=True, default="")
    encryption_key_version = db.Column(db.Integer,     nullable=False, default=1)
    dominio                = db.Column(db.String(120), nullable=False, default="")
    puerto                 = db.Column(db.Integer,     nullable=False, default=443)
    ssl_verify             = db.Column(db.Boolean,     nullable=False, default=False)
    activo                 = db.Column(db.Boolean,     nullable=False, default=True)
    ultimo_chequeo         = db.Column(db.DateTime,    nullable=True)
    created_by_id          = db.Column(db.Integer,     db.ForeignKey("usuarios.id"), nullable=True)
    created_at             = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    # Marcador explícito de "hasta cuándo ya se pidieron eventos/tareas reales de este
    # vCenter" (agregado 2026-09-07, ver core/vcenter_soap.py::obtener_eventos_tareas).
    # A propósito NO se infiere de MAX(VMTareaEvento.fecha): una sola VM con actividad
    # muy reciente adelantaría el cursor del SERVIDOR entero, tapando el backlog real de
    # el resto de sus VMs (confirmado con una extracción real: 1 VM con 217 eventos hizo
    # que pareciera que todo el servidor estaba al día). Se actualiza a la hora de arranque
    # de CADA fetch exitoso, sin importar si esa ventana trajo eventos o no.
    eventos_sync_hasta     = db.Column(db.DateTime,    nullable=True)
    updated_at             = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    origen_rel = db.relationship("Origen", foreign_keys=[origen_id], lazy="joined")
    snapshots  = db.relationship("InventarioSnapshot", backref="servidor", lazy=True, cascade="all, delete-orphan")
    maquinas   = db.relationship("Maquina", backref="servidor", lazy=True, cascade="all, delete-orphan")

    @property
    def origen(self) -> str:
        if self.origen_rel:
            return self.origen_rel.codigo
        return self._origen_str or ""

    @origen.setter
    def origen(self, value: str):
        self._origen_str = value or ""

    @property
    def password(self) -> str:
        if not self.password_enc:
            return ""
        if self.encryption_key_version >= 2:
            return _fernet_for(b"servidor-cred-v1").decrypt(self.password_enc.encode("ascii")).decode("utf-8")
        # encryption_key_version == 1: dato legacy en base64 plano (sin cifrar de verdad).
        # Se sigue pudiendo leer hasta correr scripts/migrate_encrypt_passwords.py.
        try:
            return base64.b64decode(self.password_enc).decode("utf-8")
        except Exception:
            return self.password_enc

    @password.setter
    def password(self, value: str):
        if not value:
            self.password_enc = ""
            self.encryption_key_version = 2
        else:
            self.password_enc = _fernet_for(b"servidor-cred-v1").encrypt(value.encode("utf-8")).decode("ascii")
            self.encryption_key_version = 2

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "nombre":       self.nombre,
            "host":         self.host,
            "tipo":         self.tipo if isinstance(self.tipo, str) else self.tipo.value,
            "tipo_maquina": self.tipo_maquina if isinstance(self.tipo_maquina, str) else self.tipo_maquina.value,
            "origen":       self.origen,
            "usuario":      self.usuario or "",
            "dominio":      self.dominio or "",
            "puerto":       self.puerto,
            "activo":       self.activo,
            "created_at":   self.created_at.isoformat() if self.created_at else "",
        }


class InventarioSnapshot(db.Model):
    """Cada ejecución de extracción de datos genera un snapshot."""
    __tablename__ = "inventario_snapshots"

    id                = db.Column(db.Integer,  primary_key=True)
    timestamp         = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    iniciado_en       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    finalizado_en     = db.Column(db.DateTime, nullable=True)
    duracion_segundos = db.Column(db.Float,    nullable=True)
    servidor_id       = db.Column(db.Integer,  db.ForeignKey("servidores.id"), nullable=False)
    disparado_por_id  = db.Column(db.Integer,  db.ForeignKey("usuarios.id"), nullable=True)
    tarea_id          = db.Column(db.String(100), nullable=True)
    total_vms         = db.Column(db.Integer,  nullable=False, default=0)
    total_vdi         = db.Column(db.Integer,  nullable=False, default=0)
    total_vm          = db.Column(db.Integer,  nullable=False, default=0)
    json_path         = db.Column(db.Text,     nullable=True)
    estado            = db.Column(db.String(20), nullable=False, default="completado")
    error_msg         = db.Column(db.Text,     nullable=True)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "timestamp":   self.timestamp.isoformat() if self.timestamp else "",
            "servidor_id": self.servidor_id,
            "total_vms":   self.total_vms,
            "total_vdi":   self.total_vdi,
            "total_vm":    self.total_vm,
            "estado":      self.estado if isinstance(self.estado, str) else self.estado.value,
            "duracion_segundos": self.duracion_segundos,
        }


class Maquina(db.Model):
    """
    Tabla de Estado Actual (1 fila por VM/VDI física).
    Se actualiza (UPDATE) en cada extracción en lugar de duplicarse.
    """
    __tablename__ = "maquinas"
    __table_args__ = (
        # Antes era (servidor_id, nombre) -- asumía nombre único por servidor. Bug real
        # encontrado 2026-08-12: vCenter MZ tiene VMs golden-image duplicadas de verdad
        # (mismo nombre, distinto MoRef -- ej. una master activa + una copia vieja apagada
        # que nadie borró). Con nombre como parte de la unicidad, las dos competían por la
        # MISMA fila y la que se procesaba último pisaba a la otra (a veces perdiendo el tag
        # MASTER). external_id (MoRef/GUID real) es la identidad real de la VM; nombre puede
        # repetirse. NULLs en external_id (VDI de Horizon aún sin merge de vCenter) no
        # colisionan entre sí -- SQLite trata cada NULL como distinto en un UNIQUE constraint.
        db.UniqueConstraint("servidor_id", "external_id", name="uq_maquina_servidor_external_id"),
    )

    id                   = db.Column(db.Integer, primary_key=True)
    servidor_id          = db.Column(db.Integer, db.ForeignKey("servidores.id"), nullable=False)
    ultimo_snapshot_id   = db.Column("snapshot_id", db.Integer, db.ForeignKey("inventario_snapshots.id"), nullable=True)

    nombre               = db.Column(db.String(255), nullable=False, index=True)
    tipo                 = db.Column(db.String(10),  nullable=False, default="VDI")

    origen_id            = db.Column(db.Integer, db.ForeignKey("origenes.id"), nullable=True)
    _origen_str          = db.Column("origen", db.String(20), nullable=False, default="")

    pool_id              = db.Column(db.Integer, db.ForeignKey("pools.id"), nullable=True)
    _pool_str            = db.Column("pool", db.String(255), nullable=True)

    empresa_id           = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=True)
    _empresa_str         = db.Column("empresa", db.String(120), nullable=True)

    datastore_id         = db.Column(db.Integer, db.ForeignKey("datastores.id"), nullable=True)

    usuario_asignado     = db.Column(db.String(255), nullable=True)
    # IP/nombre del cliente Horizon de la última sesión conocida.
    # Permite auditar el endpoint de conexión de cada sesión como evidencia directa.
    # No se limpia entre sesiones (última conocida, no "en vivo") -- ver DYNAMIC_LIVE_FIELDS en _save_or_update_maquina_impl.
    client_ip            = db.Column(db.String(50),  nullable=True)
    client_name           = db.Column(db.String(255), nullable=True)
    # Gateway/UAG real que atendió la última sesión (security_gateway_data de la API de
    # sesiones) -- más directo todavía que client_ip para diagnosticar problemas de
    # ruteo/balanceador entre sitios (confirmado en vivo 2026-08-13, mismo hallazgo que
    # motivó client_ip). gateway_location: "EXTERNAL"|"INTERNAL" según reporta Horizon.
    gateway_ip            = db.Column(db.String(50),  nullable=True)
    gateway_name           = db.Column(db.String(255), nullable=True)
    gateway_location       = db.Column(db.String(20),  nullable=True)
    # Client_data/protocolo de la última sesión Horizon (agregado 2026-09-07) -- mismo
    # objeto client_data ya confirmado en vivo 2026-08-13 (ver client_ip/client_name
    # arriba), solo faltaba leer 2 campos más que ya venían en la misma respuesta.
    # session_protocol/session_type no verificados contra un HAR real todavía -- lectura
    # defensiva (.get con variantes), quedan None si el nombre de campo no matchea.
    client_type           = db.Column(db.String(50),  nullable=True)   # WINDOWS/MAC/LINUX/HTML5/ANDROID/IOS (client_data.type)
    client_version        = db.Column(db.String(50),  nullable=True)   # Versión de Horizon Client
    session_protocol      = db.Column(db.String(20),  nullable=True)   # BLAST/PCOIP/RDP
    session_type          = db.Column(db.String(20),  nullable=True)   # DESKTOP/APPLICATION
    session_idle_seconds  = db.Column(db.Integer,     nullable=True)   # Tiempo inactivo de la sesión, si Horizon lo informa
    estado_horizon       = db.Column(db.String(50),  nullable=True)   # Estado sesión Horizon (CONNECTED, AVAILABLE...)
    estado_horizon_agente= db.Column(db.String(50),  nullable=True)   # Estado agente Horizon (OK, UNREACHABLE...)
    estado_vcenter       = db.Column(db.String(50),  nullable=True)   # Estado energía vCenter (PoweredOn, PoweredOff...)
    manager              = db.Column(db.String(255), nullable=True)
    agent_version        = db.Column(db.String(50),  nullable=True)
    tools_status         = db.Column(db.String(30),  nullable=True)   # VMware Tools run_state real (RUNNING/NOT_RUNNING/...)
    so                   = db.Column(db.String(255), nullable=True)
    cpu                  = db.Column(db.Integer,     nullable=True)
    ram_gb               = db.Column(db.Float,       nullable=True)
    disk_provisioned_gb  = db.Column("disk_gb", db.Float, nullable=True)
    disk_used_gb         = db.Column(db.Float,       nullable=True)
    dns                  = db.Column(db.String(255), nullable=True)
    ip_principal         = db.Column("ip", db.String(50), nullable=True)
    vcenter_host         = db.Column(db.String(255), nullable=True)
    external_id          = db.Column(db.String(255), nullable=True)   # MoRef:InstanceUuid (e.g. vm-55065:d14fa998-7e75...)
    folder               = db.Column(db.String(255), nullable=True)   # Carpeta vCenter
    # Ruta de cómputo real "Datacenter/Cluster/Host" (agregado 2026-09-07, ver
    # core/vcenter_soap.py::obtener_topologia_computo) -- vista "Cómputo" del Árbol
    # vCenter, alternativa a `folder` (vista "Carpetas"). Mismo criterio best-effort:
    # vacío si SOAP falló esa corrida, no bloquea el resto de la extracción.
    ruta_computo         = db.Column(db.String(500), nullable=True)
    resource_pool        = db.Column(db.String(255), nullable=True)   # Resource Pool vCenter
    datastores           = db.Column(db.String(500), nullable=True)   # Datastores vCenter
    hardware_version     = db.Column(db.String(50),  nullable=True)   # Versión Hardware vCenter
    # Topología de CPU/RAM y arranque (agregado 2026-09-07) -- ya vienen en la misma
    # llamada de detalle /api/vcenter/vm/{vm} que ya se consulta para disco/SO/HW version
    # (core/vcenter_rest.py), no es un fetch nuevo. Quedan None si el detalle falló para
    # esa VM, mismo criterio "sin valores inventados" del resto de columnas vCenter.
    cpu_cores_per_socket  = db.Column(db.Integer,     nullable=True)
    cpu_hot_add_enabled   = db.Column(db.Boolean,     nullable=True)
    memory_hot_add_enabled = db.Column(db.Boolean,    nullable=True)
    boot_firmware         = db.Column(db.String(20),  nullable=True)   # BIOS/EFI
    secure_boot_enabled   = db.Column(db.Boolean,     nullable=True)
    hardware_upgrade_status = db.Column(db.String(50), nullable=True)  # ej. pendingScheduled/none
    annotation           = db.Column(db.Text,        nullable=True)   # Anotación/Notas -- campo único editable+sincronizado con vCenter (unificado con el viejo `notas`, ver migración en init_db)
    connection_state     = db.Column(db.String(50),  nullable=True)   # Estado conexión vCenter
    cpu_usage_mhz        = db.Column(db.Integer,     nullable=True)   # Uso CPU (MHz)
    memory_usage_mb      = db.Column(db.Integer,     nullable=True)   # Uso RAM (MB)
    in_error_state       = db.Column(db.Boolean,     nullable=True, default=False)  # Estado de Error (Horizon)
    maintenance_mode     = db.Column(db.Boolean,     nullable=True, default=False)  # Modo Mantenimiento (Horizon)
    tipo_provisionamiento = db.Column(db.String(20), nullable=True, index=True)  # MASTER | TEMPLATE | VDI_POOL | VM_ESTATICA

    datos_extra_json     = db.Column(db.Text,     nullable=True)   # JSON con todas las propiedades extendidas del servidor
    activo               = db.Column(db.Boolean,  nullable=False, default=True)
    estado               = db.Column(db.String(100), nullable=True)   # estado operacional manual (e.g. Esperando contacto, Eliminar)
    fecha_ultimo_ingreso = db.Column(db.String(150), nullable=True)   # fecha o detalle de último ingreso manual
    primera_deteccion    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    snapshot    = db.relationship("InventarioSnapshot", backref=db.backref("maquinas_list", lazy=True), foreign_keys=[ultimo_snapshot_id])
    origen_rel  = db.relationship("Origen", foreign_keys=[origen_id], lazy="joined")
    pool_rel    = db.relationship("Pool", foreign_keys=[pool_id], lazy="joined")
    empresa_rel = db.relationship("Empresa", foreign_keys=[empresa_id], lazy="joined")
    ips         = db.relationship("MaquinaIP", backref="maquina", lazy=True, cascade="all, delete-orphan")
    historial   = db.relationship("MaquinaHistorial", backref="maquina", lazy=True, cascade="all, delete-orphan")
    usuarios_dir = db.relationship("MaquinaUsuarioDir", backref="maquina", lazy=True, cascade="all, delete-orphan")

    @property
    def snapshot_id(self) -> int | None:
        return self.ultimo_snapshot_id

    @snapshot_id.setter
    def snapshot_id(self, val: int | None):
        self.ultimo_snapshot_id = val

    @property
    def disk_gb(self) -> float | None:
        return self.disk_provisioned_gb

    @disk_gb.setter
    def disk_gb(self, val: float | None):
        self.disk_provisioned_gb = val

    @property
    def ip(self) -> str | None:
        return self.ip_principal

    @ip.setter
    def ip(self, val: str | None):
        self.ip_principal = val

    @property
    def origen(self) -> str:
        if self.origen_rel:
            return self.origen_rel.codigo
        return self._origen_str or ""

    @origen.setter
    def origen(self, val: str):
        self._origen_str = val or ""

    @property
    def pool(self) -> str:
        if self.pool_rel:
            return self.pool_rel.nombre
        return self._pool_str or ""

    @pool.setter
    def pool(self, val: str):
        self._pool_str = val or ""
        self.pool_id = None

    @property
    def persistencia(self) -> str:
        """Persistente/No Persistente segun Pool.user_assignment (Dedicated/Floating de
        Horizon). Solo aplica a VDI_POOL -- VM_ESTATICA es por definicion un equipo fijo
        (no aplica el concepto), MASTER/TEMPLATE tampoco son maquinas en uso real."""
        tp = self.tipo_provisionamiento or ""
        if tp == "VDI_POOL":
            ua = (self.pool_rel.user_assignment if self.pool_rel else None) or ""
            if ua.strip().lower() == "floating":
                return "No Persistente"
            return "Persistente"
        if tp == "VM_ESTATICA":
            return "N/A (Estática)"
        return ""

    @property
    def empresa(self) -> str:
        if self.empresa_rel:
            return self.empresa_rel.nombre
        return self._empresa_str or ""

    @empresa.setter
    def empresa(self, val: str):
        self._empresa_str = val or ""
        self.empresa_id = None

    def to_dict(self) -> dict:
        return {
            "id":                  self.id,
            "snapshot_id":         self.snapshot_id,
            "servidor_id":         self.servidor_id,
            "nombre":              self.nombre,
            "tipo":                self.tipo if isinstance(self.tipo, str) else self.tipo.value,
            "tipo_provisionamiento": self.tipo_provisionamiento or "",
            "persistencia":        self.persistencia,
            "origen":              self.origen,
            "pool":                self.pool,
            "empresa":             self.empresa,
            "usuario_asignado":    self.usuario_asignado or "",
            "client_ip":           self.client_ip or "",
            "client_name":         self.client_name or "",
            "gateway_ip":          self.gateway_ip or "",
            "gateway_name":        self.gateway_name or "",
            "gateway_location":    self.gateway_location or "",
            "client_type":         self.client_type or "",
            "client_version":      self.client_version or "",
            "session_protocol":    self.session_protocol or "",
            "session_type":        self.session_type or "",
            "session_idle_seconds": self.session_idle_seconds,
            "estado_horizon":      self.estado_horizon or "",
            "estado_horizon_agente": self.estado_horizon_agente or "",
            "estado_vcenter":      self.estado_vcenter or "",
            "manager":             self.manager or "",
            "agent_version":       self.agent_version or "",
            "tools_status":        self.tools_status or "",
            "so":                  self.so or "",
            "cpu":                 self.cpu,
            "ram_gb":              self.ram_gb,
            "disk_gb":             self.disk_provisioned_gb,
            "disk_provisioned_gb": self.disk_provisioned_gb,
            "disk_used_gb":        self.disk_used_gb,
            "dns":                 self.dns or "",
            "ip":                  self.ip_principal or "",
            "ip_principal":        self.ip_principal or "",
            "vcenter_host":        self.vcenter_host or "",
            "external_id":         self.external_id or "",
            "folder":              self.folder or "",
            "ruta_computo":        self.ruta_computo or "",
            "resource_pool":       self.resource_pool or "",
            "datastores":          self.datastores or "",
            "hardware_version":    self.hardware_version or "",
            "cpu_cores_per_socket": self.cpu_cores_per_socket,
            "cpu_hot_add_enabled": self.cpu_hot_add_enabled,
            "memory_hot_add_enabled": self.memory_hot_add_enabled,
            "boot_firmware":       self.boot_firmware or "",
            "secure_boot_enabled": self.secure_boot_enabled,
            "hardware_upgrade_status": self.hardware_upgrade_status or "",
            "annotation":          self.annotation or "",
            "connection_state":    self.connection_state or "",
            "cpu_usage_mhz":       self.cpu_usage_mhz,
            "memory_usage_mb":     self.memory_usage_mb,
            "in_error_state":      self.in_error_state or False,
            "maintenance_mode":    self.maintenance_mode or False,
            "activo":              self.activo,
            "estado":              self.estado or "",
            "fecha_ultimo_ingreso": self.fecha_ultimo_ingreso or "",
            "datos_extra": json.loads(self.datos_extra_json) if self.datos_extra_json else {},
        }


class MaquinaIP(db.Model):
    """IPs secundarias asociadas a una VM."""
    __tablename__ = "maquina_ips"

    id         = db.Column(db.Integer, primary_key=True)
    maquina_id = db.Column(db.Integer, db.ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=False)
    ip         = db.Column(db.String(50), nullable=False)
    tipo       = db.Column(db.String(20), nullable=False, default="ipv4")


class MaquinaHistorial(db.Model):
    """Delta de cambios por campo en cada máquina."""
    __tablename__ = "maquinas_historial"

    id               = db.Column(db.Integer, primary_key=True)
    maquina_id       = db.Column(db.Integer, db.ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_id      = db.Column(db.Integer, db.ForeignKey("inventario_snapshots.id"), nullable=True)
    campo_modificado = db.Column(db.String(50), nullable=False, index=True)
    valor_anterior   = db.Column(db.Text, nullable=True)
    valor_nuevo      = db.Column(db.Text, nullable=True)
    detectado_en     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class VMTareaEvento(db.Model):
    """
    Tareas y Eventos de la sección 'Supervisar' (Monitor) de vCenter por Máquina Virtual.
    """
    __tablename__ = "vm_tareas_eventos"

    id            = db.Column(db.Integer, primary_key=True)
    maquina_id    = db.Column(db.Integer, db.ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo          = db.Column(db.String(20), nullable=False, default="evento") # "task" o "evento"
    nombre_evento = db.Column(db.String(150), nullable=False, index=True)
    mensaje       = db.Column(db.Text, nullable=True)
    usuario       = db.Column(db.String(120), nullable=True)
    estado        = db.Column(db.String(50), nullable=True, default="info") # "info", "warning", "error", "success"
    fecha         = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "maquina_id": self.maquina_id,
            "tipo": self.tipo,
            "nombre_evento": self.nombre_evento,
            "mensaje": self.mensaje or "",
            "usuario": self.usuario or "vCenter",
            "estado": self.estado or "info",
            "fecha": self.fecha.strftime("%d/%m/%Y %H:%M:%S") if self.fecha else "",
        }


class MetricasRendimiento(db.Model):
    """Serie temporal de métricas en vivo CPU/RAM."""
    __tablename__ = "metricas_rendimiento"

    id         = db.Column(db.Integer, primary_key=True)
    maquina_id = db.Column(db.Integer, db.ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    cpu_pct    = db.Column(db.Float, nullable=True)
    ram_pct    = db.Column(db.Float, nullable=True)
    fuente     = db.Column(db.String(50), nullable=False, default="vcenter")


class HistorialUsuarioVDI(db.Model):
    """
    Historial funcional de rotación de usuarios por VDI/VM.
    """
    __tablename__ = "historial_usuario_vdi"

    id               = db.Column(db.Integer,  primary_key=True)
    nombre_vm        = db.Column(db.String(255), nullable=False, index=True)
    maquina_id       = db.Column(db.Integer,  db.ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=True)
    servidor_id      = db.Column(db.Integer,  db.ForeignKey("servidores.id"), nullable=True)
    pool_id          = db.Column(db.Integer,  db.ForeignKey("pools.id"), nullable=True)
    origen_id        = db.Column(db.Integer,  db.ForeignKey("origenes.id"), nullable=True)
    pool             = db.Column(db.String(255), nullable=True)
    origen           = db.Column(db.String(20),  nullable=True)
    tipo             = db.Column(db.String(10),  nullable=True)
    usuario_anterior = db.Column(db.String(255), nullable=True)
    usuario_nuevo    = db.Column(db.String(255), nullable=True)
    empresa_anterior = db.Column(db.String(120), nullable=True)
    empresa_nueva    = db.Column(db.String(120), nullable=True)
    estado_horizon   = db.Column(db.String(50),  nullable=True)
    detectado_en     = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, index=True)
    snapshot_id      = db.Column(db.Integer,  db.ForeignKey("inventario_snapshots.id"), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "nombre_vm":        self.nombre_vm,
            "pool":             self.pool or "",
            "origen":           self.origen or "",
            "tipo":             self.tipo or "",
            "usuario_anterior": self.usuario_anterior or "—",
            "usuario_nuevo":    self.usuario_nuevo or "—",
            "empresa_anterior": self.empresa_anterior or "",
            "empresa_nueva":    self.empresa_nueva or "",
            "estado_horizon":   self.estado_horizon or "",
            "detectado_en":     self.detectado_en.strftime("%d/%m/%Y %H:%M") if self.detectado_en else "",
        }


class CorreccionManual(db.Model):
    """Correcciones manuales persistentes por atributo."""
    __tablename__ = "correcciones_manuales"

    id               = db.Column(db.Integer,     primary_key=True)
    nombre_vm        = db.Column(db.String(255), nullable=False, index=True)
    maquina_id       = db.Column(db.Integer,     db.ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=True)
    campo            = db.Column(db.String(50),  nullable=True)
    valor_corregido  = db.Column(db.Text,        nullable=True)
    motivo           = db.Column(db.Text,        nullable=True)
    corregido_por_id = db.Column(db.Integer,     db.ForeignKey("usuarios.id"), nullable=True)
    activo           = db.Column(db.Boolean,     nullable=False, default=True)

    dns              = db.Column(db.String(255), nullable=True)
    pool             = db.Column(db.String(255), nullable=True)
    usuario_asignado = db.Column(db.String(255), nullable=True)
    empresa          = db.Column(db.String(120), nullable=True)
    estado_horizon   = db.Column(db.String(50),  nullable=True)
    manager          = db.Column(db.String(255), nullable=True)
    agent_version    = db.Column(db.String(50),  nullable=True)
    so               = db.Column(db.String(255), nullable=True)
    tipo             = db.Column(db.String(10),  nullable=True)
    notas            = db.Column(db.Text,        nullable=True)

    created_at       = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "nombre_vm":        self.nombre_vm,
            "dns":              self.dns or "",
            "pool":             self.pool or "",
            "usuario_asignado": self.usuario_asignado or "",
            "empresa":          self.empresa or "",
            "estado_horizon":   self.estado_horizon or "",
            "manager":          self.manager or "",
            "agent_version":    self.agent_version or "",
            "so":               self.so or "",
            "tipo":             self.tipo or "",
            "notas":            self.notas or "",
        }


# ── Nuevas Tablas de Infraestructura y Gestión ─────────────────────────


class HorizonUsuarioSid(db.Model):
    """
    Cache persistente SID de AD -> nombre de usuario resuelto.
    La API REST de Horizon (Connection Server actual) solo informa el SID del
    usuario asignado en sessions/machines, no el nombre — hay que resolverlo
    aparte vía /rest/external/v1/ad-users-or-groups/{sid}, una llamada por SID.
    Cachear acá evita repetir esa llamada en cada corrida del scheduler para
    usuarios ya resueltos (la asignación de VDI a un usuario casi no cambia).
    """
    __tablename__ = "horizon_usuarios_sid"

    sid          = db.Column(db.String(184), primary_key=True)
    nombre       = db.Column(db.String(255), nullable=True)
    resuelto_en  = db.Column(db.DateTime, default=datetime.utcnow)


class DirectorioUsuario(db.Model):
    """
    Directorio de usuarios corporativos/AD que pueden ser asignados a VMs.
    Independiente de la tabla Usuario (que es para acceso a la app web).
    """
    __tablename__ = "directorio_usuarios"

    id               = db.Column(db.Integer,     primary_key=True)
    username         = db.Column(db.String(120), unique=True, nullable=False, index=True)  # sam o UPN
    # AD real a veces tiene el "User logon name" (UPN moderno, lo que suele reportar
    # Horizon en usuario_asignado -> termina en `username`) y el "User logon name
    # (pre-Windows 2000)" (sAMAccountName) como STRINGS DISTINTOS, no solo formato
    # distinto -- inconsistencia real de datos en el AD del cliente, no se puede
    # corregir del lado AD. Se guarda el sam por separado (poblado por Verificar AD,
    # ver core/ad_client.py) para poder matchear contra App Volumes sea cual sea la
    # forma que use cada sistema.
    sam_account_name = db.Column(db.String(120), nullable=True, index=True)
    nombre_completo  = db.Column(db.String(200), nullable=True)
    email            = db.Column(db.String(200), nullable=True)
    departamento     = db.Column(db.String(150), nullable=True)
    empresa          = db.Column(db.String(150), nullable=True)
    telefono         = db.Column(db.String(50),  nullable=True)
    activo_ad        = db.Column(db.Boolean,     nullable=False, default=True)  # si existe en AD
    notas            = db.Column(db.Text,        nullable=True)   # e.g. "Usuario desvinculado 2025-06"
    created_at       = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # M:M con máquinas
    asignaciones = db.relationship("MaquinaUsuarioDir", backref="usuario_dir", lazy=True, cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "username":        self.username,
            "sam_account_name": self.sam_account_name or "",
            "nombre_completo": self.nombre_completo or "",
            "email":           self.email or "",
            "departamento":    self.departamento or "",
            "empresa":         self.empresa or "",
            "telefono":        self.telefono or "",
            "activo_ad":       self.activo_ad,
            "notas":           self.notas or "",
            "created_at":      self.created_at.isoformat() if self.created_at else "",
        }


class MaquinaUsuarioDir(db.Model):
    """
    Relación M:M entre Maquina y DirectorioUsuario.
    Permite vincular múltiples usuarios a una VM y ver todas las VMs de un usuario.
    """
    __tablename__ = "maquina_usuarios_dir"
    __table_args__ = (
        db.UniqueConstraint("maquina_id", "directorio_usuario_id", name="uq_maquina_usuario_dir"),
    )

    id                   = db.Column(db.Integer, primary_key=True)
    maquina_id           = db.Column(db.Integer, db.ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=False)
    directorio_usuario_id= db.Column(db.Integer, db.ForeignKey("directorio_usuarios.id", ondelete="CASCADE"), nullable=False)
    tipo                 = db.Column(db.String(20), nullable=False, default="principal")  # principal | secundario
    notas                = db.Column(db.Text,    nullable=True)  # e.g. "Asignado mientras regresa de licencia"
    activo               = db.Column(db.Boolean, nullable=False, default=True)
    created_at           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id":                   self.id,
            "maquina_id":           self.maquina_id,
            "directorio_usuario_id":self.directorio_usuario_id,
            "tipo":                 self.tipo,
            "notas":                self.notas or "",
            "activo":               self.activo,
        }


# ── App Volumes: paquetes, programas instalados y asignaciones ────────
#
# Modelo de datos de Omnissa App Volumes Manager (REST API 2412):
#   Application (app_products) 1--N Package (app_packages) 1--N Program (programs)
#   Application/Package --N:M-- Assignment -- Entity (User/Group/Computer/OU)
# El assignment es ESTATICO (a quién le corresponde el AppStack) y no referencia
# una VM concreta en pools flotantes -- el "adjuntado a tal VM" es un evento en
# vivo (activity_logs, tabla AppVolumesActividad) que solo existe mientras dura
# la sesión. Para saber "qué apps tiene esta VM ahora" hay que cruzar en runtime
# Maquina.usuario_asignado (ya viene de la sesión Horizon activa) contra
# AppVolumesAsignacion.entity_name/entity_upn (entity_type=User) o expandir
# grupo AD, o directo contra Maquina.nombre cuando entity_type=Computer.

class AppVolumesAplicacion(db.Model):
    """Application (app_products) de App Volumes Manager."""
    __tablename__ = "appvolumes_aplicaciones"
    __table_args__ = (
        db.UniqueConstraint("servidor_id", "av_id", name="uq_appvol_app_servidor_avid"),
    )

    id                = db.Column(db.Integer, primary_key=True)
    servidor_id       = db.Column(db.Integer, db.ForeignKey("servidores.id", ondelete="CASCADE"), nullable=False, index=True)
    av_id             = db.Column(db.Integer, nullable=False)  # id remoto en App Volumes Manager (app_products.id)
    guid              = db.Column(db.String(64), nullable=True, index=True)
    nombre            = db.Column(db.String(255), nullable=False, index=True)
    descripcion       = db.Column(db.Text, nullable=True)
    assignment_count  = db.Column(db.Integer, nullable=False, default=0)
    activo            = db.Column(db.Boolean, nullable=False, default=True)  # sigue existiendo en la última sincronización
    created_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    paquetes = db.relationship("AppVolumesPaquete", backref="aplicacion", lazy=True, cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "av_id": self.av_id, "guid": self.guid or "",
            "nombre": self.nombre, "descripcion": self.descripcion or "",
            "assignment_count": self.assignment_count, "activo": self.activo,
        }


class AppVolumesPaquete(db.Model):
    """Package (app_packages / AppStack) de una Application de App Volumes."""
    __tablename__ = "appvolumes_paquetes"
    __table_args__ = (
        db.UniqueConstraint("servidor_id", "av_id", name="uq_appvol_pkg_servidor_avid"),
    )

    id                = db.Column(db.Integer, primary_key=True)
    servidor_id       = db.Column(db.Integer, db.ForeignKey("servidores.id", ondelete="CASCADE"), nullable=False, index=True)
    aplicacion_id     = db.Column(db.Integer, db.ForeignKey("appvolumes_aplicaciones.id", ondelete="CASCADE"), nullable=True, index=True)
    av_id             = db.Column(db.Integer, nullable=False)  # id remoto (app_packages.id)
    guid              = db.Column(db.String(64), nullable=True, index=True)
    nombre            = db.Column(db.String(255), nullable=False, index=True)
    version           = db.Column(db.String(50), nullable=True)
    lifecycle_stage   = db.Column(db.String(30), nullable=True)   # New | Tested | Published | Retired
    delivery          = db.Column(db.String(20), nullable=True)   # classic | on_demand
    status            = db.Column(db.String(20), nullable=True)   # enabled | disabled
    attachment_count  = db.Column(db.Integer, nullable=False, default=0)  # cuántas VMs lo tienen montado ahora
    size_mb           = db.Column(db.Float, nullable=True)
    datastore_name    = db.Column(db.String(255), nullable=True)
    activo            = db.Column(db.Boolean, nullable=False, default=True)
    created_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    programas = db.relationship("AppVolumesPrograma", backref="paquete", lazy=True, cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "av_id": self.av_id, "guid": self.guid or "",
            "aplicacion_id": self.aplicacion_id, "nombre": self.nombre,
            "version": self.version or "", "lifecycle_stage": self.lifecycle_stage or "",
            "delivery": self.delivery or "", "status": self.status or "",
            "attachment_count": self.attachment_count, "size_mb": self.size_mb,
            "datastore_name": self.datastore_name or "",
        }


class AppVolumesPrograma(db.Model):
    """
    Programa/software real instalado dentro de un Package (GET .../app_packages/{id}/programs).
    Esta es la respuesta concreta a "qué software está instalado" para todo lo entregado
    vía App Volumes -- no cubre software que viene en la imagen base ni instalado a mano.
    """
    __tablename__ = "appvolumes_programas"

    id                = db.Column(db.Integer, primary_key=True)
    paquete_id        = db.Column(db.Integer, db.ForeignKey("appvolumes_paquetes.id", ondelete="CASCADE"), nullable=False, index=True)
    av_id             = db.Column(db.Integer, nullable=True)   # id remoto del programa, si el package no cambió puede repetirse
    nombre            = db.Column(db.String(255), nullable=False, index=True)
    publisher         = db.Column(db.String(255), nullable=True)
    install_location  = db.Column(db.String(500), nullable=True)
    version           = db.Column(db.String(100), nullable=True)
    created_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "nombre": self.nombre, "publisher": self.publisher or "",
            "install_location": self.install_location or "", "version": self.version or "",
        }


class AppVolumesAsignacion(db.Model):
    """
    Assignment (app_assignments) de App Volumes: a qué entidad de AD (User, Group,
    Computer u OU) le corresponde una Application/Package. Es la parte ESTATICA del
    link -- no dice en qué VM está montado ahora mismo (ver AppVolumesActividad).
    """
    __tablename__ = "appvolumes_asignaciones"
    __table_args__ = (
        # Una assignment (av_id) puede resolver a varias entidades (ej. dos grupos AD
        # distintos asignados al mismo app_product) -- el av_id remoto solo identifica la
        # fila de assignment en App Volumes, no cada entidad dentro de ella.
        db.UniqueConstraint("servidor_id", "av_id", "entity_type", "entity_name",
                             name="uq_appvol_asig_servidor_avid_entidad"),
    )

    id                       = db.Column(db.Integer, primary_key=True)
    servidor_id              = db.Column(db.Integer, db.ForeignKey("servidores.id", ondelete="CASCADE"), nullable=False, index=True)
    aplicacion_id            = db.Column(db.Integer, db.ForeignKey("appvolumes_aplicaciones.id", ondelete="CASCADE"), nullable=True, index=True)
    paquete_id               = db.Column(db.Integer, db.ForeignKey("appvolumes_paquetes.id", ondelete="SET NULL"), nullable=True, index=True)
    av_id                    = db.Column(db.Integer, nullable=False)  # id remoto (app_assignments.id)
    entity_type              = db.Column(db.String(20), nullable=False, index=True)  # User | Group | Computer | OrganizationalUnit
    entity_name              = db.Column(db.String(255), nullable=False, index=True)
    entity_upn               = db.Column(db.String(255), nullable=True, index=True)
    entity_dn                = db.Column(db.Text, nullable=True)
    filtro_prefijo_computadora= db.Column(db.String(100), nullable=True)  # ComputerPrefixFilter, si lo hay
    delivery                 = db.Column(db.String(20), nullable=True)   # default | on_trigger
    activo                   = db.Column(db.Boolean, nullable=False, default=True)
    created_at               = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at               = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "av_id": self.av_id,
            "aplicacion_id": self.aplicacion_id, "paquete_id": self.paquete_id,
            "entity_type": self.entity_type, "entity_name": self.entity_name,
            "entity_upn": self.entity_upn or "", "delivery": self.delivery or "",
            "filtro_prefijo_computadora": self.filtro_prefijo_computadora or "",
        }


class AppVolumesActividad(db.Model):
    """
    Espejo de activity_logs de App Volumes Manager: logins, power-ups y, sobre todo,
    "Attach"/"Assign" de volúmenes -- es la ÚNICA fuente con el link real en vivo
    VM + usuario + AppStack (mientras la sesión dura). Se importa incremental por
    event_time/av_id para no repetir filas ya vistas.
    """
    __tablename__ = "appvolumes_actividad"
    __table_args__ = (
        db.UniqueConstraint("servidor_id", "av_id", name="uq_appvol_act_servidor_avid"),
    )

    id              = db.Column(db.Integer, primary_key=True)
    servidor_id     = db.Column(db.Integer, db.ForeignKey("servidores.id", ondelete="CASCADE"), nullable=False, index=True)
    av_id           = db.Column(db.Integer, nullable=False)  # id remoto (activity_logs.id)
    source_type     = db.Column(db.String(30), nullable=True)   # User | Machine | Snapvol | ...
    source_name     = db.Column(db.String(255), nullable=True, index=True)
    target_type     = db.Column(db.String(30), nullable=True)
    target_name     = db.Column(db.String(255), nullable=True, index=True)
    accion          = db.Column(db.String(50), nullable=True, index=True)  # Assign | Attach | Login | ...
    resultado       = db.Column(db.String(20), nullable=True)   # Success | Failure | ...
    event_time      = db.Column(db.DateTime, nullable=True, index=True)
    admin_user_name = db.Column(db.String(255), nullable=True)
    importado_en    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source_type": self.source_type or "", "source_name": self.source_name or "",
            "target_type": self.target_type or "", "target_name": self.target_name or "",
            "accion": self.accion or "", "resultado": self.resultado or "",
            "event_time": self.event_time.isoformat() if self.event_time else "",
        }


class AppVolumesWritable(db.Model):
    """
    Writable Volume de App Volumes Manager (GET /app_volumes/writables) -- a diferencia
    del AppStack (AppVolumesPaquete: solo-lectura, 1 imagen compartida por muchas VMs),
    un Writable es un disco propio por usuario (perfil + datos) que persiste entre
    sesiones. Es común que un usuario acumule más de uno sin que nadie lo note -- un
    perfil viejo que quedó huérfano sin desasignar, o varios volúmenes de datos --
    inflando el disco real de la VM más de lo que se ve a simple vista en el ficha
    (pedido 2026-08-13: cruzar esto contra las alertas de disco).

    NOTA: escrito contra la documentación oficial de Omnissa App Volumes API (release
    2412), todavía sin poder validarlo contra un servidor real (la sesión de prueba dio
    "Unable to contact ActiveDirectory" del lado del App Volumes Manager, no nuestro).
    Igual que el resto de core/appvolumes_rest.py: validar con cuidado el primer log real.
    """
    __tablename__ = "appvolumes_writables"
    __table_args__ = (
        db.UniqueConstraint("servidor_id", "av_id", name="uq_appvol_writable_servidor_avid"),
    )

    id              = db.Column(db.Integer, primary_key=True)
    servidor_id     = db.Column(db.Integer, db.ForeignKey("servidores.id", ondelete="CASCADE"), nullable=False, index=True)
    av_id           = db.Column(db.Integer, nullable=False)  # id remoto (writables.id)
    guid            = db.Column(db.String(64), nullable=True, index=True)
    nombre          = db.Column(db.String(255), nullable=False, index=True)
    tipo            = db.Column(db.String(30), nullable=True)    # profile | writable | ...
    entity_type     = db.Column(db.String(20), nullable=True)    # User | Computer
    # entity_name = username LIMPIO (ej. "jdoe", de owner_upn "CORP\\jdoe") -- para
    # matchear contra Maquina.usuario_asignado, mismo criterio que AppVolumesAsignacion en
    # todo el resto del código. owner_display_name = nombre humano ("John Doe") solo
    # para mostrar en la ficha, nunca para matchear.
    entity_name         = db.Column(db.String(255), nullable=True, index=True)
    owner_display_name  = db.Column(db.String(255), nullable=True)
    estado          = db.Column(db.String(30), nullable=True)    # enabled | disabled | orphaned | ...
    attached_to     = db.Column(db.String(255), nullable=True, index=True)  # VM donde está montado AHORA, si aplica
    size_mb         = db.Column(db.Float, nullable=True)  # tamaño provisionado del VMDK
    used_mb         = db.Column(db.Float, nullable=True)  # espacio usado real dentro del volumen (si la API lo expone)
    datastore_name  = db.Column(db.String(255), nullable=True)
    # Metadatos reales del Writable en App Volumes Manager (agregado 2026-09-07) -- el
    # endpoint /app_volumes/writables procesaba 11 campos y descartaba estos 3. Nombres
    # distintos de created_at/updated_at de abajo a propósito: esos son bookkeeping de
    # NUESTRA sincronización, provisioned_at es la fecha real de aprovisionamiento del
    # VMDK que informa el servidor remoto.
    provisioned_at  = db.Column(db.DateTime, nullable=True)
    owner_email     = db.Column(db.String(255), nullable=True)
    storage_group   = db.Column(db.String(255), nullable=True)
    activo          = db.Column(db.Boolean, nullable=False, default=True)  # sigue existiendo en la última sincronización
    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "av_id": self.av_id, "nombre": self.nombre, "tipo": self.tipo or "",
            "entity_type": self.entity_type or "", "entity_name": self.entity_name or "",
            "owner_display_name": self.owner_display_name or self.entity_name or "",
            "estado": self.estado or "", "attached_to": self.attached_to or "",
            "size_gb": round(self.size_mb / 1024, 2) if self.size_mb else None,
            "used_gb": round(self.used_mb / 1024, 2) if self.used_mb else None,
            "datastore_name": self.datastore_name or "",
            "provisioned_at": self.provisioned_at.isoformat() if self.provisioned_at else None,
            "owner_email": self.owner_email or "",
            "storage_group": self.storage_group or "",
        }


class TareaExtraccion(db.Model):
    """Registro histórico de trabajos de extracción en background (threading.Thread)."""
    __tablename__ = "tareas_extraccion"

    id                = db.Column(db.Integer, primary_key=True)
    job_id            = db.Column(db.String(100), unique=True, nullable=False, index=True)
    estado            = db.Column(db.String(20), nullable=False, default="en_progreso")
    servidores_json   = db.Column(db.Text, nullable=True)
    iniciado_en       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    finalizado_en     = db.Column(db.DateTime, nullable=True)
    duracion_segundos = db.Column(db.Float, nullable=True)
    creado_por_id     = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)


class Configuracion(db.Model):
    """Ajustes del sistema clave-valor."""
    __tablename__ = "configuracion"

    id          = db.Column(db.Integer, primary_key=True)
    clave       = db.Column(db.String(100), unique=True, nullable=False, index=True)
    valor       = db.Column(db.Text, nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    updated_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SesionCredencialTemp(db.Model):
    """
    Bóveda de Credenciales Temporales Encriptadas:
    Almacena de forma segura en la base de datos la contraseña de infraestructura encriptada
    vinculada al usuario autenticado, expirando automáticamente tras 30 minutos.
    Evita guardar contraseñas en sessionStorage de navegador o cookies de cliente.
    """
    __tablename__ = "sesiones_credenciales_temp"

    id               = db.Column(db.Integer, primary_key=True)
    usuario_id       = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    clave_encriptada = db.Column(db.Text, nullable=False)
    expira_en        = db.Column(db.DateTime, nullable=False, index=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


import base64, hashlib
from datetime import timedelta


def _fernet_master_key() -> bytes:
    """Clave maestra Fernet desde el entorno. Sin fallback débil: si falta, se corta acá."""
    raw = os.environ.get("FERNET_KEY")
    if not raw:
        raise RuntimeError(
            "FERNET_KEY no configurada. Definila en .env (ver .env.example) — "
            "sin esta clave no se pueden cifrar ni leer credenciales."
        )
    return raw.encode("utf-8")


def _fernet_for(salt: bytes):
    """Fernet derivado de FERNET_KEY + salt (PBKDF2), para aislar cada uso (servidor vs sesión de usuario)."""
    from cryptography.fernet import Fernet
    digest = hashlib.pbkdf2_hmac("sha256", _fernet_master_key(), salt, 100_000, 32)
    return Fernet(base64.urlsafe_b64encode(digest))


def _get_encryption_key(usuario_id: int) -> bytes:
    digest = hashlib.pbkdf2_hmac("sha256", _fernet_master_key(), f"vdi-salt-{usuario_id}".encode("utf-8"), 100_000, 32)
    return base64.urlsafe_b64encode(digest)


def guardar_credencial_encriptada(usuario_id: int, password: str, ttl_seconds: int = 1800):
    if not usuario_id or not password:
        return
    from cryptography.fernet import Fernet
    f = Fernet(_get_encryption_key(usuario_id))
    encrypted = f.encrypt(password.encode("utf-8")).decode("ascii")

    expira = datetime.utcnow() + timedelta(seconds=ttl_seconds)
    row = SesionCredencialTemp.query.filter_by(usuario_id=usuario_id).first()
    if not row:
        row = SesionCredencialTemp(usuario_id=usuario_id, clave_encriptada=encrypted, expira_en=expira)
        db.session.add(row)
    else:
        row.clave_encriptada = encrypted
        row.expira_en = expira

    db.session.commit()

def obtener_credencial_desencriptada(usuario_id: int) -> str | None:
    if not usuario_id:
        return None
    row = SesionCredencialTemp.query.filter_by(usuario_id=usuario_id).first()
    if not row:
        return None

    if row.expira_en < datetime.utcnow():
        db.session.delete(row)
        db.session.commit()
        return None

    from cryptography.fernet import Fernet
    f = Fernet(_get_encryption_key(usuario_id))
    try:
        return f.decrypt(row.clave_encriptada.encode("ascii")).decode("utf-8")
    except Exception:
        # Token corrupto/vencido para Fernet (no confundir con clave faltante, eso ya explota antes) o
        # residuo del viejo esquema XOR pre-migración: se descarta, el usuario re-ingresa su clave.
        db.session.delete(row)
        db.session.commit()
        return None

def purgar_credenciales_usuario(usuario_id: int):
    if not usuario_id:
        return
    SesionCredencialTemp.query.filter_by(usuario_id=usuario_id).delete()
    db.session.commit()


# ── Helpers ──────────────────────────────────────────────────────────

# NOTA: Si la ruta resuelta cae en una unidad de red (ej. perfil VDI redirigido),
# SQLite WAL no sera confiable (posibles bloqueos 'database is locked').
# En ese escenario, setear INVENTARIO_DB_PATH apuntando a un disco local.
def get_db_path() -> str:
    # Override para tests (ver tests/conftest.py) — nunca corren contra data/inventario.db real.
    override = os.environ.get("INVENTARIO_DB_PATH")
    if override:
        return override
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "inventario.db")


def init_db(app):
    """Inicializa la DB, crea tablas y realiza seed inicial de catálogos y admin."""
    with app.app_context():
        # Migración one-shot: "datastores" existía con nombre UNIQUE global, lo que
        # rompe con 4 vCenters que pueden repetir nombre de datastore (ej.
        # "vsanDatastore" es el default de vSAN por cluster). La tabla nunca se pobló
        # (no estaba conectada a nada hasta ahora) — recrearla es seguro solo si
        # sigue vacía; si por algún motivo ya tiene filas, no se toca.
        try:
            with db.engine.connect() as conn:
                existe = conn.execute(db.text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='datastores'"
                )).fetchone()
                if existe:
                    total = conn.execute(db.text("SELECT COUNT(*) FROM datastores")).scalar()
                    if total == 0:
                        conn.execute(db.text("DROP TABLE datastores"))
                        conn.commit()
        except Exception:
            pass

        db.create_all()
        # Auto-migración para columnas recién agregadas en SQLite
        new_cols = [
            ("external_id", "VARCHAR(255)"),
            ("folder", "VARCHAR(255)"),
            ("resource_pool", "VARCHAR(255)"),
            ("datastores", "VARCHAR(500)"),
            ("hardware_version", "VARCHAR(50)"),
            ("annotation", "TEXT"),
            ("connection_state", "VARCHAR(50)"),
            ("cpu_usage_mhz", "INTEGER"),
            ("memory_usage_mb", "INTEGER"),
            ("in_error_state", "BOOLEAN DEFAULT 0"),
            ("maintenance_mode", "BOOLEAN DEFAULT 0"),
            ("tipo_provisionamiento", "VARCHAR(20)"),
            ("tools_status", "VARCHAR(30)"),
            ("client_ip", "VARCHAR(50)"),
            ("client_name", "VARCHAR(255)"),
            ("gateway_ip", "VARCHAR(50)"),
            ("gateway_name", "VARCHAR(255)"),
            ("gateway_location", "VARCHAR(20)"),
            ("client_type", "VARCHAR(50)"),
            ("client_version", "VARCHAR(50)"),
            ("session_protocol", "VARCHAR(20)"),
            ("session_type", "VARCHAR(20)"),
            ("session_idle_seconds", "INTEGER"),
            ("cpu_cores_per_socket", "INTEGER"),
            ("cpu_hot_add_enabled", "BOOLEAN"),
            ("memory_hot_add_enabled", "BOOLEAN"),
            ("boot_firmware", "VARCHAR(20)"),
            ("secure_boot_enabled", "BOOLEAN"),
            ("hardware_upgrade_status", "VARCHAR(50)"),
            ("ruta_computo", "VARCHAR(500)"),
        ]
        with db.engine.connect() as conn:
            for col_name, col_type in new_cols:
                try:
                    conn.execute(db.text(f"ALTER TABLE maquinas ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception:
                    pass  # Columna ya existente

            # Migración one-shot: `notas` (campo manual viejo) y `annotation` (Notes real
            # de vCenter) se unificaron en un solo campo -- `notas` se sacó del modelo,
            # pero la columna física sigue en la tabla (nunca se hace DROP COLUMN acá,
            # mismo criterio que el resto de este bloque). Se copia cualquier valor viejo
            # de `notas` a `annotation` solo si `annotation` todavía está vacío, para no
            # pisar una anotación real de vCenter ya sincronizada.
            try:
                conn.execute(db.text(
                    "UPDATE maquinas SET annotation = notas "
                    "WHERE (annotation IS NULL OR annotation = '') "
                    "AND notas IS NOT NULL AND notas != ''"
                ))
                conn.commit()
            except Exception:
                pass  # Columna `notas` ya no existe (DB nueva) o ya migrada

            pool_cols = [
                ("display_name", "VARCHAR(255)"),
                ("tipo", "VARCHAR(50) DEFAULT 'Automated'"),
                ("user_assignment", "VARCHAR(50) DEFAULT 'Dedicated'"),
                ("enabled", "BOOLEAN DEFAULT 1"),
                ("origen", "VARCHAR(20)"),
                ("provisioning_error", "TEXT"),
                ("activo", "BOOLEAN DEFAULT 1"),
                ("master_vm_actual", "VARCHAR(255)"),
                ("master_moref", "VARCHAR(50)"),
                ("snapshot_actual", "TEXT"),
                ("imagen_actualizada_en", "DATETIME"),
                ("farm_id", "INTEGER"),
            ]
            for col_name, col_type in pool_cols:
                try:
                    conn.execute(db.text(f"ALTER TABLE pools ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception:
                    pass

            try:
                conn.execute(db.text("ALTER TABLE appvolumes_writables ADD COLUMN owner_display_name VARCHAR(255)"))
                conn.commit()
            except Exception:
                pass

            for col_name, col_type in (
                ("provisioned_at", "DATETIME"),
                ("owner_email", "VARCHAR(255)"),
                ("storage_group", "VARCHAR(255)"),
            ):
                try:
                    conn.execute(db.text(f"ALTER TABLE appvolumes_writables ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception:
                    pass

            try:
                conn.execute(db.text("ALTER TABLE servidores ADD COLUMN eventos_sync_hasta DATETIME"))
                conn.commit()
            except Exception:
                pass

            try:
                conn.execute(db.text("ALTER TABLE usuarios ADD COLUMN filter_presets TEXT"))
                conn.commit()
            except Exception:
                pass

            try:
                conn.execute(db.text("ALTER TABLE directorio_usuarios ADD COLUMN sam_account_name VARCHAR(120)"))
                conn.commit()
            except Exception:
                pass

            try:
                conn.execute(db.text("ALTER TABLE usuarios ADD COLUMN inventario_columnas TEXT"))
                conn.commit()
            except Exception:
                pass

            datastore_cols = [
                ("servidor_id", "INTEGER"),
                ("espacio_libre_gb", "FLOAT"),
                ("activo", "BOOLEAN DEFAULT 1"),
            ]
            for col_name, col_type in datastore_cols:
                try:
                    conn.execute(db.text(f"ALTER TABLE datastores ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception:
                    pass

            # Crear índices compuestos para aceleración de consultas
            indices = [
                ("idx_maquina_historial_composite", "CREATE INDEX IF NOT EXISTS idx_maquina_historial_composite ON maquina_historial (maquina_id, detectado_en)"),
                ("idx_maquinas_composite", "CREATE INDEX IF NOT EXISTS idx_maquinas_composite ON maquinas (servidor_id, activo, nombre)"),
                ("idx_vm_tarea_evento_composite", "CREATE INDEX IF NOT EXISTS idx_vm_tarea_evento_composite ON vm_tarea_eventos (maquina_id, fecha)"),
            ]
            for idx_name, idx_sql in indices:
                try:
                    conn.execute(db.text(idx_sql))
                    conn.commit()
                except Exception:
                    pass

        # Fusionar duplicados case-insensitive existentes (ej. "corp" / "CORP") ANTES de
        # crear los índices únicos NOCASE de abajo — si quedan duplicados, el CREATE UNIQUE
        # INDEX falla en silencio y el índice nunca se crea.
        _fusionar_duplicados_case_insensitive()

        with db.engine.connect() as conn:
            # Índices únicos case-insensitive: cierran la condición de carrera entre servidores
            # procesados en paralelo durante la extracción (dos hilos podían crear "Empresa X" y
            # "empresa x" al mismo tiempo porque el UNIQUE por defecto de SQLite es case-sensitive).
            nocase_indices = [
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_empresas_nombre_nocase ON empresas (nombre COLLATE NOCASE)",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_pools_nombre_nocase ON pools (nombre COLLATE NOCASE)",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_directorio_usuarios_username_nocase ON directorio_usuarios (username COLLATE NOCASE)",
            ]
            for idx_sql in nocase_indices:
                try:
                    conn.execute(db.text(idx_sql))
                    conn.commit()
                except Exception:
                    pass

        seed_catalogos()
        _seed_admin()


def _fusionar_duplicados_case_insensitive():
    """Fusiona filas de Empresa/Pool/DirectorioUsuario que solo difieren en mayúsculas/minúsculas
    (quedaban duplicadas por una condición de carrera entre servidores extraídos en paralelo, o por
    _get_or_create_* comparando con `=` exacto antes de este fix). Conserva la fila de menor id."""
    from sqlalchemy import func as _func

    def _fusionar(model, campo, repoints: list[tuple]):
        """repoints: lista de (tabla_fk, columna_fk, columna_conflicto_o_None).
        Si columna_conflicto es None, repoint simple (FK sin restricción compuesta).
        Si no, repoint fila por fila y borra en vez de repointear cuando el destino
        ya tiene una fila con esa combinación (ej. UniqueConstraint maquina+usuario)."""
        vistos: dict[str, object] = {}
        for row in model.query.order_by(model.id.asc()).all():
            valor = (getattr(row, campo) or "").strip().lower()
            if not valor:
                continue
            if valor not in vistos:
                vistos[valor] = row
                continue
            principal = vistos[valor]
            for tabla_fk, columna_fk, columna_conflicto in repoints:
                if columna_conflicto is None:
                    tabla_fk.query.filter(getattr(tabla_fk, columna_fk) == row.id).update(
                        {columna_fk: principal.id}
                    )
                else:
                    for r in tabla_fk.query.filter(getattr(tabla_fk, columna_fk) == row.id).all():
                        otro_val = getattr(r, columna_conflicto)
                        conflicto = tabla_fk.query.filter(
                            getattr(tabla_fk, columna_fk) == principal.id,
                            getattr(tabla_fk, columna_conflicto) == otro_val,
                        ).first()
                        if conflicto:
                            db.session.delete(r)
                        else:
                            setattr(r, columna_fk, principal.id)
            db.session.delete(row)
        db.session.commit()

    try:
        _fusionar(Empresa, "nombre", [(Maquina, "empresa_id", None)])
        _fusionar(Pool, "nombre", [(Maquina, "pool_id", None)])
        _fusionar(DirectorioUsuario, "username", [(MaquinaUsuarioDir, "directorio_usuario_id", "maquina_id")])
    except Exception as e:
        print(f"[init_db] Aviso: no se pudo fusionar duplicados case-insensitive: {e}", flush=True)
        db.session.rollback()


def seed_catalogos():
    """Popula catálogos predeterminados de Origen y Configuración."""
    origenes_def = [
        ("dt", "Desktop / VDI"),
        ("su", "Servers / Servidores Únicos"),
        ("core", "Core Infrastructure"),
        ("mz", "DMZ Zone"),
    ]
    for cod, desc in origenes_def:
        if not Origen.query.filter_by(codigo=cod).first():
            db.session.add(Origen(codigo=cod, descripcion=desc))

    configs_def = [
        ("retencion_snapshots_dias", os.environ.get("RETENCION_SNAPSHOTS_DIAS", "90"), "Días de retención para imágenes snapshot antiguas"),
        ("session_ttl_segundos", "1800", "Tiempo de vida del token de sesión vCenter (segundos)"),
    ]
    for key, val, desc in configs_def:
        if not Configuracion.query.filter_by(clave=key).first():
            db.session.add(Configuracion(clave=key, valor=val, descripcion=desc))

    db.session.commit()


def _seed_admin():
    """
    Siembra el primer usuario admin SOLO si ADMIN_BOOTSTRAP_USER/ADMIN_BOOTSTRAP_PASSWORD
    están en el entorno (.env). Ya no existe un admin/admin por defecto: si no hay bootstrap
    configurado y la tabla usuarios está vacía, el sistema arranca sin ningún admin y hay que
    crear uno a mano (scripts/remove_default_admin.py documenta el flujo de reemplazo).
    """
    if Usuario.query.first() is not None:
        return
    bootstrap_user = os.environ.get("ADMIN_BOOTSTRAP_USER")
    bootstrap_pass = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD")
    if not bootstrap_user or not bootstrap_pass:
        return
    admin = Usuario(
        username=bootstrap_user,
        rol="admin",
        nombre_completo="Administrador",
        activo=True,
        must_change_password=True,
    )
    admin.set_password(bootstrap_pass)
    db.session.add(admin)
    db.session.commit()


def get_or_create_catalogo(model, campo: str, valor: str, extra_fields: dict | None = None):
    """
    Get-or-create case-insensitive y a prueba de condición de carrera para catálogos con
    columna única (Empresa.nombre, Pool.nombre, DirectorioUsuario.username, etc.).

    Necesario porque la extracción corre varios servidores Horizon/vCenter EN PARALELO
    (ThreadPoolExecutor) y dos hilos pueden intentar crear el mismo catálogo (misma empresa,
    mismo usuario) al mismo tiempo: sin esto, el SELECT de "no existe" de ambos hilos pasa
    antes de que ninguno haga commit, y los dos terminan insertando una fila cada uno.
    Usa un SAVEPOINT (begin_nested) para que, si la carrera se pierde, sólo se descarte este
    INSERT puntual — no toda la transacción de la extracción en curso.
    """
    valor_clean = (valor or "").strip()
    if not valor_clean:
        return None
    col = getattr(model, campo)
    existente = model.query.filter(func.lower(col) == valor_clean.lower()).first()
    if existente:
        return existente

    obj = model(**{campo: valor_clean}, **(extra_fields or {}))
    try:
        with db.session.begin_nested():
            db.session.add(obj)
            db.session.flush()
        return obj
    except IntegrityError:
        return model.query.filter(func.lower(col) == valor_clean.lower()).first()


def get_or_create_directorio_usuario(username_raw: str, empresa: str | None = None,
                                      nombre_completo: str | None = None) -> "DirectorioUsuario | None":
    """Normaliza (saca DOMINIO\\ y @dominio) y resuelve/crea el DirectorioUsuario, a prueba
    de condición de carrera entre servidores procesados en paralelo durante la extracción."""
    if not username_raw:
        return None
    from web.security_utils import normalizar_username
    clean_u = normalizar_username(username_raw)
    if not clean_u:
        return None
    dir_u = get_or_create_catalogo(
        DirectorioUsuario, "username", clean_u,
        extra_fields={"empresa": empresa or None, "nombre_completo": nombre_completo or None, "activo_ad": True},
    )
    if dir_u:
        if empresa and not dir_u.empresa:
            dir_u.empresa = empresa
        if nombre_completo and not dir_u.nombre_completo:
            dir_u.nombre_completo = nombre_completo
    return dir_u


def registrar_auditoria(accion: str, recurso: str = None,
                         detalle: str = None, usuario_id: int = None,
                         username: str = None, ip: str = None,
                         recurso_id: int = None, resultado: str = "exito"):
    """Helper para registrar un evento de auditoría."""
    log = AuditoriaLog(
        accion=accion,
        recurso=recurso,
        recurso_id=recurso_id,
        resultado=resultado,
        detalle=detalle,
        usuario_id=usuario_id,
        username=username,
        ip_origen=ip,
    )
    db.session.add(log)


def detectar_cambio_usuario(nombre_vm: str, usuario_anterior: str, usuario_nuevo: str,
                             snapshot_id: int = None, servidor_id: int = None,
                             pool: str = None, origen: str = None, tipo: str = None,
                             empresa_anterior: str = None, empresa_nueva: str = None,
                             estado_horizon: str = None, maquina_id: int = None):
    """
    Registra en HistorialUsuarioVDI si hubo cambio de usuario.
    Retorna True si hubo cambio, False si no.
    """
    ant = (usuario_anterior or "").strip().lower()
    nuevo = (usuario_nuevo or "").strip().lower()
    if ant == nuevo:
        return False

    h = HistorialUsuarioVDI(
        nombre_vm        = nombre_vm,
        maquina_id       = maquina_id,
        servidor_id      = servidor_id,
        pool             = pool,
        origen           = origen,
        tipo             = tipo,
        usuario_anterior = usuario_anterior or None,
        usuario_nuevo    = usuario_nuevo or None,
        empresa_anterior = empresa_anterior,
        empresa_nueva    = empresa_nueva,
        estado_horizon   = estado_horizon,
        snapshot_id      = snapshot_id,
    )
    db.session.add(h)
    return True
