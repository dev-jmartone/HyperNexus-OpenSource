"""
web/jobs.py
Estado de jobs de extracción + progreso SSE, externalizado a Redis para permitir
escalado horizontal (múltiples workers/instancias Waitress compartiendo el mismo estado).

Antes vivía en dicts de módulo en web/routes/inventario.py (_sse_queues, _active_jobs),
lo que ataba el tracking de progreso a la memoria de un único proceso.

Si REDIS_URL no está configurada o Redis no responde, cae de vuelta al comportamiento
anterior (dict + queue.Queue en memoria del proceso) con un warning — sigue funcionando
en una sola instancia, simplemente no escala a varios workers hasta que haya Redis real.
"""
import os
import json
import queue as _queue
import threading
from datetime import datetime, timedelta

_JOB_TTL_SECONDS = 86400

# Techo de "corriendo" antes de considerar el job abandonado (proceso murió/reinició
# a mitad de la extracción sin llegar a marcar done/error). Sin esto, un job Redis
# huérfano bloquea CUALQUIER extracción nueva hasta el TTL de 24hs — bastante peor
# que el problema de saturación que este guard intenta evitar. 45min da margen de
# sobra (una corrida completa de los 6 servidores tarda minutos, no horas).
_STALE_RUNNING_SECONDS = 45 * 60

_redis_client = None
_redis_checked = False


def _get_redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    url = os.environ.get("REDIS_URL")
    if not url:
        print("[Jobs] REDIS_URL no configurada — estado de jobs/SSE en memoria del proceso "
              "(no apto para múltiples workers).", flush=True)
        return None
    try:
        import redis
        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis_client = client
        print("[Jobs] Redis conectado — estado de jobs/SSE externalizado, multi-worker OK.", flush=True)
    except Exception as e:
        print(f"[Jobs] Redis no disponible ({e}) — cayendo a estado en memoria del proceso "
              "(no apto para múltiples workers).", flush=True)
        _redis_client = None
    return _redis_client


# Fallback en memoria (comportamiento previo, válido para una sola instancia)
_mem_jobs: dict[str, dict] = {}
_mem_queues: dict[str, "_queue.Queue"] = {}
_mem_lock = threading.Lock()


def create_job(job_id: str, meta: dict):
    """Crea el registro de un job nuevo con estado inicial."""
    meta = dict(meta)
    meta["job_id"] = job_id
    r = _get_redis()
    if r:
        r.hset(f"job:{job_id}", mapping={k: json.dumps(v) for k, v in meta.items()})
        r.expire(f"job:{job_id}", _JOB_TTL_SECONDS)
    else:
        with _mem_lock:
            _mem_jobs[job_id] = meta
            _mem_queues[job_id] = _queue.Queue()


def try_start_job(job_id: str, meta: dict) -> bool:
    """Check-and-create atómico: devuelve False si ya hay un job corriendo (sin
    crear el nuevo). get_active_job()+create_job() por separado tiene ventana de
    carrera -- dos requests casi simultáneos (doble click sin debounce, dos pestañas)
    pueden pasar ambos el chequeo antes de que cualquiera cree su job, y terminan
    corriendo dos extracciones completas en paralelo escribiendo lo mismo dos veces."""
    r = _get_redis()
    if r:
        # Prefijo DISTINTO de "job:" a proposito -- get_active_job() hace scan_iter("job:*")
        # asumiendo que todo lo que matchea es un HASH de job real (r.hgetall). Este lock es
        # un STRING (r.set); con el prefijo "job:" el scan lo encontraba y explotaba con
        # "WRONGTYPE Operation against a key holding the wrong kind of value" en CADA intento
        # de iniciar una extraccion (bug real encontrado 2026-09-02, rompia el escaneo).
        lock_key = "joblock:start"
        if not r.set(lock_key, "1", nx=True, ex=10):
            return False
        try:
            if get_active_job():
                return False
            create_job(job_id, meta)
            return True
        finally:
            r.delete(lock_key)
    with _mem_lock:
        for info in _mem_jobs.values():
            if info.get("status") == "running" and not _esta_stale(info):
                return False
        meta = dict(meta)
        meta["job_id"] = job_id
        _mem_jobs[job_id] = meta
        _mem_queues[job_id] = _queue.Queue()
        return True


def get_job(job_id: str) -> dict | None:
    r = _get_redis()
    if r:
        raw = r.hgetall(f"job:{job_id}")
        if not raw:
            return None
        return {k: json.loads(v) for k, v in raw.items()}
    with _mem_lock:
        return _mem_jobs.get(job_id)


def _esta_stale(info: dict) -> bool:
    creado = info.get("created_at")
    if not creado:
        return False
    try:
        edad = datetime.utcnow() - datetime.fromisoformat(creado)
    except (TypeError, ValueError):
        return False
    return edad > timedelta(seconds=_STALE_RUNNING_SECONDS)


def get_active_job() -> dict | None:
    """Primer job con status=running y no abandonado (para el guard anti-solapamiento
    y para mostrar "hay una extracción en curso" en la UI). Un job "running" viejo
    (>45min) se ignora — probablemente el proceso que lo corría murió sin marcarlo
    done/error, y bloquearía toda extracción futura si se lo tomara en cuenta."""
    r = _get_redis()
    if r:
        for key in r.scan_iter("job:*"):
            raw = r.hgetall(key)
            status = raw.get("status")
            if status and json.loads(status) == "running":
                info = {k: json.loads(v) for k, v in raw.items()}
                if not _esta_stale(info):
                    return info
        return None
    with _mem_lock:
        for info in _mem_jobs.values():
            if info.get("status") == "running" and not _esta_stale(info):
                return info
        return None


