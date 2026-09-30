"""
web/scheduler.py
Planificador de Extracción Automática en Tiempo Real en Segundo Plano (Background Thread).
Ejecuta la extracción periódica automática (por defecto cada 5-10 minutos) utilizando
los clientes PURE REST API para mantener el inventario y las sesiones 100% actualizados en vivo.
"""
import time
import threading
from datetime import datetime

_scheduler_thread = None
_scheduler_running = False
_current_interval_seconds = 300

INTERVAL_OPTIONS = {
    "off": 0,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}

_CONFIG_KEY = "scheduler_interval"


def set_scheduler_interval(key: str) -> dict:
    """Actualiza el intervalo de vigilancia en tiempo real Y lo persiste en
    Configuracion — antes solo vivía en una variable de módulo, así que un
    reinicio del server (bat, redeploy) lo resetía a 5m aunque un admin lo
    hubiera puesto en "off" a propósito. Requiere contexto de app Flask activo."""
    global _current_interval_seconds
    key_clean = key.lower().strip()
    if key_clean in INTERVAL_OPTIONS:
        _current_interval_seconds = INTERVAL_OPTIONS[key_clean]
        try:
            from web.db import db, Configuracion
            cfg = Configuracion.query.filter_by(clave=_CONFIG_KEY).first()
            if cfg:
                cfg.valor = key_clean
            else:
                cfg = Configuracion(clave=_CONFIG_KEY, valor=key_clean,
                                     descripcion="Intervalo del AutoScheduler de extracción (off/1m/5m/15m/30m/1h)")
                db.session.add(cfg)
            db.session.commit()
        except Exception as e:
            print(f"[AutoScheduler] No se pudo persistir el intervalo en Configuracion: {e}", flush=True)
    return get_scheduler_interval()

def get_scheduler_interval() -> dict:
    """Retorna la configuración actual del intervalo."""
    inv_map = {v: k for k, v in INTERVAL_OPTIONS.items()}
    current_key = inv_map.get(_current_interval_seconds, "5m")
    return {
        "key": current_key,
        "seconds": _current_interval_seconds,
        "enabled": _current_interval_seconds > 0,
        "options": ["off", "1m", "5m", "15m", "30m", "1h"]
    }

def start_auto_scheduler(app, default_key: str = "5m"):
    """Inicializa el hilo de fondo para extracciones automáticas periódicas."""
    global _scheduler_thread, _scheduler_running, _current_interval_seconds
    if _scheduler_running:
        return

    _current_interval_seconds = INTERVAL_OPTIONS.get(default_key, 300)
    try:
        with app.app_context():
            from web.db import Configuracion
            cfg = Configuracion.query.filter_by(clave=_CONFIG_KEY).first()
            if cfg and cfg.valor in INTERVAL_OPTIONS:
                _current_interval_seconds = INTERVAL_OPTIONS[cfg.valor]
                print(f"[AutoScheduler] Intervalo restaurado desde Configuracion: {cfg.valor}", flush=True)
    except Exception as e:
        print(f"[AutoScheduler] No se pudo leer el intervalo persistido, uso default {default_key}: {e}", flush=True)

    _scheduler_running = True

    def _loop():
        time.sleep(5)  # Espera inicial de 5 segundos al arrancar la app
        while _scheduler_running:
            if _current_interval_seconds <= 0:
                # "off": el hilo se queda vivo pero no toca servidores/credenciales —
                # solo espera liviano a que se elija un intervalo real de nuevo.
                time.sleep(5)
                continue
            try:
                with app.app_context():
                    from web.db import Servidor, SesionCredencialTemp, obtener_credencial_desencriptada
                    from web.routes.inventario import _ejecutar_extraccion
                    from web import jobs as _jobs

                    # Si ya hay una extracción corriendo (manual o de un tick anterior que se
                    # alargó más que el intervalo), saltear este tick — arrancar otra en paralelo
                    # duplica la carga de guest-ops contra vCenter/Horizon (mismo origen del 503).
                    if _jobs.get_active_job():
                        print("[AutoScheduler] Ya hay una extracción en curso — se saltea este tick.", flush=True)
                    else:
                        # Buscar servidores activos
                        servidores = Servidor.query.filter_by(activo=True).all()
                        if servidores:
                            srv_ids = [str(s.id) for s in servidores]

                            # Buscar credencial activa de cualquier usuario reciente
                            cred_row = SesionCredencialTemp.query.filter(
                                SesionCredencialTemp.expira_en > datetime.utcnow()
                            ).first()

                            if cred_row:
                                pwd = obtener_credencial_desencriptada(cred_row.usuario_id)
                                if pwd:
                                    job_id = "auto_" + datetime.utcnow().strftime("%Y%m%d%H%M%S")
                                    # Registrar el job ANTES de correrlo: así una extracción manual
                                    # disparada mientras esta corre también la ve como "activa" y
                                    # se abstiene de arrancar otra en paralelo.
                                    _jobs.create_job(job_id, {
                                        "status": "running",
                                        "pct": 0,
                                        "msg": "Iniciando extracción automática...",
                                        "created_at": datetime.utcnow().isoformat(),
                                        "servidores_count": len(srv_ids),
                                    })
                                    print(f"[AutoScheduler] Ejecutando extraccion automatica en segundo plano (Intervalo: {_current_interval_seconds}s | Job #{job_id})...", flush=True)
                                    _ejecutar_extraccion(
                                        job_id=job_id,
                                        servidor_ids=srv_ids,
                                        mantener_correcciones=True,
                                        session_user="Sistema (AutoScheduler)",
                                        session_pwd=pwd,
                                        es_automatico=True
                                    )
            except Exception as e:
                print(f"[AutoScheduler Error] {e}", flush=True)

            # Espera dinámica según la frecuencia seleccionada
            time.sleep(_current_interval_seconds)

    _scheduler_thread = threading.Thread(target=_loop, daemon=True, name="AutoSchedulerThread")
    _scheduler_thread.start()
    print(f"[AutoScheduler] Planificador automatico iniciado. Vigilancia activa en vivo.", flush=True)


