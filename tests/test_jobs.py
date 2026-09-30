"""Tests de web/jobs.py en modo memoria (sin Redis — conftest.py hace pop de REDIS_URL).
Cubre: create/get, push_event, stream_events (done/error/cancelled), cancel cooperativo,
detección de job 'running' abandonado (stale)."""
import time
from datetime import datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def _reset_jobs_module():
    """web/jobs.py guarda estado en dicts de módulo — limpiarlos entre tests."""
    import web.jobs as jobs
    jobs._mem_jobs.clear()
    jobs._mem_queues.clear()
    yield
    jobs._mem_jobs.clear()
    jobs._mem_queues.clear()


def test_create_and_get_job():
    import web.jobs as jobs
    jobs.create_job("job1", {"status": "running", "pct": 0, "created_at": datetime.utcnow().isoformat()})
    info = jobs.get_job("job1")
    assert info["status"] == "running"
    assert info["job_id"] == "job1"


def test_get_active_job_finds_running():
    import web.jobs as jobs
    jobs.create_job("job1", {"status": "running", "created_at": datetime.utcnow().isoformat()})
    activo = jobs.get_active_job()
    assert activo is not None
    assert activo["job_id"] == "job1"


def test_get_active_job_none_if_all_done():
    import web.jobs as jobs
    jobs.create_job("job1", {"status": "running", "created_at": datetime.utcnow().isoformat()})
    jobs.push_event("job1", "done", "/inventario")
    assert jobs.get_active_job() is None


def test_stale_running_job_ignored_by_active_job():
    """Job 'running' hace >45min sin cerrar (proceso muerto) no debe bloquear futuras
    extracciones — ver _esta_stale en web/jobs.py."""
    import web.jobs as jobs
    vieja = (datetime.utcnow() - timedelta(minutes=60)).isoformat()
    jobs.create_job("job_viejo", {"status": "running", "created_at": vieja})
    assert jobs.get_active_job() is None


def test_stream_events_yields_log_then_done():
    import web.jobs as jobs
    jobs.create_job("job1", {"status": "running", "created_at": datetime.utcnow().isoformat()})
    jobs.push_event("job1", "log", "hola")
    jobs.push_event("job1", "done", "/inventario")

    eventos = []
    for ev in jobs.stream_events("job1"):
        eventos.append(ev)
        if ev.get("tipo") == "done":
            break

    tipos = [e["tipo"] for e in eventos]
    assert "log" in tipos
    assert tipos[-1] == "done"


def test_stream_events_job_inexistente():
    import web.jobs as jobs
    eventos = list(jobs.stream_events("no-existe"))
    assert eventos[0]["tipo"] == "error"


def test_cancel_flag_set_and_read():
    import web.jobs as jobs
    jobs.create_job("job1", {"status": "running", "created_at": datetime.utcnow().isoformat()})
    assert jobs.is_cancel_requested("job1") is False
    jobs.request_cancel("job1")
    assert jobs.is_cancel_requested("job1") is True


def test_push_event_cancelled_sets_status_and_stops_stream():
    import web.jobs as jobs
    jobs.create_job("job1", {"status": "running", "created_at": datetime.utcnow().isoformat()})
    jobs.push_event("job1", "cancelled", "Extracción cancelada por el usuario.")

    info = jobs.get_job("job1")
    assert info["status"] == "cancelled"
    assert jobs.get_active_job() is None  # ya no cuenta como "en curso"