def push_event(job_id: str, tipo: str, msg: str):
    """Publica un evento de progreso (log/pct/progress/done/error) y actualiza el estado del job.

    Usa una lista Redis (RPUSH) en vez de pub/sub: pub/sub descarta el mensaje si todavía no
    hay nadie suscripto (típico acá — el hilo de extracción arranca y putea el primer log
    antes de que el navegador termine de abrir el EventSource), lo que dejaba el streaming
    "colgado" mostrando el job corriendo pero sin traer nada. Una lista + BLPOP no pierde
    eventos sin importar cuándo se conecte el consumidor, igual que la Queue en memoria de antes.
    """
    r = _get_redis()
    if r:
        r.rpush(f"job_queue:{job_id}", json.dumps({"tipo": tipo, "msg": msg}))
        r.expire(f"job_queue:{job_id}", _JOB_TTL_SECONDS)
        updates = {}
        if tipo == "pct":
            try:
                updates["pct"] = json.dumps(int(msg))
            except ValueError:
                pass
        elif tipo == "progress":
            updates["msg"] = json.dumps(msg)
        elif tipo in ("done", "error", "cancelled"):
            updates["status"] = json.dumps(tipo)
        if updates and r.exists(f"job:{job_id}"):
            r.hset(f"job:{job_id}", mapping=updates)
            r.expire(f"job:{job_id}", _JOB_TTL_SECONDS)
    else:
        with _mem_lock:
            q = _mem_queues.get(job_id)
            if q:
                q.put({"tipo": tipo, "msg": msg})
            job = _mem_jobs.get(job_id)
            if job:
                if tipo == "pct":
                    try:
                        job["pct"] = int(msg)
                    except ValueError:
                        pass
                elif tipo == "progress":
                    job["msg"] = msg
                elif tipo in ("done", "error", "cancelled"):
                    job["status"] = tipo


def stream_events(job_id: str):
    """Generador de eventos para el endpoint SSE (lista Redis con BLPOP si está disponible, si no la Queue local).

    Si el hilo que corre la extracción muere sin publicar done/error/cancelled (proceso
    matado, excepción no capturada antes de llegar a _push_sse), este generador quedaba
    en el `while True` para siempre mandando pings cada 60s -- la conexión SSE nunca se
    cerraba sola. Cada ping ahora también chequea si el job entró en estado "stale" (>45min
    corriendo, ver _esta_stale) y si es así corta el stream con un error, en vez de sostener
    la conexión indefinidamente."""
    r = _get_redis()
    if r:
        if not r.exists(f"job:{job_id}"):
            yield {"tipo": "error", "msg": "Job no encontrado"}
            return
        import redis as _redis_mod
        queue_key = f"job_queue:{job_id}"
        while True:
            try:
                popped = r.blpop([queue_key], timeout=60)
            except (_redis_mod.exceptions.TimeoutError, _redis_mod.exceptions.ConnectionError):
                # Socket idle-timeout a nivel de red/SO (firewall/NAT cortando la conexión
                # inactiva) antes de que Redis devuelva nil — no significa que Redis caiga.
                # Tratarlo igual que un BLPOP sin resultado, no matar el generador SSE.
                popped = None
            if popped is None:
                info = get_job(job_id)
                if info and _esta_stale(info):
                    yield {"tipo": "error", "msg": "El job quedó sin actividad demasiado tiempo (proceso caído) -- stream cerrado."}
                    r.delete(queue_key)
                    break
                yield {"tipo": "ping"}
                continue
            _, raw = popped
            event = json.loads(raw)
            yield event
            if event.get("tipo") in ("done", "error", "cancelled"):
                r.delete(queue_key)
                break
    else:
        q = _mem_queues.get(job_id)
        if not q:
            yield {"tipo": "error", "msg": "Job no encontrado"}
            return
        while True:
            try:
                event = q.get(timeout=60)
                yield event
                if event.get("tipo") in ("done", "error", "cancelled"):
                    _mem_queues.pop(job_id, None)
                    break
            except _queue.Empty:
                info = _mem_jobs.get(job_id)
                if info and _esta_stale(info):
                    yield {"tipo": "error", "msg": "El job quedó sin actividad demasiado tiempo (proceso caído) -- stream cerrado."}
                    _mem_queues.pop(job_id, None)
                    break
                yield {"tipo": "ping"}


def request_cancel(job_id: str):
    """Marca un job para cancelación cooperativa. La extracción (_ejecutar_extraccion)
    chequea esta bandera entre fases y corta ahí — no hay forma de abortar una llamada
    HTTP en vuelo a mitad de un request, así que el corte es entre fases, no instantáneo."""
    r = _get_redis()
    if r:
        if r.exists(f"job:{job_id}"):
            r.hset(f"job:{job_id}", mapping={"cancel_requested": json.dumps(True)})
            r.expire(f"job:{job_id}", _JOB_TTL_SECONDS)
    else:
        with _mem_lock:
            job = _mem_jobs.get(job_id)
            if job:
                job["cancel_requested"] = True


def is_cancel_requested(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job.get("cancel_requested"))
