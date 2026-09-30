"""
web/cache.py
Caché de lecturas caras (KPIs, distribución) sobre Redis. Antes cada request recalculaba
todo contra SQLite; con ~1000 filas no se nota, pero al escalar el dataset sí.

Si Redis no responde, se loguea un warning y se calcula directo (degradación de
disponibilidad/performance, no de seguridad — a diferencia de web/db.py con Fernet,
acá SÍ es correcto tener un fallback silencioso).
"""
import os
import json

_redis_client = None
_redis_checked = False


def _get_redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis_client = client
    except Exception as e:
        print(f"[Cache] Redis no disponible ({e}) — KPIs se calculan directo contra SQLite en cada request.", flush=True)
        _redis_client = None
    return _redis_client


def cache_get_or_set(key: str, ttl_seconds: int, compute_fn):
    """Devuelve el valor cacheado en `key` si existe; si no, lo calcula con compute_fn(),
    lo guarda con el TTL dado y lo devuelve. compute_fn debe devolver algo serializable a JSON."""
    r = _get_redis()
    if not r:
        return compute_fn()
    try:
        cached = r.get(key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass
    value = compute_fn()
    try:
        r.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass
    return value


def invalidate(prefix: str):
    """Borra todas las keys que empiecen con `prefix` (ej: invalidate('kpis:') tras una extracción)."""
    r = _get_redis()
    if not r:
        return
    try:
        keys = list(r.scan_iter(f"{prefix}*"))
        if keys:
            r.delete(*keys)
    except Exception:
        pass
