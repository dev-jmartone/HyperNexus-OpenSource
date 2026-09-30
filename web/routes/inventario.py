"""
web/routes/inventario.py
Extracción de datos Horizon/vCenter, guardado en DB y vista de tabla.
"""
import os
import json
import re
import threading
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect,
                   url_for, jsonify, Response, stream_with_context, flash, session)
from sqlalchemy import func

from web.db import (db, Servidor, InventarioSnapshot, Maquina,
                    CorreccionManual, Empresa, Pool, Origen, MaquinaHistorial,
                    HorizonUsuarioSid, Datastore, HostEsxi, InfraEvento,
                    Farm, AplicacionPublicada, AplicacionEntitlement, FarmRdsServer,
                    detectar_cambio_usuario, registrar_auditoria)
from web.kpi_utils import clasificar_provisionamiento

bp_inventario = Blueprint("inventario", __name__, url_prefix="/inventario")

# Estado de jobs de extracción + progreso SSE (externalizado a Redis si está disponible,
# ver web/jobs.py — permite escalar a múltiples workers sin perder tracking de progreso).
from web import jobs as _jobs
_db_write_lock = threading.Lock()

# Referencias de "golden image" (master) detectadas en pools Horizon durante la Fase 1 de una
# extracción, agrupadas por origen (dt/su/core/mz) para que la Fase 2 (vCenter) las cruce contra
# sus VMs y marque la golden image como MASTER en vez de VM_ESTATICA. Vive solo durante una
# corrida de _ejecutar_extraccion (Fase 1 y 2 corren secuencialmente, sin condición de carrera).
_master_refs_by_origen: dict[str, set] = {}


# ── Type-safe & Catalog helpers ────────────────────────────────────────

def _safe_int(val) -> int | None:
    try:
        return int(val) if val is not None and val != "" else None
    except (ValueError, TypeError):
        return None

def _safe_float(val) -> float | None:
    try:
        return round(float(val), 2) if val is not None and val != "" else None
    except (ValueError, TypeError):
        return None

def _normalizar_fecha_ingreso(val) -> str | None:
    """Convierte epoch (ms o s, int o string numérica) a ISO 8601 legible por la ficha
    web (ver tiempoRelativo/formatFechaIngreso en el frontend). La API de sesiones de
    Horizon (core/horizon_rest.py -- s.get("start_time")) devuelve epoch en milisegundos
    crudo, guardado tal cual en Maquina.fecha_ultimo_ingreso hasta ahora -- de ahí el bug
    real "fecha en números" reportado 2026-09-08. Si val ya es una fecha (string no
    numérica, ej. una corrección manual) se deja intacta."""
    if val is None or val == "":
        return None
    try:
        n = float(val)
    except (ValueError, TypeError):
        return val
    if n > 1e12:
        n /= 1000
    try:
        return datetime.fromtimestamp(n).isoformat()
    except (ValueError, OSError, OverflowError):
        return val

def _get_or_create_empresa(nombre: str) -> Empresa | None:
    # Case-insensitive y a prueba de condición de carrera entre servidores extraídos en
    # paralelo (ver web.db.get_or_create_catalogo) — Horizon/vCenter/GAL pueden devolver la
    # misma empresa con distinta capitalización según la fuente ("Corp" vs "CORP").
    from web.db import get_or_create_catalogo
    return get_or_create_catalogo(Empresa, "nombre", nombre)

def _get_or_create_pool(nombre: str) -> Pool | None:
    from web.db import get_or_create_catalogo
    return get_or_create_catalogo(Pool, "nombre", nombre)

def _get_or_create_origen(codigo: str) -> Origen | None:
    if not codigo or not codigo.strip():
        return None
    cod_clean = codigo.strip().lower()
    o = Origen.query.filter_by(codigo=cod_clean).first()
    if not o:
        o = Origen(codigo=cod_clean, descripcion=cod_clean.upper())
        db.session.add(o)
        db.session.flush()
    return o


# ── Helpers ──────────────────────────────────────────────────────────

def _clasificar_tipo(servidor: Servidor, pool: str) -> str:
    """Determina si una máquina es VDI o VM."""
    if servidor.tipo_maquina in ("VDI", "VM"):
        return servidor.tipo_maquina
    # "ambos" → detectar por pool
    pool_lower = (pool or "").lower()
    if "vdi" in pool_lower or "desktop" in pool_lower:
        return "VDI"
    return "VM"


def _aplicar_correcciones(maquina_dict: dict, correcciones: dict) -> dict:
    """Aplica correcciones manuales a un dict de máquina."""
    nombre = maquina_dict.get("nombre", "")
    if nombre in correcciones:
        c = correcciones[nombre]
        for campo in ["dns", "pool", "usuario_asignado", "empresa",
                      "estado_horizon", "manager", "agent_version", "so", "tipo"]:
            if c.get(campo):
                maquina_dict[campo] = c[campo]
    return maquina_dict


def _push_sse(job_id: str, msg: str, tipo: str = "log"):
    """Envía evento SSE al job (Redis pub/sub o memoria local, ver web/jobs.py) y actualiza su estado."""
    _jobs.push_event(job_id, tipo, msg)

def get_active_job():
    return _jobs.get_active_job()

@bp_inventario.route("/api/active_job")
def active_job_api():
    job = get_active_job()
    if job:
        return jsonify({"ok": True, "active": True, "job": job})
    return jsonify({"ok": True, "active": False})


# ── Vista principal ───────────────────────────────────────────────────

@bp_inventario.route("/")
def index():
    # Filtros
    tipo_filter    = request.args.get("tipo", "")
    origen_filter  = request.args.get("origen", "")
    empresa_filter = request.args.get("empresa", "")
    pool_filter    = request.args.get("pool", "")
    estado_filter  = request.args.get("estado", "")
    servidor_filter = request.args.get("servidor_id", "")
    buscar         = request.args.get("q", "")

    has_snapshots = db.session.query(InventarioSnapshot.id).filter(
        InventarioSnapshot.estado.in_(["completado", "ok"])
    ).first() is not None

    if has_snapshots:
        subq = (
            db.session.query(
                InventarioSnapshot.servidor_id,
                db.func.max(InventarioSnapshot.id).label("max_id")
            )
            .filter(InventarioSnapshot.estado.in_(["completado", "ok"]))
            .group_by(InventarioSnapshot.servidor_id)
            .subquery()
        )
        query = Maquina.query.filter(
            Maquina.ultimo_snapshot_id.in_(
                db.session.query(subq.c.max_id)
            )
        )
    else:
        query = Maquina.query
    if tipo_filter:
        query = query.filter(Maquina.tipo == tipo_filter)
    if origen_filter:
        query = query.filter(Maquina._origen_str.ilike(f"%{origen_filter}%"))
    if empresa_filter:
        query = query.filter(Maquina._empresa_str.ilike(f"%{empresa_filter}%"))
    if pool_filter:
        query = query.filter(Maquina._pool_str.ilike(f"%{pool_filter}%"))
    if estado_filter:
        query = query.filter(Maquina.estado_horizon.ilike(f"%{estado_filter}%"))
    if servidor_filter:
        query = query.filter(Maquina.servidor_id == int(servidor_filter))
    if buscar:
        like = f"%{buscar}%"
        query = query.filter(
            db.or_(
                Maquina.nombre.ilike(like),
                Maquina.usuario_asignado.ilike(like),
                Maquina._empresa_str.ilike(like),
                Maquina._pool_str.ilike(like),
                Maquina.dns.ilike(like),
            )
        )

    maquinas = query.order_by(Maquina.nombre).all()

    # Datos para filtros dinámicos
    servidores  = Servidor.query.filter_by(activo=True).all()
    empresas    = sorted(set(m.empresa for m in Maquina.query.all() if m.empresa))
    pools       = sorted(set(m.pool for m in Maquina.query.all() if m.pool))
    origenes    = sorted(set(m.origen for m in Maquina.query.all() if m.origen))

    return render_template(
        "inventario.html",
        maquinas=maquinas,
        servidores=servidores,
        empresas=empresas,
        pools=pools,
        origenes=origenes,
        filtros={
            "tipo": tipo_filter,
            "origen": origen_filter,
            "empresa": empresa_filter,
            "pool": pool_filter,
            "estado": estado_filter,
            "servidor_id": servidor_filter,
            "q": buscar,
        },
    )


# ── Extracción ────────────────────────────────────────────────────────

@bp_inventario.route("/extraer", methods=["GET"])
def extraer_form():
    servidores = Servidor.query.filter_by(activo=True).all()
    active_job = get_active_job()
    return render_template("extraer.html", servidores=servidores, active_job=active_job)


from web.auth import get_current_user

@bp_inventario.route("/extraer", methods=["POST"])
def extraer_post():
    """Lanza extracción en background y redirige al stream SSE."""
    servidor_ids = request.form.getlist("servidor_ids")
    mantener_correcciones = "mantener_correcciones" in request.form

    from web.db import guardar_credencial_encriptada, obtener_credencial_desencriptada

    user = get_current_user()
    user_email = (user.email.strip() if user and user.email else user.username) if user else ""
    form_pwd = (request.form.get("vc_password") or "").strip()
    # La clave nunca se guarda en la cookie de sesión (firmada pero NO encriptada por Flask,
    # legible en Base64 por cualquiera con la cookie) -- vive solo en SesionCredencialTemp,
    # cifrada con Fernet, mismo mecanismo que ya usan api.py::auth_set_vc_credentials y
    # servidores.py::guardar_credenciales_sesion (hallazgo de seguridad, corregido 2026-09-07).
    session_pwd = form_pwd or (obtener_credencial_desencriptada(user.id) if user else None) or ""

    if not servidor_ids:
        flash("Seleccioná al menos un servidor.", "error")
        return redirect(url_for("inventario.extraer_form"))

    if not session_pwd:
        flash("Se requiere la contraseña de sesión de vCenter/Horizon. Ingresala desde el botón superior.", "error")
        return redirect(url_for("inventario.extraer_form"))

    if user and form_pwd:
        guardar_credencial_encriptada(user.id, form_pwd, ttl_seconds=1800)
    session["vc_usuario"] = user_email
    session.pop("vc_password", None)
    session.pop("vc_expires_at", None)

    job_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    started = _jobs.try_start_job(job_id, {
        "status": "running",
        "pct": 0,
        "msg": "Iniciando extracción...",
        "created_at": datetime.utcnow().isoformat(),
        "servidores_count": len(servidor_ids),
    })
    if not started:
        flash("Ya hay una extracción en curso (manual o automática). Esperá a que termine — "
              "lanzar dos en paralelo satura vCenter/Horizon.", "error")
        return redirect(url_for("inventario.extraer_form"))

    # Lanzar en thread con email del usuario y su clave de sesión
    t = threading.Thread(
        target=_ejecutar_extraccion,
        args=(job_id, servidor_ids, mantener_correcciones, user_email, session_pwd),
        daemon=True
    )
    t.start()

    return redirect(url_for("inventario.progreso", job_id=job_id))


@bp_inventario.route("/progreso/<job_id>")
def progreso(job_id: str):
    return render_template("progreso.html", job_id=job_id)