_retention_thread = None
_retention_running = False


def _purgar_historial_viejo(app):
    """Borra InventarioSnapshot/MaquinaHistorial más viejos que Configuracion.retencion_snapshots_dias,
    y VMTareaEvento "huérfano" (VM inactiva hace más de esos mismos días — mismo criterio que usa
    el Motor de Reconciliación para marcarlos huérfanos, ver _validar_y_reconciliar_payload).
    Conserva siempre el snapshot más reciente de cada servidor (no borra el único registro de "última corrida")."""
    from datetime import timedelta
    from web.db import db, Configuracion, InventarioSnapshot, MaquinaHistorial, Servidor, Maquina, VMTareaEvento

    with app.app_context():
        cfg = Configuracion.query.filter_by(clave="retencion_snapshots_dias").first()
        try:
            dias = int(cfg.valor) if cfg and cfg.valor else 90
        except (TypeError, ValueError):
            dias = 90
        limite = datetime.utcnow() - timedelta(days=dias)

        total_snapshots = 0
        for s in Servidor.query.all():
            ultimo_id = (
                db.session.query(InventarioSnapshot.id)
                .filter_by(servidor_id=s.id)
                .order_by(InventarioSnapshot.timestamp.desc())
                .limit(1)
                .scalar()
            )
            q = InventarioSnapshot.query.filter(
                InventarioSnapshot.servidor_id == s.id,
                InventarioSnapshot.timestamp < limite,
            )
            if ultimo_id is not None:
                q = q.filter(InventarioSnapshot.id != ultimo_id)
            total_snapshots += q.delete(synchronize_session=False)

        total_historial = MaquinaHistorial.query.filter(
            MaquinaHistorial.detectado_en < limite
        ).delete(synchronize_session=False)

        maquinas_inactivas_viejas = db.session.query(Maquina.id).filter(
            Maquina.activo == False,
            Maquina.updated_at < limite,
        )
        total_eventos = VMTareaEvento.query.filter(
            VMTareaEvento.maquina_id.in_(maquinas_inactivas_viejas)
        ).delete(synchronize_session=False)

        db.session.commit()
        if total_snapshots or total_historial or total_eventos:
            print(f"[RetentionPurger] Retención={dias}d — borrados {total_snapshots} snapshots viejos, "
                  f"{total_historial} filas de historial, {total_eventos} eventos huérfanos.", flush=True)


def start_retention_purger(app, interval_seconds: int = 86400):
    """Hilo daemon que corre la purga de retención una vez por día (mismo patrón que el AutoScheduler)."""
    global _retention_thread, _retention_running
    if _retention_running:
        return
    _retention_running = True

    def _loop():
        time.sleep(30)  # esperar a que la app termine de arrancar
        while _retention_running:
            try:
                _purgar_historial_viejo(app)
            except Exception as e:
                print(f"[RetentionPurger Error] {e}", flush=True)
            time.sleep(interval_seconds)

    _retention_thread = threading.Thread(target=_loop, daemon=True, name="RetentionPurgerThread")
    _retention_thread.start()
    print("[RetentionPurger] Purga de retención iniciada (corre una vez por día).", flush=True)