@bp_inventario.route("/stream/<job_id>")
def stream(job_id: str):
    """Server-Sent Events para progreso en tiempo real (Redis pub/sub o memoria local, ver web/jobs.py)."""
    def generate():
        for event in _jobs.stream_events(job_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


def _clean_vm_name(name: str) -> str:
    """Normaliza nombres de VM despojando sufijos FQDN (.corp.local) y convirtiendo a UPPERCASE."""
    if not name:
        return ""
    return name.split(".")[0].strip().upper()


def _construir_indice_nombre_limpio(servidor_id: int) -> dict:
    """Índice en memoria {nombre_limpio: Maquina} de TODAS las filas activas de un
    servidor, construido UNA sola vez al arrancar el procesamiento de ese servidor --
    reemplaza el fallback O(N) que hacía `_save_or_update_maquina_impl` (traer TODAS las
    filas del servidor y filtrar en Python) en CADA VM procesada. Con un servidor de
    1000+ VMs y aunque sea 10% cayendo a este fallback, eran ~100 queries trayendo hasta
    1000+ filas cada una (hallazgo de calidad/performance, corregido 2026-09-07).

    Se mantiene actualizado en vivo por el caller cuando se crea una fila nueva durante
    el mismo run (ver `_save_or_update_maquina_impl`) -- así la VM #500 de la corrida ve
    lo que escribió la VM #1, mismo comportamiento que las queries en vivo de antes.

    Si algo sale mal usando el índice, `_save_or_update_maquina`/`_impl` aceptan
    `indice_nombre_limpio=None` y caen exactamente al camino viejo (query por VM) sin
    tocar código -- ver ese parámetro para el rollback rápido en caliente."""
    indice: dict[str, "Maquina"] = {}
    for m in Maquina.query.filter_by(servidor_id=servidor_id).all():
        clave = _clean_vm_name(m.nombre)
        if clave and clave not in indice:
            indice[clave] = m
    return indice


def _validar_y_reconciliar_payload(log_callback=None):
    """
    Auditoría & Reconciliación de datos post-extracción:
    - Genera data/audit_reconciliacion.json
    - Detecta eventos huérfanos e integridad global del inventario.
    """
    from web.db import db, Maquina, Pool, VMTareaEvento
    from datetime import datetime
    import json, os

    # ── Deduplicación Automática Post-Extracción ───────────────────────────
    all_active = Maquina.query.filter_by(activo=True).all()
    cleaned_map = {}
    dupes_merged = 0

    for m in all_active:
        c_name = _clean_vm_name(m.nombre)
        if not c_name: continue
        if c_name not in cleaned_map:
            cleaned_map[c_name] = m
        else:
            primary = cleaned_map[c_name]
            dupe = m

            # Bug real encontrado 2026-08-12: nombre limpio igual no significa misma VM --
            # vCenter puede tener VMs físicas distintas con el mismo nombre exacto (golden
            # images con una copia vieja duplicada, confirmado en vivo). Esta fusión corría
            # DESPUÉS de la extracción y, sin chequear external_id, volvía a mezclar en una
            # sola fila lo que _save_or_update_maquina_impl ya había separado correctamente
            # (mismo criterio que _es_otra_vm ahí) -- deshacía el fix de raíz en otra capa.
            if primary.external_id and dupe.external_id and primary.external_id != dupe.external_id:
                continue

            # Fusión de duplicado en el registro principal

            # Copiar campos no nulos del duplicado al principal
            for attr in ("ip_principal", "vcenter_host", "estado_vcenter", "estado_horizon",
                         "cpu", "ram_gb", "disk_provisioned_gb", "so", "dns", "folder",
                         "resource_pool", "datastores", "hardware_version", "annotation"):
                val_dupe = getattr(dupe, attr, None)
                val_pri = getattr(primary, attr, None)
                if val_dupe and not val_pri:
                    setattr(primary, attr, val_dupe)

            # Re-anclar eventos y tareas del duplicado al registro principal
            VMTareaEvento.query.filter_by(maquina_id=dupe.id).update({"maquina_id": primary.id})
            MaquinaHistorial.query.filter_by(maquina_id=dupe.id).update({"maquina_id": primary.id})

            db.session.delete(dupe)
            dupes_merged += 1

    if dupes_merged > 0:
        db.session.commit()
        if log_callback:
            log_callback(f"  [Reconciliacion Anti-Duplicacion] {dupes_merged} registros duplicados fusionados limpiamente.")

    total_vms = Maquina.query.filter_by(activo=True).count()
    vdis_horizon = Maquina.query.filter_by(activo=True, tipo="VDI").count()
    vms_vcenter = Maquina.query.filter_by(activo=True, tipo="VM").count()

    total_eventos = VMTareaEvento.query.count()
    # "Huérfano real" = apunta a una Maquina que ya no existe (maquina_id FK sin destino).
    # Con VMTareaEvento.maquina_id -> ondelete="CASCADE", esto solo puede pasar si algo
    # rompió la integridad referencial (nunca en operación normal). Distinto de "evento de
    # VM decomisionada" (Maquina.activo == False): eso es historial esperado y correcto --
    # se conserva hasta que el RetentionPurger lo purga a los N días (Configuracion.
    # retencion_snapshots_dias), NO es una falla. Antes ambos casos sumaban a
    # "eventos_huerfanos" y disparaban ADVERTENCIA permanente en cualquier entorno con
    # rotación normal de VMs (decomisionar una VM basta para nunca volver a estar "OK").
    eventos_huerfanos_reales = (
        db.session.query(VMTareaEvento)
        .outerjoin(Maquina, VMTareaEvento.maquina_id == Maquina.id)
        .filter(Maquina.id == None)
        .count()
    )
    eventos_vm_decomisionada = (
        db.session.query(VMTareaEvento)
        .join(Maquina, VMTareaEvento.maquina_id == Maquina.id)
        .filter(Maquina.activo == False)
        .count()
    )
    pools_totales = Pool.query.filter_by(activo=True).count()

    audit_payload = {
        "fecha_auditoria": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "resumen_reconciliacion": {
            "total_maquinas_activas": total_vms,
            "vdis_horizon": vdis_horizon,
            "vms_vcenter_exclusivas": vms_vcenter,
            "pools_registradas": pools_totales,
            "eventos_totales_anclados": total_eventos,
            "eventos_huerfanos": eventos_huerfanos_reales,
            "eventos_vm_decomisionada": eventos_vm_decomisionada,
            "duplicados_fusionados": dupes_merged,
            "estado_integridad": "OK" if eventos_huerfanos_reales == 0 else "ADVERTENCIA"
        }
    }

    try:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(data_dir, exist_ok=True)
        json_path = os.path.join(data_dir, "audit_reconciliacion.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(audit_payload, f, indent=2, ensure_ascii=False)
        if log_callback:
            log_callback(f"\n  [Motor Reconciliacion] Audit report generado en 'data/audit_reconciliacion.json'.")
            log_callback(f"  [Motor Reconciliacion] Integridad: {audit_payload['resumen_reconciliacion']['estado_integridad']} | {total_vms} VMs activas | {total_eventos} Eventos anclados "
                         f"({eventos_huerfanos_reales} huerfanos reales, {eventos_vm_decomisionada} de VMs decomisionadas -- historial esperado, no es alerta).")

        # Disparar alertas por Webhook si la integridad requiere atención
        _disparar_alertas_webhook(audit_payload, log_callback=log_callback)
    except Exception as e:
        if log_callback:
            log_callback(f"[Motor Reconciliación Error] {e}")


def _disparar_alertas_webhook(audit_payload: dict, log_callback=None):
    """Envía notificación HTTP POST a Webhook (Teams/Slack/Custom) si se detectan anomalías."""
    try:
        from web.db import Configuracion
        cfg = Configuracion.query.filter_by(clave="webhook_url").first()
        if not cfg or not cfg.valor or not cfg.valor.startswith("http"):
            return

        from web.security_utils import url_webhook_es_segura
        webhook_url = cfg.valor
        if not url_webhook_es_segura(webhook_url):
            if log_callback:
                log_callback(f"[Webhook Alert] URL rechazada (no resuelve a IP pública/válida): {webhook_url[:60]}")
            return

        import urllib.request
        resumen = audit_payload.get("resumen_reconciliacion", {})
        
        payload_msg = {
            "text": f"⚠️ *Alerta Inventario VDI — Reporte de Auditoría*\n"
                    f"- Integridad: *{resumen.get('estado_integridad')}*\n"
                    f"- Total VMs Activas: {resumen.get('total_maquinas_activas')}\n"
                    f"- Eventos Huérfanos: {resumen.get('eventos_huerfanos')}\n"
                    f"- Detección: {audit_payload.get('timestamp')}"
        }
        
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload_msg).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if log_callback:
                log_callback(f"🔔 [Webhook Alert] Notificación enviada exitosamente a {webhook_url[:30]}...")
    except Exception as e:
        if log_callback:
            log_callback(f"[Webhook Alert Exception] {e}")




def _ejecutar_extraccion(job_id: str, servidor_ids: list[str], mantener_correcciones: bool,
                         session_user: str = "", session_pwd: str = "", es_automatico: bool = False):
    """Extrae datos de los servidores seleccionados usando un motor de extracción unificado ultra rápido de alto rendimiento."""
    from web.app import create_app
    app = create_app()

    def log(msg: str):
        _push_sse(job_id, msg, "log")

    def progress(pct: float, msg: str):
        _push_sse(job_id, msg, "progress")
        _push_sse(job_id, str(int(pct * 100)), "pct")

    with app.app_context():
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            from core.horizon_rest import HorizonRestClient
            from core.vcenter_rest import vCenterRestClient
            from core.appvolumes_rest import AppVolumesRestClient
            from concurrent.futures import ThreadPoolExecutor

            _master_refs_by_origen.clear()

            servidores = Servidor.query.filter(
                Servidor.id.in_([int(x) for x in servidor_ids]),
                Servidor.activo == True
            ).all()

            total_servidores = len(servidores)

            horizon_client = HorizonRestClient(log_callback=log)
            vcenter_client = vCenterRestClient(log_callback=log)
            appvolumes_client = AppVolumesRestClient(log_callback=log)

            correcciones = {}
            if mantener_correcciones:
                for c in CorreccionManual.query.all():
                    correcciones[c.nombre_vm] = c.to_dict()

            if os.environ.get("DEMO_MODE", "0") == "1":
                import time
                log("🧪 [DEMO MODE] Entorno de demostración activo — simulando extracción de telemetría...")
                time.sleep(0.4)
                progress(0.25, "Consultando Horizon Connection Servers (Simulado)...")
                log("✅ [Demo] Horizon Pools y Sesiones virtuales verificadas.")
                time.sleep(0.4)
                progress(0.60, "Extrayendo métricas de vSphere vCenter y hardware host...")
                log("✅ [Demo] Clústeres ESXi, Datastores y VMs actualizados.")
                time.sleep(0.4)
                progress(0.85, "Sincronizando App Volumes packages y writable volumes...")
                log("✅ [Demo] Paquetes de aplicaciones y volúmenes reconciliados.")
                time.sleep(0.3)
                progress(0.95, "Ejecutando motor de reconciliación y auditoría de integridad...")
                _validar_y_reconciliar_payload(log_callback=log)
                for s in servidores:
                    s.ultimo_sync = datetime.utcnow()
                    s.sync_status = "completado"
                db.session.commit()
                progress(1.0, "✅ Extracción completada (Simulación Demo)")
                log("\n✅ [Demo] Extracción completada exitosamente sin requerir conectividad de infraestructura.")
                from web.cache import invalidate
                invalidate("kpis:")
                _push_sse(job_id, "/inventario", "done")
                return

            log("─── Iniciando motor de extracción 100% PURE REST API (HTTPS Directo sin PowerShell) ───")
            progress(0.05, "Conectando a endpoints HTTPS REST en paralelo...")
            log(f"Extrayendo de {total_servidores} servidor(es) simultáneamente...")

            exitos_count = 0
            errores_count = 0

            horizon_srvs = [s for s in servidores if s.tipo == "horizon"]
            vcenter_srvs = [s for s in servidores if s.tipo == "vcenter"]
            appvolumes_srvs = [s for s in servidores if s.tipo == "appvolumes"]

            # Cancelación cooperativa: no se puede abortar un request HTTP en vuelo,
            # así que se chequea entre fases — el corte tarda como máximo lo que dure
            # la fase que está corriendo en ese momento, no es instantáneo.
            def _cancelado() -> bool:
                if _jobs.is_cancel_requested(job_id):
                    log("\n⏹ Extracción cancelada por el usuario.")
                    _push_sse(job_id, "Extracción cancelada por el usuario.", "cancelled")
                    return True
                return False

            # Techo duro por servidor: sin esto, un solo servidor colgado (DNS que no
            # resuelve, red caída sin RST) bloquea f.result() indefinidamente y el chequeo
            # de cancelación entre fases nunca se alcanza — "cancelando" que no termina
            # nunca. El timeout de los urlopen individuales NO cubre resolución DNS (ver
            # limitación conocida de socket.getaddrinfo en Python), así que hace falta este
            # techo aparte. El hilo abandonado sigue corriendo en segundo plano (Python no
            # puede matar threads), pero deja de bloquear el resto de la extracción.
            _TIMEOUT_POR_SERVIDOR = 300

            def _esperar_futures(futures, fase_nombre):
                nonlocal exitos_count, errores_count
                for f in futures:
                    if _jobs.is_cancel_requested(job_id):
                        for pendiente in futures:
                            pendiente.cancel()
                        break
                    try:
                        f.result(timeout=_TIMEOUT_POR_SERVIDOR)
                        exitos_count += 1
                    except TimeoutError:
                        errores_count += 1
                        log(f"[ERROR {fase_nombre}] Servidor no respondió en {_TIMEOUT_POR_SERVIDOR}s — se abandona y se sigue con el resto.")
                    except Exception as e:
                        errores_count += 1
                        log(f"[ERROR {fase_nombre}] {e}")

            if _cancelado():
                return

            # Fase 1: Servidores Horizon en paralelo
            if horizon_srvs:
                log(f"\n⚡ [Fase 1/2] Escaneando {len(horizon_srvs)} servidor(es) Horizon en PARALELO...")
                def _worker_h(srv):
                    with app.app_context():
                        _extraer_horizon_cred(
                            job_id, srv, session_user, session_pwd, srv.dominio or "",
                            horizon_client, correcciones, 0.10, total_servidores, log, progress
                        )

                with ThreadPoolExecutor(max_workers=min(4, len(horizon_srvs))) as executor:
                    futures = [executor.submit(_worker_h, srv) for srv in horizon_srvs]
                    _esperar_futures(futures, "Horizon Parallel")

            if _cancelado():
                return

            # Fase 2: Servidores vCenter en paralelo (matching dinámico en tiempo real contra Horizon)
            if vcenter_srvs:
                log(f"\n⚡ [Fase 2/2] Escaneando {len(vcenter_srvs)} servidor(es) vCenter en PARALELO...")
                def _worker_vc(srv):
                    with app.app_context():
                        _extraer_vcenter_cred(
                            job_id, srv, session_user, session_pwd, srv.dominio or "",
                            vcenter_client, correcciones, 0.40, total_servidores, log, progress
                        )

                with ThreadPoolExecutor(max_workers=min(4, len(vcenter_srvs))) as executor:
                    futures = [executor.submit(_worker_vc, srv) for srv in vcenter_srvs]
                    _esperar_futures(futures, "vCenter Parallel")

            if _cancelado():
                return

            # Fase App Volumes: aplicaciones/packages/programas/asignaciones (dominio de
            # datos aparte, no toca la tabla maquinas)
            if appvolumes_srvs:
                log(f"\n⚡ [Fase App Volumes] Escaneando {len(appvolumes_srvs)} servidor(es) App Volumes en PARALELO...")
                def _worker_av(srv):
                    with app.app_context():
                        # App Volumes Manager suele requerir una cuenta de servicio propia,
                        # distinta de la contraseña de sesión que el operador tipea para
                        # Horizon/vCenter -- si el servidor tiene credenciales propias
                        # cargadas (ver ServidoresPage), se usan esas; si no, se cae al
                        # fallback histórico de reusar la sesión.
                        if not srv.usuario and es_automatico:
                            # Bug real encontrado 2026-09-04: en una corrida automática
                            # (AutoScheduler) no hay operador humano, session_user es un label
                            # fijo ("Sistema (AutoScheduler)") -- sin cuenta de servicio propia
                            # cargada, este fallback intentaba loguear contra AD literal con
                            # ese label como si fuera un username real, garantizado a fallar.
                            log(f"[AppVolumes {srv.nombre}] Sin cuenta de servicio configurada "
                                f"(Servidor.usuario vacío) -- se omite en extracción automática "
                                f"para no intentar login con un usuario inválido. Configurá una "
                                f"cuenta de servicio en Servidores > {srv.nombre}, o corré la "
                                f"extracción manual.")
                            return
                        av_user = srv.usuario or session_user
                        av_pwd = srv.password if srv.usuario else session_pwd
                        _extraer_appvolumes_cred(
                            job_id, srv, av_user, av_pwd, srv.dominio or "",
                            appvolumes_client, 0.70, total_servidores, log, progress
                        )

                with ThreadPoolExecutor(max_workers=min(4, len(appvolumes_srvs))) as executor:
                    futures = [executor.submit(_worker_av, srv) for srv in appvolumes_srvs]
                    _esperar_futures(futures, "App Volumes Parallel")

            if _cancelado():
                return

            # Fase 3: Motor de Reconciliación & Auditoría
            log("\n🔍 [Fase 3] Ejecutando Motor de Reconciliación y Re-validación de Integridad...")
            _validar_y_reconciliar_payload(log_callback=log)

            if exitos_count == 0 and errores_count > 0:
                progress(1.0, "❌ Error general en la extracción")
                log("\n❌ No se pudo extraer información de ningún servidor. Revisa credenciales o conectividad.")
                _push_sse(job_id, "Falló la autenticación o consulta en todos los servidores.", "error")
            else:
                progress(1.0, "✅ Extracción completada")
                log("\n✅ Extracción completada exitosamente.")
                from web.cache import invalidate
                invalidate("kpis:")
                _push_sse(job_id, "/inventario", "done")

        except Exception as e:
            log(f"[ERROR FATAL] {e}")
            _push_sse(job_id, str(e), "error")


# Campos que se actualizan en vivo pero NO generan fila de MaquinaHistorial — fluctúan
# constantemente (uso de CPU/RAM/disco en cada corrida) y no son "eventos" en el sentido
# de algo que le importe a un admin, solo ruido que ahogaba cambios reales en el feed.
# El disco SÍ genera su propia alerta dedicada (ver _chequear_alerta_disco) pero solo al
# CRUZAR el umbral crítico, no en cada fluctuación normal.
_CAMPOS_SIN_HISTORIAL = {"cpu_usage_mhz", "memory_usage_mb", "disk_used_gb"}

_UMBRAL_DISCO_CRITICO = 0.90


def _chequear_alerta_disco(maquina_id: int, snapshot_id: int,
                            usado_ant: float | None, total_ant: float | None,
                            usado_nuevo: float | None, total_nuevo: float | None):
    """Genera un evento 'disco_critico' en MaquinaHistorial SOLO al cruzar el umbral
    (90%) en cualquier dirección — no en cada fluctuación normal de uso, que sería tan
    ruidoso como cpu_usage_mhz/memory_usage_mb (por eso disk_used_gb está en
    _CAMPOS_SIN_HISTORIAL: la columna se actualiza en vivo pero no audita cada cambio)."""
    if usado_nuevo is None or not total_nuevo:
        return
    pct_nuevo = usado_nuevo / total_nuevo
    pct_ant = (usado_ant / total_ant) if (usado_ant is not None and total_ant) else None

    cruzo_arriba = pct_nuevo >= _UMBRAL_DISCO_CRITICO and (pct_ant is None or pct_ant < _UMBRAL_DISCO_CRITICO)
    cruzo_abajo = pct_nuevo < _UMBRAL_DISCO_CRITICO and pct_ant is not None and pct_ant >= _UMBRAL_DISCO_CRITICO
    if not (cruzo_arriba or cruzo_abajo):
        return

    db.session.add(MaquinaHistorial(
        maquina_id=maquina_id,
        snapshot_id=snapshot_id,
        campo_modificado="disco_critico",
        valor_anterior=f"{round((pct_ant or 0) * 100, 1)}%",
        valor_nuevo=f"{round(pct_nuevo * 100, 1)}%",
        detectado_en=datetime.utcnow(),
    ))


def _guardar_infra_datastores_hosts(servidor: "Servidor", hosts_raw: list, datastores_raw: list, log):
    """Persiste datastores/hosts ESXi de este vCenter y genera InfraEvento cuando:
    - un datastore cruza el 90% de uso (en cualquier dirección), o
    - un host cambia de connection_state (ej. CONNECTED -> DISCONNECTED).
    No estaba conectado a ninguna tabla — la respuesta de vCenter que ya se pedía para
    armar el lookup de nombres traía esto y se descartaba."""
    vistos_host = set()
    for h in hosts_raw:
        nombre = h.get("Name")
        if not nombre:
            continue
        vistos_host.add(nombre)
        row = HostEsxi.query.filter_by(servidor_id=servidor.id, nombre=nombre).first()
        estado_nuevo = h.get("ConnectionState")
        if not row:
            row = HostEsxi(servidor_id=servidor.id, nombre=nombre,
                            connection_state=estado_nuevo, power_state=h.get("PowerState"))
            db.session.add(row)
        else:
            estado_ant = row.connection_state
            if estado_nuevo and estado_ant != estado_nuevo:
                db.session.add(InfraEvento(
                    tipo="host_desconectado" if estado_nuevo != "CONNECTED" else "host_reconectado",
                    entidad_nombre=nombre,
                    servidor_id=servidor.id,
                    valor_anterior=estado_ant or "—",
                    valor_nuevo=estado_nuevo,
                    mensaje=f"Host {nombre} pasó de '{estado_ant or '—'}' a '{estado_nuevo}'.",
                    detectado_en=datetime.utcnow(),
                ))
            row.connection_state = estado_nuevo
            row.power_state = h.get("PowerState")
            row.activo = True

    if vistos_host:
        for row in HostEsxi.query.filter_by(servidor_id=servidor.id, activo=True).all():
            if row.nombre not in vistos_host:
                row.activo = False

    vistos_ds = set()
    for d in datastores_raw:
        nombre = d.get("Name")
        if not nombre:
            continue
        vistos_ds.add(nombre)
        cap = d.get("CapacityGB")
        free = d.get("FreeGB")
        usado = round(cap - free, 2) if (cap is not None and free is not None) else None

        row = Datastore.query.filter_by(servidor_id=servidor.id, nombre=nombre).first()
        if not row:
            row = Datastore(servidor_id=servidor.id, nombre=nombre, capacidad_gb=cap,
                             espacio_libre_gb=free, tipo=d.get("Type"))
            db.session.add(row)
            db.session.flush()
            if usado is not None and cap:
                pct = usado / cap
                if pct >= _UMBRAL_DISCO_CRITICO:
                    db.session.add(InfraEvento(
                        tipo="datastore_critico", entidad_nombre=nombre, servidor_id=servidor.id,
                        valor_anterior="—", valor_nuevo=f"{round(pct * 100, 1)}%",
                        mensaje=f"Datastore {nombre} al {round(pct * 100, 1)}% de uso.",
                        detectado_en=datetime.utcnow(),
                    ))
        else:
            usado_ant = row.capacidad_gb - row.espacio_libre_gb if (row.capacidad_gb and row.espacio_libre_gb is not None) else None
            pct_ant = (usado_ant / row.capacidad_gb) if (usado_ant is not None and row.capacidad_gb) else None
            pct_nuevo = (usado / cap) if (usado is not None and cap) else None

            if pct_nuevo is not None:
                cruzo_arriba = pct_nuevo >= _UMBRAL_DISCO_CRITICO and (pct_ant is None or pct_ant < _UMBRAL_DISCO_CRITICO)
                cruzo_abajo = pct_nuevo < _UMBRAL_DISCO_CRITICO and pct_ant is not None and pct_ant >= _UMBRAL_DISCO_CRITICO
                if cruzo_arriba or cruzo_abajo:
                    db.session.add(InfraEvento(
                        tipo="datastore_critico", entidad_nombre=nombre, servidor_id=servidor.id,
                        valor_anterior=f"{round((pct_ant or 0) * 100, 1)}%",
                        valor_nuevo=f"{round(pct_nuevo * 100, 1)}%",
                        mensaje=f"Datastore {nombre}: {round((pct_ant or 0) * 100, 1)}% -> {round(pct_nuevo * 100, 1)}%.",
                        detectado_en=datetime.utcnow(),
                    ))

            if cap is not None:
                row.capacidad_gb = cap
            if free is not None:
                row.espacio_libre_gb = free
            row.tipo = d.get("Type") or row.tipo
            row.activo = True

    if vistos_ds:
        for row in Datastore.query.filter_by(servidor_id=servidor.id, activo=True).all():
            if row.nombre not in vistos_ds:
                row.activo = False

    if hosts_raw or datastores_raw:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log(f"[{servidor.nombre}] ⚠️ No se pudo guardar infraestructura (datastores/hosts): {e}")


# Mensaje real de Horizon (audit-events), ej.:
# "Image Publish initiated by SchedulePushImage for Pool vdi-general succeeded for
#  Image [VM=/DT/vm/Windows 11 - Golden/Master-Package/PC_MSTRWIN11-01,
#  Snapshot=/VM limpia + instaladores/Docker Configuraciones ALL/V9_QUALYS+TEAMS, State=PUBLISHING]"
# Es texto libre, no un campo estructurado de la API -- este regex es la única forma de
# sacar Pool/Master VM/Snapshot de ahí. "VM" es el path completo en el árbol de vCenter;
# el master real es el último segmento (nombre de la VM).
_RE_IMAGEN_EVENTO = re.compile(
    r"Image (?P<accion>Publish|Unpublish) initiated by (?P<iniciado_por>\S+) for Pool (?P<pool>\S+) "
    r"(?P<resultado>succeeded|failed).*?VM=(?P<vm>[^,\]]+).*?Snapshot=(?P<snapshot>[^,\]]+).*?"
    r"State=(?P<estado>[^\]]+)\]"
)


def _parsear_evento_imagen(mensaje: str) -> dict | None:
    """Extrae Pool/Master VM/Snapshot/State de un mensaje de audit-events de Horizon del
    tipo "Image Publish/Unpublish...". None si el mensaje no matchea ese patrón (la
    inmensa mayoría de audit-events son de otro tipo: logins, entitlements, etc)."""
    if not mensaje or "Image " not in mensaje:
        return None
    m = _RE_IMAGEN_EVENTO.search(mensaje)
    if not m:
        return None
    vm_path = m.group("vm").strip()
    return {
        "accion": m.group("accion"),
        "iniciado_por": m.group("iniciado_por"),
        "pool": m.group("pool").strip(),
        "resultado": m.group("resultado"),
        "master_vm": vm_path.rstrip("/").split("/")[-1],
        "snapshot": m.group("snapshot").strip(),
        "estado": m.group("estado").strip(),
    }


def _actualizar_imagen_pools_desde_eventos(log):
    """Recalcula Pool.master_vm_actual/snapshot_actual desde los eventos horizon_audit ya
    guardados en InfraEvento -- se recorre TODO el historial (no solo lo nuevo de esta
    corrida) para quedar siempre consistente con el evento "Image Publish...succeeded"
    más reciente por pool, sea cual sea el orden en que Horizon los haya devuelto."""
    eventos = (
        InfraEvento.query
        .filter_by(tipo="horizon_audit")
        .filter(InfraEvento.mensaje.ilike("%Image Publish%"))
        .order_by(InfraEvento.detectado_en.asc())
        .all()
    )
    if not eventos:
        return

    ultimo_por_pool = {}
    for ev in eventos:
        info = _parsear_evento_imagen(ev.mensaje or "")
        if not info or info["accion"] != "Publish" or info["resultado"] != "succeeded":
            continue
        # Orden ascendente por detectado_en -- el último que sobreescribe el dict gana,
        # así queda el más reciente sin tener que comparar fechas a mano.
        ultimo_por_pool[info["pool"].lower()] = (ev.detectado_en, info)

    if not ultimo_por_pool:
        return

    pools = Pool.query.all()
    actualizados = 0
    for pool in pools:
        clave = (pool.nombre or "").lower()
        # Solo por Pool.nombre (UNIQUE real) -- Pool.display_name tiene datos mal cargados
        # de antes (ej. "Pool-Engineering" con display_name="Pool-Networking", sin ninguna
        # relación real entre esos dos pools) y matcheaba cruzado con la pool equivocada.
        entrada = ultimo_por_pool.get(clave)
        if not entrada:
            continue
        fecha, info = entrada
        if pool.master_vm_actual == info["master_vm"] and pool.snapshot_actual == info["snapshot"]:
            continue
        pool.master_vm_actual = info["master_vm"]
        pool.snapshot_actual = info["snapshot"]
        pool.imagen_actualizada_en = fecha
        actualizados += 1

    if actualizados:
        db.session.commit()
        log(f"Imagen actual (master/snapshot) actualizada en {actualizados} pool(s) desde eventos de Horizon.")


def _persistir_audit_events_horizon(servidor, audit_events: list, log):
    """Persiste el audit trail de Horizon (quién hizo qué — pools/máquinas eliminadas,
    entitlements, etc) como InfraEvento. Dedupea por el id propio de Horizon (guardado
    en valor_anterior) — el endpoint no soporta filtro de fecha confiable, así que cada
    corrida vuelve a traer ~1000 eventos recientes y hay que filtrar los ya conocidos acá."""
    if not audit_events:
        return

    ids_existentes = {
        row[0] for row in db.session.query(InfraEvento.valor_anterior)
        .filter_by(tipo="horizon_audit").all()
    }

    nuevos = 0
    for ev in audit_events:
        ev_id = ev.get("Id")
        if not ev_id or str(ev_id) in ids_existentes:
            continue

        tiempo_ms = ev.get("Time")
        # detectado_en es NOT NULL -- si Horizon no manda Time o no parsea, se usa la hora de
        # la corrida PERO se marca en el mensaje (auditoría 2026-08-12: antes quedaba
        # indistinguible de una fecha real, podía desordenar/falsear "cuándo pasó" en el feed).
        fecha_estimada = False
        try:
            detectado = datetime.utcfromtimestamp(tiempo_ms / 1000) if tiempo_ms else datetime.utcnow()
            if not tiempo_ms:
                fecha_estimada = True
        except (TypeError, ValueError, OSError):
            detectado = datetime.utcnow()
            fecha_estimada = True

        usuario = ev.get("Usuario") or ""
        entidad = ev.get("PoolName") or ev.get("MachineDns") or ev.get("Type") or "Horizon"
        mensaje_evt = f"{usuario + ': ' if usuario else ''}{ev.get('Message') or ''}"
        if fecha_estimada:
            mensaje_evt = f"{mensaje_evt} [fecha estimada, no informada por Horizon]".strip()

        db.session.add(InfraEvento(
            tipo="horizon_audit",
            entidad_nombre=entidad,
            servidor_id=servidor.id,
            valor_anterior=str(ev_id),
            valor_nuevo=ev.get("Type") or "",
            mensaje=mensaje_evt,
            detectado_en=detectado,
        ))
        nuevos += 1

    if nuevos:
        try:
            db.session.commit()
            log(f"[{servidor.nombre}] {nuevos} evento(s) de auditoría Horizon nuevo(s) registrados.")
        except Exception as e:
            db.session.rollback()
            log(f"[{servidor.nombre}] ⚠️ No se pudo guardar audit-events: {e}")
            return

    try:
        _actualizar_imagen_pools_desde_eventos(log)
    except Exception as e:
        db.session.rollback()
        log(f"[{servidor.nombre}] ⚠️ No se pudo actualizar imagen actual de pools: {e}")


def _save_or_update_maquina(servidor_id: int, snapshot_id: int, nombre_vm: str,
                            tipo: str, origen_str: str, pool_str: str, empresa_str: str,
                            usuario_asignado: str, estado_horizon: str, estado_vcenter: str | None,
                            manager: str, agent_version: str, so: str, cpu: int | None,
                            ram_gb: float | None, disk_gb: float | None, dns: str,
                            ip: str, vcenter_host: str | None, correcciones: dict,
                            fecha_ultimo_ingreso: str = "", datos_extra: dict | None = None,
                            disk_used_gb: float | None = None,
                            indice_nombre_limpio: dict | None = None) -> tuple[Maquina, bool]:
    """Guarda o actualiza in-place una VM/VDI y registra deltas en MaquinaHistorial.

    indice_nombre_limpio: índice opcional de _construir_indice_nombre_limpio() para
    evitar el fallback O(N) por VM (ver ese helper). None (default) = camino viejo,
    sin índice -- rollback en caliente sin tocar código si el índice da problemas."""
    # _db_write_lock: esta función corre en paralelo desde varios hilos (uno por servidor
    # Horizon/vCenter, ver _extraer_horizon_cred/_extraer_vcenter_cred) y hace múltiples
    # add()/flush() -- sin serializar, escrituras concurrentes a SQLite generaban
    # "database is locked" esporádico. Antes _db_write_lock solo protegía
    # _guardar_pools_y_autorizaciones_horizon(); acá era donde más falta hacía (loop de
    # cientos de VMs por servidor). acquire/finally en vez de "with" porque la función es
    # larga y tiene un único return al final -- evita reindentar todo el cuerpo.
    _db_write_lock.acquire()
    try:
        return _save_or_update_maquina_impl(
            servidor_id, snapshot_id, nombre_vm, tipo, origen_str, pool_str, empresa_str,
            usuario_asignado, estado_horizon, estado_vcenter, manager, agent_version, so,
            cpu, ram_gb, disk_gb, dns, ip, vcenter_host, correcciones,
            fecha_ultimo_ingreso, datos_extra, disk_used_gb, indice_nombre_limpio,
        )
    finally:
        _db_write_lock.release()


def _save_or_update_maquina_impl(servidor_id: int, snapshot_id: int, nombre_vm: str,
                            tipo: str, origen_str: str, pool_str: str, empresa_str: str,
                            usuario_asignado: str, estado_horizon: str, estado_vcenter: str | None,
                            manager: str, agent_version: str, so: str, cpu: int | None,
                            ram_gb: float | None, disk_gb: float | None, dns: str,
                            ip: str, vcenter_host: str | None, correcciones: dict,
                            fecha_ultimo_ingreso: str = "", datos_extra: dict | None = None,
                            disk_used_gb: float | None = None,
                            indice_nombre_limpio: dict | None = None) -> tuple[Maquina, bool]:
    """Cuerpo real de _save_or_update_maquina -- separado para que el lock de arriba
    envuelva la llamada sin tener que reindentar 300 líneas."""
    if not pool_str or not pool_str.strip():
        pool_str = "Estática"

    # Normalizar usuario_asignado (quitar "DOMINIO\" y "@dominio.lo-que-sea"): Horizon/vCenter/Sessions
    # devuelven el mismo usuario con formato de dominio distinto según el endpoint, y guardarlo crudo
    # generaba falsos "cambio de usuario" en el historial y usuarios contados por separado en
    # reportes/alertas (mismo criterio que ya se usa para vincular con DirectorioUsuario).
    if usuario_asignado:
        from web.security_utils import normalizar_username
        usuario_asignado = normalizar_username(usuario_asignado)

    emp_rel  = _get_or_create_empresa(empresa_str)
    pool_rel = _get_or_create_pool(pool_str)
    orig_rel = _get_or_create_origen(origen_str)

    clean_v_name = _clean_vm_name(nombre_vm)
    ext_id = datos_extra.get("external_id") if datos_extra else None

    maq = None
    if ext_id:
        maq = Maquina.query.filter_by(external_id=ext_id).first()

    # Los fallbacks por nombre solo valen si la fila encontrada no tiene YA un
    # external_id real y distinto al que estamos procesando -- nombres duplicados
    # en vCenter son reales (auditoría 2026-08-12: vCenter MZ tenía VMs golden-image
    # con nombre idéntico y MoRef distinto), y matchear por nombre ahí mezclaba los
    # datos de dos VMs físicas distintas en una sola fila.
    def _es_otra_vm(candidato) -> bool:
        return bool(ext_id and candidato.external_id and candidato.external_id != ext_id)

    if not maq:
        candidato = Maquina.query.filter_by(servidor_id=servidor_id, nombre=nombre_vm).first()
        if candidato and not _es_otra_vm(candidato):
            maq = candidato

    if not maq and clean_v_name:
        # Acotado a servidor_id (bug real encontrado 2026-09-04, auditoria DT): antes buscaba
        # en TODA la tabla sin importar servidor -- si esta VM no existia aun bajo el servidor
        # actual pero un nombre igual (normalizado) ya existia bajo OTRO servidor (ej. una
        # reestructuracion vieja de pools entre sitios), pisaba esa fila ajena: actualizaba
        # origen/pool/tipo con los datos frescos pero dejaba servidor_id del dueño original
        # para siempre (nunca se reasigna, solo se setea al crear la fila). 10 VDI reales de
        # Horizon DT quedaron mostrando "Horizon MZ" como servidor por esto. El merge legitimo
        # Horizon<->vCenter del mismo sitio no pasa por aca (tiene su propio indice por origen
        # mas arriba) -- este fallback es solo para reencontrar la MISMA VM en una corrida
        # posterior del MISMO servidor con el nombre formateado distinto.
        if indice_nombre_limpio is not None:
            # Camino batch (2026-09-07) -- ver _construir_indice_nombre_limpio(). Reemplaza
            # el .all() de abajo por un lookup O(1) en el índice precomputado del servidor.
            candidato = indice_nombre_limpio.get(clean_v_name)
            if candidato and not _es_otra_vm(candidato):
                maq = candidato
        else:
            for m in Maquina.query.filter_by(servidor_id=servidor_id).all():
                if _clean_vm_name(m.nombre) == clean_v_name and not _es_otra_vm(m):
                    maq = m
                    break

    is_new = False

    new_data = {
        "tipo": tipo,
        "pool": pool_str,
        "empresa": empresa_str,
        "usuario_asignado": usuario_asignado,
        "estado_horizon": estado_horizon,
        "manager": manager,
        "agent_version": agent_version,
        "so": so,
        "cpu": cpu,
        "ram_gb": ram_gb,
        "disk_provisioned_gb": disk_gb,
        "dns": dns,
        "ip_principal": ip,
    }
    # estado_vcenter/vcenter_host solo se incluyen si el caller realmente tiene ese dato
    # (None = "no sé", distinto de "" = "sé que está vacío"). El lado Horizon no tiene
    # info de vCenter todavía en su propia pasada y antes mandaba "" acá, que al ser
    # DYNAMIC_LIVE_FIELDS pisaba el valor real que vCenter había guardado la corrida
    # anterior — y unos segundos después, en la misma corrida, la Fase 2 (vCenter) lo
    # rellenaba de nuevo. Eso generaba 2 falsos "cambios" en el historial por VM por
    # corrida, ahogando eventos reales (bajas, cambios de usuario) en ruido.
    if estado_vcenter is not None:
        new_data["estado_vcenter"] = estado_vcenter
    if vcenter_host is not None:
        new_data["vcenter_host"] = vcenter_host
    if disk_used_gb is not None:
        new_data["disk_used_gb"] = disk_used_gb
    if datos_extra:
        import json
        new_data["datos_extra_json"] = json.dumps(datos_extra, ensure_ascii=False)
        # Asignación directa a columnas dedicadas en DB
        for k in ("folder", "ruta_computo", "resource_pool", "datastores", "hardware_version", "annotation",
                  "connection_state", "cpu_usage_mhz", "memory_usage_mb", "in_error_state", "maintenance_mode",
                  "estado_horizon_agente", "tools_status", "external_id", "client_ip", "client_name",
                  "gateway_ip", "gateway_name", "gateway_location",
                  # Agregados 2026-09-07 -- ver Maquina en web/db.py para el detalle de cada uno.
                  "client_type", "client_version", "session_protocol", "session_type", "session_idle_seconds",
                  "cpu_cores_per_socket", "cpu_hot_add_enabled", "memory_hot_add_enabled",
                  "boot_firmware", "secure_boot_enabled", "hardware_upgrade_status"):
            val = datos_extra.get(k) if k in datos_extra else datos_extra.get(k.capitalize())
            if val is None and k == "in_error_state":
                val = datos_extra.get("InErrorState")
            if val is None and k == "maintenance_mode":
                val = datos_extra.get("MaintenanceMode")
            if val is None and k == "estado_horizon_agente":
                val = datos_extra.get("AgentState")
            if val is None and k == "tools_status":
                val = datos_extra.get("ToolsStatus")
            if val is not None:
                new_data[k] = val

        # "" en vez de None en external_id rompería la unicidad (servidor_id, external_id)
        # -- SQLite trata cada NULL como distinto entre sí, pero dos filas con external_id=""
        # sí colisionarían entre sí como si fueran la misma VM. Normalizado a "ausente" (None).
        if not new_data.get("external_id"):
            new_data.pop("external_id", None)

        # Maquina.datastore_id es FK real a Datastore, pero quedaba siempre NULL --
        # "datastores" es el string libre de vCenter (puede listar varios separados por
        # coma si el disco está repartido), acá se resuelve el PRIMERO contra la tabla
        # Datastore real para tener al menos el principal como relación de verdad y no
        # solo texto. Datastore.nombre no es único global (mismo nombre puede repetirse
        # entre vCenters, ej. "vsanDatastore" default por cluster) -- hay que resolver
        # primero el servidor vCenter correcto (por vcenter_host) antes de buscar por nombre.
        if new_data.get("datastores"):
            primer_ds = new_data["datastores"].split(",")[0].strip()
            if primer_ds:
                servidor_ds = None
                if vcenter_host:
                    servidor_ds = Servidor.query.filter_by(host=vcenter_host, tipo="vcenter").first()
                if not servidor_ds:
                    srv_actual = Servidor.query.get(servidor_id)
                    if srv_actual and srv_actual.tipo == "vcenter":
                        servidor_ds = srv_actual
                if servidor_ds:
                    ds_row = Datastore.query.filter_by(servidor_id=servidor_ds.id, nombre=primer_ds).first()
                    if ds_row:
                        new_data["datastore_id"] = ds_row.id
    if fecha_ultimo_ingreso:
        new_data["fecha_ultimo_ingreso"] = _normalizar_fecha_ingreso(fecha_ultimo_ingreso)

    # Aplicar correcciones manuales
    fake_dict = {"nombre": nombre_vm, "tipo": tipo, "empresa": empresa_str, "pool": pool_str,
                 "usuario_asignado": usuario_asignado, "estado_horizon": estado_horizon,
                 "manager": manager, "agent_version": agent_version, "so": so}
    fake_dict = _aplicar_correcciones(fake_dict, correcciones)

    if fake_dict.get("empresa"):
        empresa_str = fake_dict["empresa"]
        emp_rel = _get_or_create_empresa(empresa_str)
    if fake_dict.get("pool"):
        pool_str = fake_dict["pool"] or "Estática"
        pool_rel = _get_or_create_pool(pool_str)

    new_data["empresa"]          = empresa_str
    new_data["pool"]             = pool_str
    new_data["usuario_asignado"] = fake_dict.get("usuario_asignado", usuario_asignado)
    new_data["estado_horizon"]   = fake_dict.get("estado_horizon", estado_horizon)
    new_data["manager"]          = fake_dict.get("manager", manager)
    new_data["agent_version"]    = fake_dict.get("agent_version", agent_version)
    new_data["so"]               = fake_dict.get("so", so)
    if fake_dict.get("tipo"):
        new_data["tipo"] = fake_dict["tipo"]

    new_data["tipo_provisionamiento"] = clasificar_provisionamiento(
        pool_str,
        es_template=bool(datos_extra.get("es_template")) if datos_extra else False,
        es_master=bool(datos_extra.get("es_master")) if datos_extra else False,
    )

    if not maq:
        is_new = True
        # Buscar cualquier registro previo de la VM por nombre (independiente del servidor)
        maq_prev = Maquina.query.filter(Maquina.nombre.ilike(nombre_vm)).order_by(Maquina.primera_deteccion.asc()).first()
        
        fecha_alta = None
        if maq_prev and maq_prev.primera_deteccion:
            fecha_alta = maq_prev.primera_deteccion
        
        if not fecha_alta and fecha_ultimo_ingreso:
            try:
                if isinstance(fecha_ultimo_ingreso, str):
                    if "T" in fecha_ultimo_ingreso:
                        fecha_alta = datetime.strptime(fecha_ultimo_ingreso[:19], "%Y-%m-%dT%H:%M:%S")
                    else:
                        fecha_alta = datetime.strptime(fecha_ultimo_ingreso[:19], "%Y-%m-%d %H:%M:%S")
                elif isinstance(fecha_ultimo_ingreso, datetime):
                    fecha_alta = fecha_ultimo_ingreso
            except Exception:
                pass

        if not fecha_alta:
            fecha_alta = datetime.utcnow()
        
        maq = Maquina(
            servidor_id=servidor_id,
            nombre=nombre_vm,
            ultimo_snapshot_id=snapshot_id,
            tipo=new_data["tipo"],
            origen_id=orig_rel.id if orig_rel else None,
            _origen_str=origen_str,
            pool_id=pool_rel.id if pool_rel else None,
            _pool_str=pool_str,
            empresa_id=emp_rel.id if emp_rel else None,
            _empresa_str=empresa_str,
            usuario_asignado=new_data["usuario_asignado"],
            estado_horizon=new_data["estado_horizon"],
            estado_vcenter=new_data.get("estado_vcenter"),
            manager=new_data["manager"],
            agent_version=new_data["agent_version"],
            so=new_data["so"],
            cpu=new_data["cpu"],
            ram_gb=new_data["ram_gb"],
            disk_provisioned_gb=new_data["disk_provisioned_gb"],
            dns=new_data["dns"],
            ip_principal=new_data["ip_principal"],
            vcenter_host=new_data.get("vcenter_host"),
            folder=new_data.get("folder"),
            ruta_computo=new_data.get("ruta_computo"),
            resource_pool=new_data.get("resource_pool"),
            datastores=new_data.get("datastores"),
            hardware_version=new_data.get("hardware_version"),
            annotation=new_data.get("annotation"),
            connection_state=new_data.get("connection_state"),
            cpu_usage_mhz=new_data.get("cpu_usage_mhz"),
            memory_usage_mb=new_data.get("memory_usage_mb"),
            in_error_state=new_data.get("in_error_state", False),
            maintenance_mode=new_data.get("maintenance_mode", False),
            estado_horizon_agente=new_data.get("estado_horizon_agente"),
            tools_status=new_data.get("tools_status"),
            # Agregados 2026-09-07 -- ver Maquina en web/db.py para el detalle de cada uno.
            client_type=new_data.get("client_type"),
            client_version=new_data.get("client_version"),
            session_protocol=new_data.get("session_protocol"),
            session_type=new_data.get("session_type"),
            session_idle_seconds=new_data.get("session_idle_seconds"),
            cpu_cores_per_socket=new_data.get("cpu_cores_per_socket"),
            cpu_hot_add_enabled=new_data.get("cpu_hot_add_enabled"),
            memory_hot_add_enabled=new_data.get("memory_hot_add_enabled"),
            boot_firmware=new_data.get("boot_firmware"),
            secure_boot_enabled=new_data.get("secure_boot_enabled"),
            hardware_upgrade_status=new_data.get("hardware_upgrade_status"),
            disk_used_gb=new_data.get("disk_used_gb"),
            tipo_provisionamiento=new_data["tipo_provisionamiento"],
            external_id=new_data.get("external_id"),
            datastore_id=new_data.get("datastore_id"),
            activo=True,
            primera_deteccion=fecha_alta,
        )
        db.session.add(maq)
        db.session.flush()

        # Mantener el índice batch al día en vivo (2026-09-07) -- si no, la VM #500 de
        # esta misma corrida no vería la fila que creó la VM #1, y el fallback de nombre
        # limpio la duplicaría en vez de reencontrarla (ver _construir_indice_nombre_limpio).
        if indice_nombre_limpio is not None and clean_v_name:
            indice_nombre_limpio[clean_v_name] = maq

        _chequear_alerta_disco(maq.id, snapshot_id, None, None,
                                new_data.get("disk_used_gb"), new_data.get("disk_provisioned_gb"))

        if maq_prev:
            srv_ant_name = maq_prev.servidor.nombre if maq_prev.servidor else "otro servidor"
            hist_creacion = MaquinaHistorial(
                maquina_id=maq.id,
                snapshot_id=snapshot_id,
                campo_modificado="migracion",
                valor_anterior=f"Servidor {srv_ant_name}",
                valor_nuevo=f"VM re-detectada en nuevo servidor (Alta original: {fecha_alta.strftime('%d/%m/%Y %H:%M')})",
                detectado_en=datetime.utcnow(),
            )
        else:
            hist_creacion = MaquinaHistorial(
                maquina_id=maq.id,
                snapshot_id=snapshot_id,
                campo_modificado="creacion",
                valor_anterior="",
                valor_nuevo=f"VM Nueva {nombre_vm} creada / detectada por primera vez",
                detectado_en=datetime.utcnow(),
            )
        db.session.add(hist_creacion)
    else:
        # Chequear cruce de umbral de disco ANTES de que el loop de abajo pise
        # maq.disk_used_gb/disk_provisioned_gb con los valores nuevos.
        if "disk_used_gb" in new_data:
            _chequear_alerta_disco(maq.id, snapshot_id, maq.disk_used_gb, maq.disk_provisioned_gb,
                                    new_data.get("disk_used_gb"), new_data.get("disk_provisioned_gb"))

        # Registrar cambios en MaquinaHistorial y emitir alertas si cambiaron datos clave
        for attr, val_nuevo in new_data.items():
            if attr in ("pool", "empresa"):
                val_ant = getattr(maq, f"_{attr}_str", None) or getattr(maq, attr, None)
            else:
                val_ant = getattr(maq, attr, None)

            val_ant_str = str(val_ant or "").strip()
            val_nuevo_str = str(val_nuevo or "").strip()

            DYNAMIC_LIVE_FIELDS = {
                "usuario_asignado", "estado_horizon", "estado_vcenter",
                "ip_principal", "dns", "vcenter_host", "folder", "resource_pool",
                "datastores", "cpu_usage_mhz", "memory_usage_mb", "disk_used_gb",
                "in_error_state", "maintenance_mode",
                "estado_horizon_agente", "tools_status"
            }
            # REGLA ANTI-SOBREESCRITURA: Si ya hay información previa y la nueva es vacía, PRESERVAR existente
            # (Excepción: todos los atributos dinámicos operacionales se actualizan 100% en tiempo real)
            if val_ant_str and not val_nuevo_str and attr not in DYNAMIC_LIVE_FIELDS:
                continue

            # usuario_asignado: comparar sin importar mayúsculas/minúsculas — evita falsos
            # "cambio de usuario" en el historial cuando la fuente devuelve el mismo usuario
            # con distinta capitalización entre una extracción y la siguiente.
            if attr == "usuario_asignado":
                cambio = val_ant_str.lower() != val_nuevo_str.lower()
            else:
                cambio = val_ant_str != val_nuevo_str

            if cambio:
                # cpu_usage_mhz/memory_usage_mb son métricas de uso en vivo — fluctúan en
                # CASI TODAS las VMs encendidas en CASI CADA corrida (cada 5min). Registrarlas
                # como "cambio" en el historial inundaba el feed de Actividad/Novedades con
                # miles de filas irrelevantes, tapando eventos reales (bajas, cambio de
                # usuario). El valor en sí SÍ se sigue actualizando (columna en vivo, se ve
                # en la UI); solo se deja de auditar cada fluctuación como "evento".
                if attr not in _CAMPOS_SIN_HISTORIAL:
                    hist = MaquinaHistorial(
                        maquina_id=maq.id,
                        snapshot_id=snapshot_id,
                        campo_modificado=attr,
                        valor_anterior=val_ant_str,
                        valor_nuevo=val_nuevo_str,
                        detectado_en=datetime.utcnow(),
                    )
                    db.session.add(hist)

                if attr not in ("pool", "empresa"):
                    setattr(maq, attr, val_nuevo)

        maq.origen_id = orig_rel.id if orig_rel else None
        maq._origen_str = origen_str
        if pool_rel and (pool_str or not maq.pool_id):
            maq.pool_id = pool_rel.id
            maq._pool_str = pool_str
        if emp_rel and (empresa_str or not maq.empresa_id):
            maq.empresa_id = emp_rel.id
            maq._empresa_str = empresa_str
        maq.ultimo_snapshot_id = snapshot_id
        maq.activo = True
        maq.updated_at = datetime.utcnow()

    # Sincronización automática con DirectorioUsuario y MaquinaUsuarioDir (con vinculación de VMs y Pools)
    if maq.usuario_asignado and maq.usuario_asignado.strip():
        from web.db import MaquinaUsuarioDir, get_or_create_directorio_usuario
        dir_u = get_or_create_directorio_usuario(maq.usuario_asignado, empresa=maq.empresa)
        if dir_u:
            vinc = MaquinaUsuarioDir.query.filter_by(
                maquina_id=maq.id,
                directorio_usuario_id=dir_u.id
            ).first()
            if not vinc:
                vinc = MaquinaUsuarioDir(
                    maquina_id=maq.id,
                    directorio_usuario_id=dir_u.id,
                    tipo="principal",
                    activo=True,
                )
                db.session.add(vinc)

    return maq, is_new


def _generar_log_diagnostico_extenso(servidor_nombre: str, vms_raw: list[dict], log_callback=None):
    """
    Genera un log extenso y detallado por VM para auditar:
    - Cantidad de parámetros recibidos por VM.
    - Datos traídos (completados vs vacíos).
    - Datos adicionales recibidos del servidor que NO se guardan en la DB.
    """
    import json, os
    from datetime import datetime

    DB_FIELDS = {
        "Name": "nombre",
        "PowerState": "estado_vcenter",
        "BasicState": "estado_horizon",
        "NumCpu": "cpu",
        "MemoryGB": "ram_gb",
        "ProvisionedSpaceGB": "disk_provisioned_gb",
        "UsedSpaceGB": "disk_used_gb",
        "OS": "so",
        "OperatingSystem": "so",
        "IPAddress": "ip_principal",
        "DnsName": "dns",
        "Host": "vcenter_host",
        "Pool": "pool",
        "AssignedUser": "usuario_asignado",
        "AgentVersion": "agent_version",
        "LastPowerOnTime": "fecha_ultimo_ingreso",
        # Propiedades Extendidas vCenter & Horizon
        "Folder": "folder",
        "ResourcePool": "resource_pool",
        "Datastores": "datastores",
        "HardwareVersion": "hardware_version",
        "Annotation": "annotation",
        "ConnectionState": "connection_state",
        "CpuUsageMhz": "cpu_usage_mhz",
        "MemoryUsageMB": "memory_usage_mb",
        "InErrorState": "in_error_state",
        "MaintenanceMode": "maintenance_mode",
        "AgentState": "estado_horizon_agente",
        "ToolsStatus": "tools_status",
        "ExternalId": "external_id",
        "MachineId": "external_id",
        "DesktopType": "tipo",
        "Events": "vm_tareas_eventos",
        "EnrichmentFallas": "datos_extra_json.enrichment_fallas",
    }

    UNMAPPED_FIELDS = []

    report_vms = []
    total_params_recibidos = 0
    total_campos_completados = 0
    total_campos_vacios = 0
    total_no_mapeados = 0

    for v in vms_raw:
        vm_name = v.get("Name") or v.get("nombre") or "Sin Nombre"
        params_recibidos = list(v.keys())

        completados = []
        vacios = []
        no_mapeados = {}

        for k, val in v.items():
            val_str = str(val if val is not None else "").strip()
            if k in UNMAPPED_FIELDS or k not in DB_FIELDS:
                if k not in DB_FIELDS and k != "Name":
                    no_mapeados[k] = val
            elif val_str and val_str != "0" and val_str != "0.0":
                completados.append(f"{k} -> {val_str}")
            else:
                vacios.append(k)

        total_params_recibidos += len(params_recibidos)
        total_campos_completados += len(completados)
        total_campos_vacios += len(vacios)
        total_no_mapeados += len(no_mapeados)

        report_vms.append({
            "vm_nombre": vm_name,
            "total_parametros_recibidos": len(params_recibidos),
            "campos_db_completados_count": len(completados),
            "campos_db_vacios_count": len(vacios),
            "campos_no_mapeados_count": len(no_mapeados),
            "campos_db_completados": completados,
            "campos_db_vacios": vacios,
            "datos_servidor_no_mapeados_en_db": no_mapeados,
        })

    audit_payload = {
        "servidor": servidor_nombre,
        "fecha_auditoria": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "total_vms_evaluadas": len(vms_raw),
        "resumen": {
            "promedio_parametros_por_vm": round(total_params_recibidos / max(1, len(vms_raw)), 1),
            "total_campos_completados": total_campos_completados,
            "total_campos_vacios": total_campos_vacios,
            "total_campos_no_mapeados_en_db": total_no_mapeados,
        },
        "detalle_por_vm": report_vms
    }

    try:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(data_dir, exist_ok=True)
        
        # Un JSON por servidor (antes era un único archivo compartido que se pisaba en cada
        # servidor procesado -- en una corrida con 2 Horizon + 4 vCenter solo sobrevivía el
        # diagnóstico del último). El .log sí acumulaba bien porque ya abría en modo "a".
        servidor_slug = "".join(c if c.isalnum() else "_" for c in servidor_nombre)
        json_path = os.path.join(data_dir, f"audit_vms_diagnostico_{servidor_slug}.json")
        log_path = os.path.join(data_dir, "audit_vms_diagnostico.log")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(audit_payload, f, indent=2, ensure_ascii=False)
            
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=======================================================\n")
            f.write(f"AUDITORÍA DIAGNÓSTICA DE EXTRACCIÓN - {servidor_nombre}\n")
            f.write(f"Fecha: {audit_payload['fecha_auditoria']} | Total VMs: {len(vms_raw)}\n")
            f.write(f"Promedio Parámetros/VM: {audit_payload['resumen']['promedio_parametros_por_vm']}\n")
            f.write(f"Campos DB Completados: {total_campos_completados} | Vacíos: {total_campos_vacios}\n")
            f.write(f"Campos Servidor No Mapeados en DB: {total_no_mapeados}\n")
            f.write(f"=======================================================\n")
            for r in report_vms[:30]:
                f.write(f"\nVM: {r['vm_nombre']}\n")
                f.write(f"  Parámetros Recibidos ({r['total_parametros_recibidos']}): {', '.join(r['campos_db_completados'])}\n")
                f.write(f"  Campos Vacíos ({r['campos_db_vacios_count']}): {', '.join(r['campos_db_vacios'])}\n")
                f.write(f"  Datos Servidor No Guardados ({r['campos_no_mapeados_count']}): {r['datos_servidor_no_mapeados_en_db']}\n")

        if log_callback:
            log_callback(f"[Auditoría Diagnóstica] {len(vms_raw)} VMs inspeccionadas en {servidor_nombre}.")
            log_callback(f"[Auditoría Diagnóstica] {audit_payload['resumen']['promedio_parametros_por_vm']} parámetros/VM recogidos. {total_no_mapeados} datos de servidor no mapeados en DB.")
            log_callback(f"[Auditoría Diagnóstica] Log detallado generado en 'data/audit_vms_diagnostico.log' y 'data/audit_vms_diagnostico.json'.")
    except Exception as e:
        if log_callback:
            log_callback(f"[Auditoría Error] No se pudo escribir log extenso: {e}")


def _extraer_horizon_cred(job_id, servidor, user, password, dominio, horizon_client,
                         correcciones, base_pct, total, log, progress):
    """Extrae datos de un servidor Horizon y guarda/actualiza en DB de forma directa y ultrarrápida."""

    def hp(step, total_steps, desc):
        pct = base_pct + (step / total_steps) * (0.60 / total)
        progress(pct, f"[{servidor.nombre}] {desc}")

    # Cache SID->nombre precargada de DB: Horizon solo informa el usuario asignado
    # como SID crudo, resolverlo a nombre implica 1 llamada por SID (ver
    # HorizonRestClient._resolver_sids). Precargar lo ya conocido evita repetir esas
    # llamadas en cada corrida del scheduler para usuarios cuya asignación no cambió.
    sid_cache_previo = {r.sid: r.nombre for r in HorizonUsuarioSid.query.all()}

    datos = horizon_client.obtener_todo(
        servidor=servidor.host,
        usuario=user,
        password=password,
        dominio=dominio,
        progress_callback=hp,
        sid_cache=dict(sid_cache_previo),
    )

    sid_cache_nuevo = datos.get("sid_cache") or {}
    sids_a_guardar = {sid: nombre for sid, nombre in sid_cache_nuevo.items()
                       if sid_cache_previo.get(sid) != nombre}
    if sids_a_guardar:
        try:
            for sid, nombre in sids_a_guardar.items():
                row = HorizonUsuarioSid.query.get(sid)
                if row:
                    row.nombre = nombre
                    row.resuelto_en = datetime.utcnow()
                else:
                    db.session.add(HorizonUsuarioSid(sid=sid, nombre=nombre))
            db.session.commit()
            log(f"[{servidor.nombre}] {len(sids_a_guardar)} usuario(s) nuevo(s) resuelto(s) (SID -> nombre) y cacheado(s).")
        except Exception as e:
            # Servidores Horizon corren en paralelo (Fase 1) — si dos threads resuelven
            # el mismo SID nuevo a la vez, el segundo INSERT choca contra la PK. No es
            # fatal: la cache ya tiene el nombre en memoria para esta corrida, y la
            # próxima extracción lo va a persistir igual (el otro thread ya lo guardó).
            # Se loggea igual (antes quedaba en silencio total) para poder distinguir esta
            # colisión esperada de un error real de otro tipo si el volumen sube de golpe.
            db.session.rollback()
            log(f"[{servidor.nombre}] Cache de SIDs: colisión esperada o error al guardar ({len(sids_a_guardar)} pendientes): {e}")

    _persistir_audit_events_horizon(servidor, datos.get("audit_events", []), log)

    maquinas_raw = datos.get("maquinas", [])
    sesiones_raw = datos.get("sesiones", [])
    log(f"[{servidor.nombre}] {len(maquinas_raw)} VMs y {len(sesiones_raw)} sesiones obtenidas de Horizon.")

    refs_pool = datos.get("master_refs")
    if refs_pool:
        _master_refs_by_origen.setdefault((servidor.origen or "").lower(), set()).update(refs_pool)

    _generar_log_diagnostico_extenso(servidor.nombre, maquinas_raw, log_callback=log)

    # Crear mapa de sesiones activas/desconectadas por nombre o ID de VM
    sesion_map = {}
    for s in sesiones_raw:
        m_id = s.get("MachineId") or s.get("machine_id") or ""
        m_name = (s.get("MachineName") or s.get("MachineOrRDSServerName") or s.get("name") or "").lower().strip()
        if m_id:
            sesion_map[m_id] = s
        if m_name:
            sesion_map[m_name] = s

    # Omitir consulta GAL (Outlook) durante la extracción para máxima velocidad
    clasificacion_map = {}

    # Crear snapshot
    snap = InventarioSnapshot(
        servidor_id=servidor.id,
        total_vms=len(maquinas_raw),
        estado="completado",
    )
    db.session.add(snap)
    db.session.flush()

    vdi_count = vm_count = cambios_usuario = 0
    vms_procesadas = set()

    # Índice batch (2026-09-07) construido una sola vez para todo este servidor -- ver
    # _construir_indice_nombre_limpio(). Reemplaza el fallback O(N) por VM del matching
    # por nombre limpio en _save_or_update_maquina_impl.
    indice_maquinas = _construir_indice_nombre_limpio(servidor.id)

    for m in maquinas_raw:
        if not isinstance(m, dict):
            continue
        nombre_vm        = m.get("Name", "")
        nombre_vm_lower  = nombre_vm.lower().strip()
        # Bug real encontrado 2026-08-13: core/horizon_rest.py YA arma "Session" por máquina
        # con el matching correcto (sessions_map por machine_id/nombre, hecho ahí mismo con
        # datos frescos) -- pero acá se ignoraba y se reconstruía sesion_map desde cero por
        # NOMBRE de máquina, campo que en el payload real de sessions viene vacío ("machine_name"
        # no existe, solo "machine_id"). Resultado: s_info quedaba {} siempre, client_ip/gateway
        # nunca se guardaban aunque el fetch los traía bien. m.get("Session") ya resuelto tiene
        # prioridad; sesion_map queda de fallback por si algún día no viene embebido.
        s_info           = m.get("Session") or sesion_map.get(nombre_vm_lower) or (sesion_map.get(m.get("id")) if m.get("id") else {}) or {}

        usuario_asignado = m.get("AssignedUser", "")
        user_session     = s_info.get("UserName", "")
        if not usuario_asignado and user_session:
            usuario_asignado = user_session

        assigned_clean   = usuario_asignado.lower().strip()
        if "\\" in assigned_clean:
            assigned_clean = assigned_clean.split("\\")[-1]
        clas = clasificacion_map.get(assigned_clean, {})

        pool = m.get("Pool", "")
        tipo = _clasificar_tipo(servidor, pool)
        if tipo == "VDI":
            vdi_count += 1
        else:
            vm_count += 1

        empresa_nueva    = clas.get("empresa", "")
        vms_procesadas.add(nombre_vm)

        prev_maq = Maquina.query.filter_by(servidor_id=servidor.id, nombre=nombre_vm).first()
        prev_user = prev_maq.usuario_asignado if prev_maq else ""
        prev_empresa = prev_maq.empresa if prev_maq else ""

        ip_cand = m.get("IPAddress", "") or m.get("ipAddress", "")
        dns_cand = m.get("DnsName", "")
        if not ip_cand and dns_cand:
            try:
                import socket
                host_only = dns_cand.split()[0].strip()
                if host_only:
                    ip_cand = socket.gethostbyname(host_only)
            except Exception:
                pass

        # Estado Horizon: prioridad a la sesión en vivo (CONNECTED / DISCONNECTED)
        estado_session = s_info.get("SessionState", "") or s_info.get("State", "")
        basic_st = m.get("BasicState", "")
        if estado_session:
            estado_horizon = estado_session.upper()
        elif basic_st:
            estado_horizon = basic_st.upper()
        else:
            # Sin default falso (auditoría 2026-08-12, mismo bug que core/horizon_rest.py):
            # sin sesión y sin BasicState, mejor vacío que asumir "AVAILABLE".
            estado_horizon = ""

        datos_extra_h = {
            "InErrorState": m.get("InErrorState"),
            "MaintenanceMode": m.get("MaintenanceMode"),
            "AgentState": m.get("AgentState"),
            # Prioridad 2026-08-13: ya se pedía a la API de sesiones pero se descartaba
            # antes de persistir (ver web/db.py Maquina.client_ip). Última sesión conocida,
            # no se limpia si ahora no hay sesión activa (no está en DYNAMIC_LIVE_FIELDS).
            "client_ip": s_info.get("ClientIP"),
            "client_name": s_info.get("ClientName"),
            "gateway_ip": s_info.get("GatewayIP"),
            "gateway_name": s_info.get("GatewayName"),
            "gateway_location": s_info.get("GatewayLocation"),
            # Agregados 2026-09-07 -- mismo criterio que client_ip/gateway arriba: ya
            # venían en s_info (core/horizon_rest.py), se descartaban antes de persistir.
            "client_type": s_info.get("ClientType"),
            "client_version": s_info.get("ClientVersion"),
            "session_protocol": s_info.get("SessionProtocol"),
            "session_type": s_info.get("SessionType"),
            "session_idle_seconds": s_info.get("SessionIdleSeconds"),
        }

        maq, is_new = _save_or_update_maquina(
            servidor_id=servidor.id,
            snapshot_id=snap.id,
            nombre_vm=nombre_vm,
            tipo=tipo,
            origen_str=servidor.origen,
            pool_str=pool,
            empresa_str=empresa_nueva,
            usuario_asignado=usuario_asignado,
            estado_horizon=estado_horizon,
            estado_vcenter=None,
            manager=clas.get("manager_name", ""),
            agent_version=m.get("AgentVersion", ""),
            so=m.get("OperatingSystem", ""),
            cpu=_safe_int(m.get("NumCPU")),
            ram_gb=_safe_float(m.get("MemoryGB")),
            disk_gb=_safe_float(m.get("DiskGB")),
            dns=dns_cand,
            ip=ip_cand,
            vcenter_host=None,
            correcciones=correcciones,
            datos_extra=datos_extra_h,
            indice_nombre_limpio=indice_maquinas,
        )

        # Actualizar fecha de último ingreso si viene timestamp de inicio de sesión
        start_time = s_info.get("StartTime", "")
        if start_time:
            maq.fecha_ultimo_ingreso = _normalizar_fecha_ingreso(start_time)

        hubo_cambio = detectar_cambio_usuario(
            nombre_vm        = nombre_vm,
            usuario_anterior = prev_user or None,
            usuario_nuevo    = maq.usuario_asignado or None,
            snapshot_id      = snap.id,
            servidor_id      = servidor.id,
            pool             = maq.pool,
            origen           = maq.origen,
            tipo             = maq.tipo,
            empresa_anterior = prev_empresa or None,
            empresa_nueva    = maq.empresa or None,
            estado_horizon   = maq.estado_horizon,
            maquina_id       = maq.id,
        )
        if hubo_cambio:
            cambios_usuario += 1

    # Desactivar VMs no detectadas en este snapshot
    for maq_ant in Maquina.query.filter_by(servidor_id=servidor.id, activo=True).all():
        if maq_ant.nombre not in vms_procesadas:
            maq_ant.activo = False
            hist_del = MaquinaHistorial(
                maquina_id=maq_ant.id,
                snapshot_id=snap.id,
                campo_modificado="eliminacion",
                valor_anterior="Activo",
                valor_nuevo=f"VM {maq_ant.nombre} dada de baja",
                detectado_en=datetime.utcnow(),
            )
            db.session.add(hist_del)

    snap.total_vdi = vdi_count
    snap.total_vm  = vm_count
    db.session.commit()
    log(f"[{servidor.nombre}] Guardado: {vdi_count} VDI + {vm_count} VM. "
        f"Cambios de usuario detectados: {cambios_usuario}.")

    # Persistir Pools y Autorizaciones (Locales & Globales)
    try:
        _guardar_pools_y_autorizaciones_horizon(servidor, datos)
        log(f"[{servidor.nombre}] Autorizaciones locales y globales de pools sincronizadas.")
    except Exception as ex_p:
        log(f"[{servidor.nombre}] ⚠️ Error guardando autorizaciones de pools: {ex_p}")

    # Persistir Granja RDS (Farms, Application Pools, Autorizaciones, RDS Servers)
    try:
        _guardar_granja_horizon(servidor, datos)
        log(f"[{servidor.nombre}] Granja RDS (Farms/Apps/Autorizaciones) sincronizada.")
    except Exception as ex_g:
        log(f"[{servidor.nombre}] ⚠️ Error guardando Granja RDS: {ex_g}")


def _guardar_pools_y_autorizaciones_horizon(servidor, datos_raw: dict):
    """
    Persiste en la DB (tablas Pool y PoolEntitlement) las pools y autorizaciones (locales y globales)
    extraídas de Horizon View.
    """
    if not datos_raw:
        return

    from web.db import Pool, PoolEntitlement, db
    from datetime import datetime

    with _db_write_lock:
        with db.session.no_autoflush:
            # 1. Guardar/Actualizar Pools
            pools_raw = datos_raw.get("pools", [])
            vistas = set()
            for p_info in pools_raw:
                p_name = p_info.get("Name") or p_info.get("name")
                if not p_name:
                    continue
                vistas.add(p_name)
                p_db = Pool.query.filter_by(nombre=p_name).first()
                if not p_db:
                    p_db = Pool(nombre=p_name)
                    db.session.add(p_db)

                p_db.display_name = p_info.get("DisplayName") or p_info.get("displayName") or p_name
                p_db.tipo = p_info.get("Type") or p_info.get("type") or "Automated"
                p_db.user_assignment = p_info.get("UserAssignment") or p_info.get("userAssignment") or "Dedicated"
                p_db.enabled = p_info.get("Enabled") if p_info.get("Enabled") is not None else True
                p_db.activo = True
                p_db.origen = servidor.origen
                nuevo_moref = p_info.get("ParentVmId")
                if nuevo_moref:
                    p_db.master_moref = nuevo_moref

                # Alerta solo si el error cambia (aparece, cambia de mensaje, o se resuelve)
                # — no en cada corrida con el mismo error sin resolver.
                error_nuevo = p_info.get("ProvisioningError") or ""
                error_ant = p_db.provisioning_error or ""
                if error_nuevo != error_ant:
                    from web.db import InfraEvento
                    db.session.add(InfraEvento(
                        tipo="pool_provisioning_error" if error_nuevo else "pool_provisioning_resuelto",
                        entidad_nombre=p_name,
                        servidor_id=servidor.id,
                        valor_anterior=error_ant or "—",
                        valor_nuevo=error_nuevo or "OK",
                        mensaje=error_nuevo or f"Pool {p_name} recuperado — dejó de tener error de provisioning.",
                        detectado_en=datetime.utcnow(),
                    ))
                    p_db.provisioning_error = error_nuevo

                p_db.updated_at = datetime.utcnow()

            # Desactivar pools de este origen que ya no aparecen — antes se acumulaban
            # para siempre (nombre 'nombre_vm' un usuario borra una pool en Horizon
            # Console y acá seguía figurando como si existiera, sin límite de tiempo).
            if vistas:
                from web.db import InfraEvento
                for p_db in Pool.query.filter_by(origen=servidor.origen, activo=True).all():
                    if p_db.nombre not in vistas:
                        p_db.activo = False
                        db.session.add(InfraEvento(
                            tipo="pool_eliminado",
                            entidad_nombre=p_db.nombre,
                            servidor_id=servidor.id,
                            valor_anterior="Activa",
                            valor_nuevo="Eliminada",
                            mensaje=f"Pool {p_db.nombre} ya no existe en Horizon — se desactivó del inventario.",
                            detectado_en=datetime.utcnow(),
                        ))

            db.session.commit()

            # Mapa de nombre_pool -> id (solo activas — no atar entitlements a pools fantasma)
            pool_map = {p.nombre: p.id for p in Pool.query.filter_by(activo=True).all()}

            # 2. Guardar Entitlements Locales
            ent_locales = datos_raw.get("entitlements_locales", [])
            for el in ent_locales:
                pool_name = el.get("PoolName") or el.get("poolName") or ""
                usr_group = el.get("UserOrGroup") or el.get("userOrGroup") or ""
                if not pool_name or not usr_group:
                    continue

                p_id = pool_map.get(pool_name)
                es_grp = el.get("IsGroup", False)

                existe = PoolEntitlement.query.filter_by(
                    pool_nombre=pool_name,
                    usuario_o_grupo=usr_group,
                    tipo_entitlement="Local"
                ).first()

                if not existe:
                    item_ent = PoolEntitlement(
                        pool_id=p_id,
                        pool_nombre=pool_name,
                        usuario_o_grupo=usr_group,
                        tipo_entitlement="Local",
                        es_grupo=bool(es_grp),
                        servidor_id=servidor.id,
                        origen=servidor.origen,
                    )
                    db.session.add(item_ent)

            # 3. Guardar Entitlements Globales
            ent_globales = datos_raw.get("entitlements_globales", [])
            for eg in ent_globales:
                ge_name = eg.get("GlobalEntitlementName") or eg.get("PoolName") or "Global Entitlement"
                usr_group = eg.get("UserOrGroup") or eg.get("userOrGroup") or ""
                if not usr_group:
                    continue

                p_id = pool_map.get(ge_name)
                es_grp = eg.get("IsGroup", False)

                existe = PoolEntitlement.query.filter_by(
                    pool_nombre=ge_name,
                    usuario_o_grupo=usr_group,
                    tipo_entitlement="Global"
                ).first()

                if not existe:
                    item_ent = PoolEntitlement(
                        pool_id=p_id,
                        pool_nombre=ge_name,
                        usuario_o_grupo=usr_group,
                        tipo_entitlement="Global",
                        es_grupo=bool(es_grp),
                        servidor_id=servidor.id,
                        origen=servidor.origen,
                    )
                    db.session.add(item_ent)

            db.session.commit()


def _guardar_granja_horizon(servidor, datos_raw: dict):
    """
    Persiste en la DB (tablas Farm, AplicacionPublicada, AplicacionEntitlement,
    FarmRdsServer) las granjas RDS, aplicaciones publicadas, autorizaciones y RDS
    Servers extraídos de Horizon View. Mismo patrón que
    _guardar_pools_y_autorizaciones_horizon. Además enlaza Pool.farm_id para los
    desktop pools tipo RDS de este origen (fusiona el Pool RDS existente con su Farm real).
    """
    if not datos_raw:
        return

    with _db_write_lock:
        with db.session.no_autoflush:
            # 1. Guardar/Actualizar Farms
            farms_raw = datos_raw.get("farms", [])
            farms_vistas = set()
            for f_info in farms_raw:
                f_name = f_info.get("Name") or f_info.get("name")
                if not f_name:
                    continue
                farms_vistas.add(f_name)
                f_db = Farm.query.filter_by(nombre=f_name).first()
                if not f_db:
                    f_db = Farm(nombre=f_name)
                    db.session.add(f_db)

                f_db.display_name = f_info.get("DisplayName") or f_name
                f_db.tipo = f_info.get("Type") or "AUTOMATED"
                f_db.horizon_farm_id = str(f_info.get("Id")) if f_info.get("Id") is not None else None
                f_db.rds_server_max_sessions = f_info.get("RdsServerMaxSessions")
                f_db.enabled = f_info.get("Enabled") if f_info.get("Enabled") is not None else True
                f_db.provisioning_error = f_info.get("ProvisioningError") or ""
                f_db.activo = True
                f_db.origen = servidor.origen
                f_db.servidor_id = servidor.id
                f_db.updated_at = datetime.utcnow()

            db.session.commit()

            farm_id_map = {}
            for f_db in Farm.query.filter_by(origen=servidor.origen, activo=True).all():
                if f_db.nombre not in farms_vistas:
                    f_db.activo = False
                else:
                    farm_id_map[f_db.nombre] = f_db.id

            # 2. Guardar/Actualizar Application Pools (aplicaciones publicadas)
            apps_raw = datos_raw.get("application_pools", [])
            apps_vistas = set()
            for a_info in apps_raw:
                a_name = a_info.get("Name") or a_info.get("name")
                if not a_name:
                    continue
                apps_vistas.add(a_name)
                a_db = AplicacionPublicada.query.filter_by(nombre=a_name).first()
                if not a_db:
                    a_db = AplicacionPublicada(nombre=a_name)
                    db.session.add(a_db)

                a_db.display_name = a_info.get("DisplayName") or a_name
                a_db.farm_id = farm_id_map.get(a_info.get("FarmName") or "")
                a_db.path_ejecutable = a_info.get("ExecutablePath") or ""
                a_db.enabled = a_info.get("Enabled") if a_info.get("Enabled") is not None else True
                a_db.activo = True
                a_db.origen = servidor.origen
                a_db.servidor_id = servidor.id
                a_db.updated_at = datetime.utcnow()

            db.session.commit()

            app_id_map = {}
            for a_db in AplicacionPublicada.query.filter_by(origen=servidor.origen, activo=True).all():
                if a_db.nombre not in apps_vistas:
                    a_db.activo = False
                else:
                    app_id_map[a_db.nombre] = a_db.id

            # 3. Guardar Entitlements de Aplicaciones (Local y Global -- mismo patrón que
            #    PoolEntitlement en _guardar_pools_y_autorizaciones_horizon)
            for tipo_ent, key_raw in (("Local", "app_entitlements_locales"), ("Global", "app_entitlements_globales")):
                for e in datos_raw.get(key_raw, []):
                    a_name = e.get("AplicacionNombre") or e.get("aplicacion_nombre") or ""
                    usr_group = e.get("UserOrGroup") or e.get("userOrGroup") or ""
                    if not a_name or not usr_group:
                        continue

                    existe = AplicacionEntitlement.query.filter_by(
                        aplicacion_nombre=a_name,
                        usuario_o_grupo=usr_group,
                        tipo_entitlement=tipo_ent,
                    ).first()
                    if existe:
                        continue

                    db.session.add(AplicacionEntitlement(
                        aplicacion_id=app_id_map.get(a_name),
                        aplicacion_nombre=a_name,
                        usuario_o_grupo=usr_group,
                        tipo_entitlement=tipo_ent,
                        es_grupo=bool(e.get("IsGroup", False)),
                        servidor_id=servidor.id,
                        origen=servidor.origen,
                    ))

            # 4. Guardar/Actualizar RDS Servers de cada Farm
            rds_raw = datos_raw.get("rds_servers", [])
            rds_vistos = set()
            for rs_info in rds_raw:
                rs_name = rs_info.get("Name") or rs_info.get("name")
                f_id = farm_id_map.get(rs_info.get("FarmName") or "")
                if not rs_name or not f_id:
                    continue
                rds_vistos.add((f_id, rs_name))
                rs_db = FarmRdsServer.query.filter_by(farm_id=f_id, nombre=rs_name).first()
                if not rs_db:
                    rs_db = FarmRdsServer(farm_id=f_id, nombre=rs_name)
                    db.session.add(rs_db)

                rs_db.estado = rs_info.get("Estado") or ""
                rs_db.sesiones_activas = rs_info.get("SesionesActivas") or 0
                rs_db.enabled = rs_info.get("Enabled") if rs_info.get("Enabled") is not None else True
                rs_db.activo = True
                rs_db.origen = servidor.origen
                rs_db.servidor_id = servidor.id
                rs_db.updated_at = datetime.utcnow()

            for rs_db in FarmRdsServer.query.filter_by(origen=servidor.origen, activo=True).all():
                if (rs_db.farm_id, rs_db.nombre) not in rds_vistos:
                    rs_db.activo = False

            # 5. Enlazar Pool.farm_id para desktop pools tipo RDS de este origen -- fusiona
            #    el Pool RDS ya existente (ej. RDS_Desktop/POC_RDS) con su Farm real.
            for p_info in datos_raw.get("pools", []):
                p_farm_id_raw = p_info.get("FarmId") or p_info.get("farm_id")
                p_name = p_info.get("Name") or p_info.get("name")
                if not p_farm_id_raw or not p_name:
                    continue
                p_db = Pool.query.filter_by(nombre=p_name).first()
                if not p_db:
                    continue
                farm_match = Farm.query.filter_by(horizon_farm_id=str(p_farm_id_raw)).first()
                if farm_match:
                    p_db.farm_id = farm_match.id

            db.session.commit()


def _guardar_tareas_eventos_vcenter(maquina_id: int, events_raw):
    """
    Persiste en la tabla VMTareaEvento los eventos y tareas de la sección Supervisar (Monitor)
    de vCenter, previniendo duplicados. Soporta dict único o list[dict].
    """
    if not maquina_id or not events_raw:
        return

    # Si events_raw es un único diccionario (1 evento), convertir a lista
    if isinstance(events_raw, dict):
        events_raw = [events_raw]
    elif not isinstance(events_raw, list):
        return

    from web.db import VMTareaEvento
    from datetime import datetime

    # Batch (2026-09-07): antes se hacía 1 query de deduplicación POR EVENTO (indexada
    # por maquina_id, pero igual N consultas por VM en vez de 1 -- con miles de eventos
    # por corrida, sumaba). Ahora se trae una sola vez el set de eventos ya existentes
    # de ESTA máquina y se chequea en memoria. Si esto da problemas, comentar este bloque
    # y descomentar el `existe = VMTareaEvento.query...` de más abajo (código viejo
    # dejado comentado a propósito para un rollback en caliente sin buscar en el
    # historial de git).
    existentes = {
        (e.nombre_evento, e.fecha)
        for e in VMTareaEvento.query.filter_by(maquina_id=maquina_id).all()
    }

    for ev in events_raw:
        if not isinstance(ev, dict):
            continue
        n_evt = ev.get("nombre_evento") or ev.get("name") or "vCenterEvent"
        msg = ev.get("mensaje") or ev.get("message") or ""
        # Sin default falso (auditoría 2026-08-12): "vCenter" como usuario fabricaba un actor
        # que nunca ejecutó la acción. Vacío en vez de inventar quién lo hizo.
        usr = ev.get("usuario") or ev.get("user") or ""
        tipo_str = ev.get("tipo") or ("task" if "Task" in n_evt else "evento")
        dt_raw = ev.get("fecha")

        # fecha es NOT NULL (no se puede dejar en None) -- si no viene o no parsea, se usa
        # la hora de la corrida PERO se marca en el mensaje para que no quede indistinguible
        # de una fecha real del evento (auditoría 2026-08-12).
        dt_obj = datetime.utcnow()
        fecha_estimada = True
        if dt_raw:
            try:
                dt_obj = datetime.strptime(str(dt_raw)[:19], "%Y-%m-%d %H:%M:%S")
                fecha_estimada = False
            except Exception:
                pass
        if fecha_estimada and "[fecha estimada]" not in msg:
            msg = f"{msg} [fecha estimada, no informada por vCenter]".strip()

        # Evitar duplicados por máquina + fecha + nombre_evento -- chequeo en memoria
        # contra `existentes` (ver arriba). Código viejo, 1 query por evento, dejado
        # comentado para rollback rápido si hiciera falta:
        # existe = VMTareaEvento.query.filter_by(
        #     maquina_id=maquina_id, nombre_evento=n_evt, fecha=dt_obj
        # ).first()
        clave_evt = (n_evt, dt_obj)

        if clave_evt not in existentes:
            st = "info"
            n_lower = n_evt.lower()
            if "error" in n_lower or "failed" in n_lower or "alarm" in n_lower:
                st = "error"
            elif "warning" in n_lower or "reset" in n_lower or "remove" in n_lower:
                st = "warning"
            elif "success" in n_lower or "create" in n_lower or "poweron" in n_lower:
                st = "success"

            item_evt = VMTareaEvento(
                maquina_id=maquina_id,
                tipo=tipo_str,
                nombre_evento=n_evt,
                mensaje=msg,
                usuario=usr,
                estado=st,
                fecha=dt_obj,
            )
            db.session.add(item_evt)
            existentes.add(clave_evt)


def _vincular_farm_rds_server(origen: str, nombre_vm: str, maquina_id: int):
    """Si nombre_vm matchea un FarmRdsServer pendiente (maquina_id IS NULL) de este
    origen, lo enlaza a la Maquina real de vCenter -- mismo criterio de matching por
    nombre que ya usa _master_refs_by_origen para masters, pero consultando la tabla
    directamente (FarmRdsServer ya está en DB desde la Fase 1, no hace falta cachear en
    memoria como con los master_refs crudos de Horizon)."""
    if not nombre_vm:
        return
    rs_db = FarmRdsServer.query.filter(
        FarmRdsServer.origen == (origen or ""),
        FarmRdsServer.activo == True,
        FarmRdsServer.maquina_id.is_(None),
        func.lower(FarmRdsServer.nombre) == nombre_vm.lower().strip(),
    ).first()
    if rs_db:
        rs_db.maquina_id = maquina_id


def _extraer_vcenter_cred(job_id, servidor, user, password, dominio, vcenter_client,
                         correcciones, base_pct, total, log, progress):
    """Extrae VMs de un servidor vCenter y guarda/actualiza en DB.
    
    MERGE Horizon↔vCenter: si una VM ya existe en un servidor Horizon (por nombre),
    se enriquece esa máquina con datos de vCenter (IP, host, CPU, RAM, disco, PowerState)
    en lugar de crear un duplicado.
    """

    def vp(step, total_steps, desc):
        pct = base_pct + (step / total_steps) * (0.60 / total)
        progress(pct, f"[{servidor.nombre}] {desc}")

    resultado_vc = vcenter_client.obtener_vms(
        servidor=servidor.host,
        usuario=user,
        password=password,
        dominio=dominio,
        progress_callback=vp,
    )
    vms_raw = resultado_vc.get("vms", [])
    _guardar_infra_datastores_hosts(servidor, resultado_vc.get("hosts", []), resultado_vc.get("datastores", []), log)

    # Annotation/Notes real: la REST API no lo expone (ver core/vcenter_rest.py), se lee
    # aparte por SOAP en un único bulk call (PropertyCollector, no per-VM). Best-effort:
    # si falla (SOAP deshabilitado, credencial sin permiso, etc.) se sigue sin anotaciones
    # reales en vez de abortar la extracción completa por un campo secundario.
    annotations_vc = {}
    try:
        from core.vcenter_soap import obtener_annotations
        annotations_vc = obtener_annotations(servidor.host, user, password, dominio)
        log(f"[{servidor.nombre}] {len(annotations_vc)} anotaciones reales leídas de vCenter vía SOAP.")
    except Exception as e:
        log(f"[{servidor.nombre}] ⚠️ No se pudieron leer anotaciones vía SOAP: {e}")

    # Carpeta real de vCenter (árbol de inventario, 2026-09-04): mismo criterio best-effort
    # que Annotation -- si SOAP falla, la vista del árbol cae sola a la agrupación por
    # pool/categoría (ver /api/inventario/arbol), no rompe la extracción.
    folders_vc = {}
    try:
        from core.vcenter_soap import obtener_folders
        folders_vc = obtener_folders(servidor.host, user, password, dominio)
        log(f"[{servidor.nombre}] {len(folders_vc)} carpetas reales leídas de vCenter vía SOAP.")
    except Exception as e:
        log(f"[{servidor.nombre}] ⚠️ No se pudieron leer carpetas vía SOAP: {e}")

    # Resource Pool real (2026-09-07): la vía REST siempre lo dejaba en '' (ver
    # core/vcenter_rest.py) -- mismo criterio best-effort que folders/annotations arriba.
    resource_pools_vc = {}
    try:
        from core.vcenter_soap import obtener_resource_pools
        resource_pools_vc = obtener_resource_pools(servidor.host, user, password, dominio)
        log(f"[{servidor.nombre}] {len(resource_pools_vc)} resource pools reales leídos de vCenter vía SOAP.")
    except Exception as e:
        log(f"[{servidor.nombre}] ⚠️ No se pudieron leer resource pools vía SOAP: {e}")

    # Topología de cómputo real Datacenter/Cluster/Host (2026-09-07) -- vista "Cómputo"
    # del Árbol vCenter, alternativa a la vista "Carpetas" (folders_vc arriba). Mismo
    # criterio best-effort.
    topologia_computo_vc = {}
    try:
        from core.vcenter_soap import obtener_topologia_computo
        topologia_computo_vc = obtener_topologia_computo(servidor.host, user, password, dominio)
        log(f"[{servidor.nombre}] {len(topologia_computo_vc)} rutas de cómputo reales leídas de vCenter vía SOAP.")
    except Exception as e:
        log(f"[{servidor.nombre}] ⚠️ No se pudo leer topología de cómputo vía SOAP: {e}")

    # Eventos y tareas reales de vCenter (2026-09-07) -- reemplaza el "Events": []
    # hardcodeado de core/vcenter_rest.py, que nunca trajo datos reales (VMTareaEvento
    # llevaba desde agosto sin filas nuevas). Incremental por servidor.
    #
    # Cursor: Servidor.eventos_sync_hasta, marcador EXPLÍCITO ("hasta cuándo ya pedí"),
    # no inferido de MAX(VMTareaEvento.fecha) -- 2 bugs reales encontrados con 2
    # extracciones reales seguidas usando esa idea:
    #   1) Global (sin scope por servidor): con las 4 fases vCenter en paralelo, el
    #      servidor más rápido en escribir eventos (SU/Core, pocas VMs) adelantaba el
    #      máximo GLOBAL a "ahora", y el siguiente en leerlo (MZ/DT, muchas VMs, tarda
    #      más) heredaba ese "ahora" como piso sin haber traído su propio backlog.
    #   2) Aunque se scopee por servidor, sigue distorsionado por una sola VM con
    #      actividad muy reciente: confirmado en vivo, 1 VM de VCenter DT con 217
    #      eventos en 40 minutos adelantó lo que hubiera sido el "máximo del servidor"
    #      a hoy, tapando el backlog real de las otras 587 VMs de ese vCenter.
    # Por eso el cursor no sale de los datos guardados en absoluto -- se guarda aparte.
    # Si el fetch se corta por el techo de tiempo/páginas (ver obtener_eventos_tareas),
    # el cursor NO avanza hasta "ahora" -- avanza solo hasta el evento más viejo
    # realmente visto, para no dejar un agujero permanente en la parte del backlog que
    # todavía no se llegó a pedir (se completa solo, de a poco, en corridas siguientes).
    eventos_reales_vc = {}
    try:
        from core.vcenter_soap import obtener_eventos_tareas
        piso_45d = datetime.utcnow() - timedelta(days=45)
        desde_eventos = servidor.eventos_sync_hasta if (servidor.eventos_sync_hasta and servidor.eventos_sync_hasta > piso_45d) else piso_45d
        momento_fetch = datetime.utcnow()
        resultado_eventos = obtener_eventos_tareas(servidor.host, user, password, dominio, desde=desde_eventos)
        eventos_reales_vc = resultado_eventos["por_vm"]
        nuevo_cursor = momento_fetch if resultado_eventos["completo"] else resultado_eventos["cursor_hasta"]
        # _db_write_lock: mismo criterio que _save_or_update_maquina -- este commit
        # corre en paralelo desde varios hilos (uno por servidor vCenter), sin serializar
        # generaría el mismo "database is locked" esporádico que ese lock ya evita ahí.
        _db_write_lock.acquire()
        try:
            if nuevo_cursor:
                servidor.eventos_sync_hasta = nuevo_cursor
                db.session.commit()
        finally:
            _db_write_lock.release()
        total_eventos_nuevos = sum(len(v) for v in eventos_reales_vc.values())
        parcial = "" if resultado_eventos["completo"] else " (CORTADO por techo de tiempo/páginas, se completa en próximas corridas)"
        log(f"[{servidor.nombre}] {total_eventos_nuevos} eventos/tareas reales leídos de vCenter vía SOAP "
            f"(desde {desde_eventos.strftime('%Y-%m-%d %H:%M')}) para {len(eventos_reales_vc)} VM(s).{parcial}")
    except Exception as e:
        log(f"[{servidor.nombre}] ⚠️ No se pudieron leer eventos/tareas vía SOAP: {e}")

    total_evts_recibidos = sum(len(evs) for evs in eventos_reales_vc.values())
    log(f"[{servidor.nombre}] {len(vms_raw)} VMs obtenidas de vCenter ({total_evts_recibidos} eventos/tareas recolectados).")
    _generar_log_diagnostico_extenso(servidor.nombre, vms_raw, log_callback=log)

    from web.db import Servidor as SrvModel
    # Acotado al MISMO origen que este vCenter (ej. solo Horizon 'dt' si servidor.origen=='dt') --
    # antes tomaba TODOS los servidores Horizon activos sin importar el origen. Con varios
    # sitios/pods (dt/mz/su/core), dos VMs de origen distinto pueden tener el mismo nombre
    # limpio y la última pisaba a la primera en el dict, mezclando datos de una VM con otra.
    # También evita colisión de external_id: un MoRef como "vm-511" es único DENTRO de un
    # vCenter, no entre vCenters distintos -- mezclar orígenes acá podía matchear una VM de
    # este vCenter contra el Maquina equivocado de otro pod con el mismo MoRef numérico.
    # Bug real encontrado 2026-08-12 (rastreado hasta 2026-08-07 vía MaquinaHistorial):
    # Servidor.origen es una @property de Python (ver web/db.py), NO una columna mapeada --
    # filter_by(origen=...) nunca matchea nada contra ningún valor, da lista vacía siempre.
    # Resultado: horizon_srv_ids quedaba [] en TODAS las corridas, horizon_maquinas vacío,
    # y el 99% de la flota caía a la rama "sin match" (estado_horizon="N/A (vCenter)")
    # pisando el estado real que Horizon acababa de escribir. Fix: filtrar por la columna
    # real _origen_str (mismo patrón que Maquina._origen_str en otros lados del código).
    horizon_srv_ids = [
        s.id for s in SrvModel.query.filter_by(tipo="horizon", activo=True, _origen_str=servidor.origen).all()
    ]
    horizon_maquinas: dict[str, "Maquina"] = {}
    colisiones = 0
    if horizon_srv_ids:
        for maq_h in Maquina.query.filter(
            Maquina.servidor_id.in_(horizon_srv_ids),
            Maquina.activo == True
        ).all():
            for clave in (maq_h.nombre.lower(), _clean_vm_name(maq_h.nombre), maq_h.external_id):
                if not clave:
                    continue
                existente = horizon_maquinas.get(clave)
                if existente is not None and existente.id != maq_h.id:
                    colisiones += 1
                horizon_maquinas[clave] = maq_h

    if colisiones:
        log(f"[{servidor.nombre}] ⚠️ {colisiones} colisión(es) de nombre/MoRef detectadas armando el "
            f"índice de matching Horizon (mismo origen '{servidor.origen}') -- revisar VMs con nombres duplicados.")
    log(f"[{servidor.nombre}] {len(horizon_maquinas)} índices de Horizon disponibles para match (origen '{servidor.origen}').")

    snap = InventarioSnapshot(
        servidor_id=servidor.id,
        total_vms=len(vms_raw),
        estado="completado",
    )
    db.session.add(snap)
    db.session.flush()

    vdi_count = vm_count = 0
    vms_procesadas = set()
    merged_count = 0
    _con_disco_real = 0  # diagnóstico temporal 2026-08-12: confirmar si esto llega en vivo igual que en pruebas aisladas

    # Índice batch (2026-09-07), ver _construir_indice_nombre_limpio() y el comentario
    # equivalente en _extraer_horizon_cred. Solo se usa en la rama "sin match Horizon"
    # (creación de VM_ESTATICA) más abajo -- la rama con match ya tiene su propio índice
    # por origen (horizon_maquinas) y no pasa por este fallback.
    indice_maquinas_vc = _construir_indice_nombre_limpio(servidor.id)

    for v in vms_raw:
        if not isinstance(v, dict):
            continue
        nombre_vm = v.get("Name", "")
        if not nombre_vm:
            continue
        vms_procesadas.add(nombre_vm)

        ip           = v.get("IPAddress", "")
        vcenter_host = v.get("Host", "")
        cpu          = _safe_int(v.get("NumCpu"))
        ram_gb       = _safe_float(v.get("MemoryGB"))
        disk_gb      = _safe_float(v.get("ProvisionedSpaceGB"))
        disk_used_gb = _safe_float(v.get("UsedSpaceGB", v.get("DiskUsedGB")))
        if disk_gb:
            _con_disco_real += 1
        so           = v.get("OS", "")
        dns          = v.get("DnsName", "")
        power_state    = v.get("PowerState", "")
        last_power_on  = v.get("LastPowerOnTime", "")

        ext_id = v.get("ExternalId")
        annotation_real = annotations_vc.get(ext_id, "") if ext_id else ""
        folder_real = folders_vc.get(ext_id, "") if ext_id else ""
        resource_pool_real = resource_pools_vc.get(ext_id, "") if ext_id else ""
        ruta_computo_real = topologia_computo_vc.get(ext_id, "") if ext_id else ""
        clean_v_name = _clean_vm_name(nombre_vm)
        cand_horizon = (
            (horizon_maquinas.get(ext_id) if ext_id else None)
            or horizon_maquinas.get(nombre_vm.lower())
            or horizon_maquinas.get(clean_v_name)
        )
        maq_horizon = cand_horizon

        datos_extra_vc = {
            "folder": folder_real,
            "ruta_computo": ruta_computo_real,
            "resource_pool": resource_pool_real or v.get("ResourcePool"),
            "datastores": v.get("Datastores"),
            "hardware_version": v.get("HardwareVersion"),
            "annotation": annotation_real,
            "connection_state": v.get("ConnectionState"),
            "cpu_usage_mhz": v.get("CpuUsageMhz"),
            "memory_usage_mb": v.get("MemoryUsageMB"),
            "external_id": v.get("ExternalId"),
            "es_template": v.get("EsTemplate", False),
            "tools_status": v.get("ToolsStatus"),
            # Agregados 2026-09-07 -- ver Maquina en web/db.py para el detalle de cada uno.
            "hardware_upgrade_status": v.get("HardwareUpgradeStatus"),
            "cpu_cores_per_socket": v.get("CpuCoresPerSocket"),
            "cpu_hot_add_enabled": v.get("CpuHotAddEnabled"),
            "memory_hot_add_enabled": v.get("MemoryHotAddEnabled"),
            "boot_firmware": v.get("BootFirmware"),
            "secure_boot_enabled": v.get("SecureBootEnabled"),
            # Campos de guest-ops que quedaron sin datos frescos tras el pase 1 paralelo Y
            # los 2 intentos secuenciales del pase 2 (ver core/vcenter_rest.py) -- visible acá
            # en vez de perderse silenciosamente para poder distinguir "esta VM nunca tuvo
            # esos datos" de "vCenter no contestó esta corrida, reintentar la próxima".
            "enrichment_fallas": v.get("EnrichmentFallas"),
        }

        if maq_horizon:
            campos_vcenter = {
                "ip_principal":        ip          or maq_horizon.ip_principal,
                "vcenter_host":        vcenter_host or maq_horizon.vcenter_host,
                "estado_vcenter":      power_state  or maq_horizon.estado_vcenter,
                "cpu":                 cpu          or maq_horizon.cpu,
                "ram_gb":              ram_gb        or maq_horizon.ram_gb,
                "disk_provisioned_gb": disk_gb       or maq_horizon.disk_provisioned_gb,
                "disk_used_gb":        disk_used_gb  or getattr(maq_horizon, 'disk_used_gb', None),
                "dns":                 dns           or maq_horizon.dns,
                "so":                  so            or maq_horizon.so,
                "folder":              folder_real or maq_horizon.folder,
                "ruta_computo":        ruta_computo_real or maq_horizon.ruta_computo,
                "resource_pool":       v.get("ResourcePool") or maq_horizon.resource_pool,
                "datastores":          v.get("Datastores") or maq_horizon.datastores,
                "hardware_version":    v.get("HardwareVersion") or maq_horizon.hardware_version,
                "annotation":          annotation_real or maq_horizon.annotation,
                "connection_state":    v.get("ConnectionState") or maq_horizon.connection_state,
                "cpu_usage_mhz":       v.get("CpuUsageMhz") or maq_horizon.cpu_usage_mhz,
                "memory_usage_mb":     v.get("MemoryUsageMB") or maq_horizon.memory_usage_mb,
                "tools_status":        v.get("ToolsStatus") or maq_horizon.tools_status,
                "external_id":         ext_id        or maq_horizon.external_id,
                # Agregados 2026-09-07 -- strings, mismo patrón "or" que el resto de este
                # dict. Los 3 booleanos (hot-add/secure boot) van aparte más abajo: acá
                # "or" trataría un False real como "sin dato nuevo" y nunca lo guardaría.
                "hardware_upgrade_status": v.get("HardwareUpgradeStatus") or maq_horizon.hardware_upgrade_status,
                "cpu_cores_per_socket":    v.get("CpuCoresPerSocket") or maq_horizon.cpu_cores_per_socket,
                "boot_firmware":           v.get("BootFirmware") or maq_horizon.boot_firmware,
            }
            if last_power_on:
                campos_vcenter["fecha_ultimo_ingreso"] = _normalizar_fecha_ingreso(last_power_on)

            # Igual que en _save_or_update_maquina: chequear el umbral de disco ANTES
            # de pisar los valores viejos, y no auditar cpu/ram/disco como "cambio" en
            # cada fluctuación (la mayoría de las VDI pasan por ESTE path, no por
            # _save_or_update_maquina, porque ya matchearon con Horizon).
            _chequear_alerta_disco(maq_horizon.id, snap.id, maq_horizon.disk_used_gb, maq_horizon.disk_provisioned_gb,
                                    campos_vcenter.get("disk_used_gb"), campos_vcenter.get("disk_provisioned_gb"))

            changed = False
            for attr, val_nuevo in campos_vcenter.items():
                val_ant = getattr(maq_horizon, attr, None)
                if val_nuevo and str(val_ant or "") != str(val_nuevo or ""):
                    if attr not in _CAMPOS_SIN_HISTORIAL:
                        hist = MaquinaHistorial(
                            maquina_id=maq_horizon.id,
                            snapshot_id=snap.id,
                            campo_modificado=attr,
                            valor_anterior=str(val_ant or ""),
                            valor_nuevo=str(val_nuevo or ""),
                            detectado_en=datetime.utcnow(),
                        )
                        db.session.add(hist)
                    setattr(maq_horizon, attr, val_nuevo)
                    changed = True

            # Booleanos reales (True y False son ambos datos válidos, no "ausente") --
            # el patrón `val_nuevo or valor_viejo` del loop de arriba trataría un False
            # real como "sin dato nuevo" y nunca lo persistiría. Manejo aparte con
            # "is not None" sin tocar el loop genérico (agregado 2026-09-07).
            for attr, val_nuevo in (
                ("cpu_hot_add_enabled", v.get("CpuHotAddEnabled")),
                ("memory_hot_add_enabled", v.get("MemoryHotAddEnabled")),
                ("secure_boot_enabled", v.get("SecureBootEnabled")),
            ):
                if val_nuevo is None:
                    continue
                val_ant = getattr(maq_horizon, attr, None)
                if val_ant != val_nuevo:
                    if attr not in _CAMPOS_SIN_HISTORIAL:
                        db.session.add(MaquinaHistorial(
                            maquina_id=maq_horizon.id, snapshot_id=snap.id, campo_modificado=attr,
                            valor_anterior=str(val_ant), valor_nuevo=str(val_nuevo), detectado_en=datetime.utcnow(),
                        ))
                    setattr(maq_horizon, attr, val_nuevo)
                    changed = True

            import json
            existing_extra = json.loads(maq_horizon.datos_extra_json) if maq_horizon.datos_extra_json else {}
            existing_extra.update({k: v for k, v in datos_extra_vc.items() if v})
            maq_horizon.datos_extra_json = json.dumps(existing_extra, ensure_ascii=False)

            # Bug real encontrado 2026-08-12: esta rama (VM de vCenter que matcheó con un
            # registro Horizon existente) nunca chequeaba _master_refs_by_origen -- solo
            # la rama "sin match" de abajo lo hacía. Una master real que por nombre
            # coincidiera con algo en Horizon (o que el merge encontrara igual) nunca
            # podía taggearse MASTER acá, quedaba en VDI_POOL/VM_ESTATICA para siempre.
            # Es la causa confirmada de por qué MZ solo mostraba 1 master activa de 5 reales.
            refs_origen_merge = _master_refs_by_origen.get((servidor.origen or "").lower(), set())
            es_master_merge = bool(refs_origen_merge and (ext_id in refs_origen_merge or nombre_vm in refs_origen_merge))
            if es_master_merge:
                maq_horizon.tipo_provisionamiento = "MASTER"
            elif maq_horizon.tipo_provisionamiento != "MASTER":
                maq_horizon.tipo_provisionamiento = clasificar_provisionamiento(maq_horizon.pool)

            if changed:
                maq_horizon.updated_at = datetime.utcnow()

            _guardar_tareas_eventos_vcenter(maq_horizon.id, eventos_reales_vc.get(ext_id, []))
            merged_count += 1
            _vincular_farm_rds_server(servidor.origen, nombre_vm, maq_horizon.id)
            continue

        # ── Antes de asumir "sin match": si esta MISMA VM (mismo external_id, mismo
        # origen) ya tiene una fila VDI_POOL activa bajo OTRO servidor (típicamente el
        # Horizon de este origen), es el mismo objeto real de vCenter que horizon_maquinas
        # no encontró -- no crear/mantener una fila VM_ESTATICA fantasma en paralelo. Bug
        # real encontrado 2026-09-08 (reportado por el usuario: VDIs reales apareciendo
        # etiquetadas como VM): 110 filas así en la DB real, casi todas vdi-* de MZ --
        # residuo de un fallo de matching puntual (coincide con el reordenamiento de pools
        # Horizon a la convención "-MZ" ya documentado más arriba) que ya no ocurre hoy
        # pero cuya fila vieja nunca se limpiaba sola. Si esta MISMA fila (mismo servidor)
        # ya existía como VM_ESTATICA de una corrida vieja, se desactiva acá.
        if ext_id:
            match_real = Maquina.query.filter(
                Maquina._origen_str == servidor.origen,
                Maquina.external_id == ext_id,
                Maquina.servidor_id != servidor.id,
                Maquina.activo == True,
                Maquina.tipo_provisionamiento == "VDI_POOL",
            ).first()
            if match_real:
                fantasma = Maquina.query.filter_by(
                    servidor_id=servidor.id, external_id=ext_id, activo=True
                ).first()
                if fantasma and fantasma.tipo_provisionamiento == "VM_ESTATICA":
                    fantasma.activo = False
                continue

        # ── SIN MATCH: crear/actualizar como VM exclusiva de vCenter ────────
        # Sin correspondencia en ningún pool de Horizon = VM estática (no VDI de pool).
        # Antes se guardaba como "Sin Pool (vCenter)", un pool sintético propio que
        # terminaba listado junto a los pools reales de Horizon en la gestión de pools
        # (sin autorizaciones, porque nunca fue un pool real) -- van directo a
        # "Estática" para no duplicar la categoría (ver _POOLS_SIN_ASIGNAR en kpi_utils.py).
        tipo = _clasificar_tipo(servidor, "")
        if tipo == "VDI":
            vdi_count += 1
        else:
            vm_count += 1

        refs_origen = _master_refs_by_origen.get((servidor.origen or "").lower(), set())
        if refs_origen and (ext_id in refs_origen or nombre_vm in refs_origen):
            datos_extra_vc["es_master"] = True

        maq_created, _ = _save_or_update_maquina(
            servidor_id=servidor.id,
            snapshot_id=snap.id,
            nombre_vm=nombre_vm,
            tipo=tipo,
            origen_str=servidor.origen,
            pool_str="Estática",
            empresa_str="",
            usuario_asignado="",
            estado_horizon="N/A (vCenter)",
            estado_vcenter=power_state,
            manager="",
            agent_version="",
            so=so,
            cpu=cpu,
            ram_gb=ram_gb,
            disk_gb=disk_gb,
            dns=dns,
            ip=ip,
            vcenter_host=vcenter_host,
            correcciones=correcciones,
            fecha_ultimo_ingreso=last_power_on,
            datos_extra=datos_extra_vc,
            disk_used_gb=disk_used_gb,
            indice_nombre_limpio=indice_maquinas_vc,
        )
        if maq_created:
            _guardar_tareas_eventos_vcenter(maq_created.id, eventos_reales_vc.get(ext_id, []))
            _vincular_farm_rds_server(servidor.origen, nombre_vm, maq_created.id)

    log(f"[{servidor.nombre}] 📊 Diagnóstico disco: {_con_disco_real} de {len(vms_raw)} VMs "
        f"trajeron ProvisionedSpaceGB real en esta corrida.")

    # Desactivar VMs NO detectadas en este snapshot Y que no están en Horizon
    for maq_ant in Maquina.query.filter_by(servidor_id=servidor.id, activo=True).all():
        if maq_ant.nombre not in vms_procesadas:
            maq_ant.activo = False

    snap.total_vdi = vdi_count
    snap.total_vm  = vm_count
    db.session.commit()
    log(f"[{servidor.nombre}] vCenter procesado: {vdi_count} VDI + {vm_count} VM propias, "
        f"{merged_count} mergeadas con Horizon (sin duplicar)."
    )


def _extraer_appvolumes_cred(job_id, servidor, user, password, dominio, av_client,
                              base_pct, total, log, progress):
    """
    Extrae aplicaciones/packages/programas instalados/asignaciones/actividad de un
    servidor App Volumes Manager y las persiste en appvolumes_*. No toca la tabla
    `maquinas` -- este es un dominio de datos paralelo (qué software hay paquetizado
    y a quién le corresponde), no inventario de VMs.
    """
    from web.db import (AppVolumesAplicacion, AppVolumesPaquete, AppVolumesPrograma,
                         AppVolumesAsignacion, AppVolumesActividad, AppVolumesWritable)

    def ap(pct, desc):
        progress(base_pct + pct * (0.20 / total), f"[{servidor.nombre}] {desc}")

    datos = av_client.obtener_todo(
        servidor=servidor.host, usuario=user, password=password, dominio=dominio,
        progress_callback=ap,
    )

    # Aplicaciones
    apps_por_avid = {}
    vistas_apps = set()
    for a in datos["aplicaciones"]:
        av_id = a.get("av_id")
        if av_id is None:
            continue
        vistas_apps.add(av_id)
        row = AppVolumesAplicacion.query.filter_by(servidor_id=servidor.id, av_id=av_id).first()
        if not row:
            row = AppVolumesAplicacion(servidor_id=servidor.id, av_id=av_id, nombre=a.get("nombre") or f"App {av_id}")
            db.session.add(row)
        row.guid = a.get("guid")
        row.nombre = a.get("nombre") or row.nombre
        row.descripcion = a.get("descripcion")
        row.assignment_count = a.get("assignment_count") or 0
        row.activo = True
        db.session.flush()
        apps_por_avid[av_id] = row

    for row in AppVolumesAplicacion.query.filter_by(servidor_id=servidor.id, activo=True).all():
        if row.av_id not in vistas_apps:
            row.activo = False

    # Paquetes + programas (software real instalado en cada AppStack)
    vistos_pkgs = set()
    for p in datos["paquetes"]:
        av_id = p.get("av_id")
        if av_id is None:
            continue
        vistos_pkgs.add(av_id)
        row = AppVolumesPaquete.query.filter_by(servidor_id=servidor.id, av_id=av_id).first()
        if not row:
            row = AppVolumesPaquete(servidor_id=servidor.id, av_id=av_id, nombre=p.get("nombre") or f"Package {av_id}")
            db.session.add(row)
        aplicacion_row = apps_por_avid.get(p.get("aplicacion_av_id"))
        if aplicacion_row:
            row.aplicacion_id = aplicacion_row.id
        row.guid = p.get("guid")
        row.nombre = p.get("nombre") or row.nombre
        row.version = p.get("version")
        row.lifecycle_stage = p.get("lifecycle_stage")
        row.delivery = p.get("delivery")
        row.status = p.get("status")
        row.attachment_count = p.get("attachment_count") or 0
        row.size_mb = p.get("size_mb")
        row.datastore_name = p.get("datastore_name")
        row.activo = True
        db.session.flush()

        # La lista de programas de un package se reemplaza entera en cada corrida (delete +
        # insert) en vez de diffear fila a fila -- ya viene completa de la API y no tiene un
        # av_id estable útil para upsert individual.
        AppVolumesPrograma.query.filter_by(paquete_id=row.id).delete()
        for prog in p.get("programas", []):
            db.session.add(AppVolumesPrograma(
                paquete_id=row.id, av_id=prog.get("av_id"), nombre=prog.get("nombre") or "",
                publisher=prog.get("publisher"), install_location=prog.get("install_location"),
                version=prog.get("version"),
            ))

    for row in AppVolumesPaquete.query.filter_by(servidor_id=servidor.id, activo=True).all():
        if row.av_id not in vistos_pkgs:
            row.activo = False

    # Asignaciones (estático: entidad AD <-> aplicación/paquete)
    vistas_asig = set()
    for a in datos["asignaciones"]:
        av_id = a.get("av_id")
        entity_type = a.get("entity_type") or "Desconocido"
        entity_name = a.get("entity_name") or ""
        if av_id is None or not entity_name:
            continue
        key = (av_id, entity_type, entity_name)
        vistas_asig.add(key)
        row = AppVolumesAsignacion.query.filter_by(
            servidor_id=servidor.id, av_id=av_id, entity_type=entity_type, entity_name=entity_name
        ).first()
        if not row:
            row = AppVolumesAsignacion(servidor_id=servidor.id, av_id=av_id,
                                        entity_type=entity_type, entity_name=entity_name)
            db.session.add(row)
        aplicacion_row = apps_por_avid.get(a.get("aplicacion_av_id"))
        row.aplicacion_id = aplicacion_row.id if aplicacion_row else row.aplicacion_id
        row.paquete_id = None  # resuelto abajo si aplica
        paquete_av_id = a.get("paquete_av_id")
        if paquete_av_id:
            pkg_row = AppVolumesPaquete.query.filter_by(servidor_id=servidor.id, av_id=paquete_av_id).first()
            if pkg_row:
                row.paquete_id = pkg_row.id
        row.entity_upn = a.get("entity_upn")
        row.entity_dn = a.get("entity_dn")
        row.filtro_prefijo_computadora = a.get("filtro_prefijo_computadora")
        row.delivery = a.get("delivery")
        row.activo = True
        db.session.flush()

    for row in AppVolumesAsignacion.query.filter_by(servidor_id=servidor.id, activo=True).all():
        if (row.av_id, row.entity_type, row.entity_name) not in vistas_asig:
            row.activo = False

    # Actividad: incremental por (servidor_id, av_id) -- reimportar filas ya vistas es
    # idempotente (UNIQUE), así que no hace falta trackear un cursor de "desde cuándo".
    ids_existentes = {
        row[0] for row in db.session.query(AppVolumesActividad.av_id).filter_by(servidor_id=servidor.id).all()
    }
    nuevos_eventos = 0
    for act in datos["actividad"]:
        av_id = act.get("av_id")
        if av_id is None or av_id in ids_existentes:
            continue
        event_time = None
        raw_time = (act.get("event_time") or "").strip()
        if raw_time:
            for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
                try:
                    event_time = datetime.strptime(raw_time, fmt)
                    break
                except ValueError:
                    continue
        db.session.add(AppVolumesActividad(
            servidor_id=servidor.id, av_id=av_id,
            source_type=act.get("source_type"), source_name=act.get("source_name"),
            target_type=act.get("target_type"), target_name=act.get("target_name"),
            accion=act.get("accion"), resultado=act.get("resultado"),
            event_time=event_time, admin_user_name=act.get("admin_user_name"),
        ))
        nuevos_eventos += 1

    # Writable Volumes (perfil/datos persistentes por usuario) -- mismo patrón upsert por
    # av_id que el resto. Ver core/appvolumes_rest.py para el detalle de por qué esto
    # importa para las alertas de disco (un usuario puede acumular más de un writable).
    vistos_writables = set()
    for w in datos.get("writables", []):
        av_id = w.get("av_id")
        if av_id is None:
            continue
        vistos_writables.add(av_id)
        row = AppVolumesWritable.query.filter_by(servidor_id=servidor.id, av_id=av_id).first()
        if not row:
            row = AppVolumesWritable(servidor_id=servidor.id, av_id=av_id, nombre=w.get("nombre") or f"Writable {av_id}")
            db.session.add(row)
        row.guid = w.get("guid")
        row.nombre = w.get("nombre") or row.nombre
        row.tipo = w.get("tipo")
        row.entity_type = w.get("entity_type")
        row.entity_name = w.get("entity_name")
        row.owner_display_name = w.get("owner_display_name")
        row.estado = w.get("estado")
        row.attached_to = w.get("attached_to")
        row.size_mb = w.get("size_mb")
        row.used_mb = w.get("used_mb")
        row.datastore_name = w.get("datastore_name")
        # Agregados 2026-09-07 -- ver nota de "no confirmado contra payload real" en
        # core/appvolumes_rest.py. provisioned_at_raw puede venir como ISO string o
        # epoch; parseo best-effort, None si no matchea ningún formato conocido.
        row.owner_email = w.get("owner_email") or None
        row.storage_group = w.get("storage_group") or None
        prov_raw = w.get("provisioned_at_raw")
        if prov_raw:
            try:
                if isinstance(prov_raw, (int, float)):
                    row.provisioned_at = datetime.utcfromtimestamp(prov_raw)
                elif isinstance(prov_raw, str):
                    row.provisioned_at = datetime.fromisoformat(prov_raw.replace("Z", "+00:00"))
            except (ValueError, OSError, OverflowError):
                pass
        row.activo = True

    for row in AppVolumesWritable.query.filter_by(servidor_id=servidor.id, activo=True).all():
        if row.av_id not in vistos_writables:
            row.activo = False

    db.session.commit()
    log(f"[{servidor.nombre}] App Volumes procesado: {len(vistas_apps)} aplicaciones, "
        f"{len(vistos_pkgs)} packages, {len(vistas_asig)} asignaciones, {len(vistos_writables)} writable volumes, "
        f"{nuevos_eventos} eventos de actividad nuevos.")


# ── Edición manual ────────────────────────────────────────────────────

@bp_inventario.route("/editar/<int:mid>", methods=["POST"])
def editar_maquina(mid: int):
    maq = Maquina.query.get_or_404(mid)
    try:
        new_pool = request.form.get("pool", "").strip() or "Estática"
        new_empresa = request.form.get("empresa", "").strip()

        emp_rel  = _get_or_create_empresa(new_empresa) if new_empresa else None
        pool_rel = _get_or_create_pool(new_pool) if new_pool else None

        maq.pool_id      = pool_rel.id if pool_rel else None
        maq._pool_str    = new_pool
        maq.empresa_id   = emp_rel.id if emp_rel else None
        maq._empresa_str = new_empresa

        maq.usuario_asignado = request.form.get("usuario_asignado", maq.usuario_asignado)
        maq.estado_horizon   = request.form.get("estado_horizon", maq.estado_horizon)
        maq.manager          = request.form.get("manager", maq.manager)
        maq.agent_version    = request.form.get("agent_version", maq.agent_version)
        maq.so               = request.form.get("so", maq.so)
        maq.tipo             = request.form.get("tipo", maq.tipo)
        if "annotation" in request.form:
            maq.annotation = request.form.get("annotation") or None
        if "estado" in request.form:
            maq.estado = request.form.get("estado") or None
        if "fecha_ultimo_ingreso" in request.form:
            raw_fui = (request.form.get("fecha_ultimo_ingreso") or "").strip()
            import re
            if raw_fui and not re.search(r'^\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4}', raw_fui):
                # Es un texto u observación, no una fecha -> mover a la anotación
                maq.annotation = f"{maq.annotation} | {raw_fui}".strip(" |") if maq.annotation else raw_fui
                maq.fecha_ultimo_ingreso = None
            else:
                maq.fecha_ultimo_ingreso = raw_fui or None

        # Persistir corrección manual
        corr = CorreccionManual.query.filter_by(nombre_vm=maq.nombre).first()
        if not corr:
            corr = CorreccionManual(nombre_vm=maq.nombre)
            db.session.add(corr)
        corr.pool             = maq.pool
        corr.empresa          = maq.empresa
        corr.usuario_asignado = maq.usuario_asignado
        corr.estado_horizon   = maq.estado_horizon
        corr.manager          = maq.manager
        corr.agent_version    = maq.agent_version
        corr.so               = maq.so
        corr.tipo             = maq.tipo
        corr.notas            = maq.annotation

        # Auditoría
        registrar_auditoria(
            accion="editar_vm",
            recurso=maq.nombre,
            detalle=f"empresa={maq.empresa}, usuario={maq.usuario_asignado}, pool={maq.pool}, tipo={maq.tipo}",
            usuario_id=session.get("user_id"),
            username=session.get("username"),
            ip=request.remote_addr,
        )
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Vista de Actividad & Novedades por Servidor ────────────────────────

@bp_inventario.route("/actividad")
def actividad():
    """Vista detallada de Novedades, Eventos y Actividad por Servidor."""
    servidores = Servidor.query.filter_by(activo=True).all()
    srv_stats = []
    for s in servidores:
        maquinas_s = Maquina.query.filter_by(servidor_id=s.id, activo=True).all()
        total = len(maquinas_s)
        nuevas = sum(1 for m in maquinas_s if m.primera_deteccion and (datetime.utcnow() - m.primera_deteccion).total_seconds() < 86400 * 3)
        connected = sum(1 for m in maquinas_s if m.estado_horizon and "CONNECTED" in m.estado_horizon.upper())
        available = sum(1 for m in maquinas_s if m.estado_horizon and "AVAILABLE" in m.estado_horizon.upper())
        srv_stats.append({
            "servidor": s,
            "total": total,
            "nuevas": nuevas,
            "connected": connected,
            "available": available,
        })
    return render_template("actividad.html", servidores=servidores, srv_stats=srv_stats)

