"""Test unitario del parseo de Farms/Application Pools/Entitlements/RDS Servers en
HorizonRestClient.obtener_todo -- sin servidor real, mockea urllib.request.urlopen."""
import json


class _FakeResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen_factory(routes: dict):
    """routes: dict de 'fragmento de URL' -> payload JSON a devolver. Matchea por el
    fragmento MAS LARGO (no el primero insertado) -- varias URLs reales son substring
    unas de otras (ej. '/application-pools' vs '/application-pools/app-1/entitlements')."""
    ordenadas = sorted(routes.items(), key=lambda kv: len(kv[0]), reverse=True)

    def _fake_urlopen(req, context=None, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for frag, payload in ordenadas:
            if frag in url:
                return _FakeResponse(payload)
        return _FakeResponse([])
    return _fake_urlopen


def test_obtener_todo_incluye_farms_apps_entitlements_rds_servers(monkeypatch):
    from core.horizon_rest import HorizonRestClient

    routes = {
        "/rest/login": {"access_token": "tok-123"},
        "/rest/inventory/v2/desktop-pools": [
            {"id": "pool-1", "name": "Pool-Ventas-MZ", "enabled": True},
        ],
        "/rest/inventory/v1/sessions": [],
        "/rest/inventory/v1/machines": [],
        "/rest/external/v1/audit-events": [],
        "/rest/inventory/v1/farms": [
            {"id": "farm-1", "name": "Farm-DT-01", "display_name": "Farm DT 01",
             "type": "AUTOMATED", "enabled": True, "rds_server_max_sessions": 250},
        ],
        "/rest/inventory/v1/application-pools": [
            {"id": "app-1", "name": "Excel", "display_name": "Microsoft Excel",
             "farm_id": "farm-1", "executable_path": "C:\\Excel.exe", "enabled": True},
        ],
        # Entitlements viven en el namespace "/rest/entitlements/v1/*", bulk (no
        # por-pool-id) -- confirmado en vivo 2026-09-07 contra un Connection Server
        # real, ver comentario en core/horizon_rest.py. El shape real es
        # {"id": <pool_id>, "ad_user_or_group_ids": [sid, ...]}, los SIDs se
        # resuelven aparte vía /rest/external/v1/ad-users-or-groups/{sid}.
        "/rest/entitlements/v1/application-pools": [
            {"id": "app-1", "ad_user_or_group_ids": ["S-1-5-21-1001"]},
        ],
        "/rest/entitlements/v1/desktop-pools": [
            {"id": "pool-1", "ad_user_or_group_ids": ["S-1-5-21-1002"]},
        ],
        "/rest/external/v1/ad-users-or-groups/S-1-5-21-1001": {"login_name": "jperez"},
        "/rest/external/v1/ad-users-or-groups/S-1-5-21-1002": {"login_name": "mgomez"},
        # Recurso plano top-level, NO nested bajo farms/{id}/ -- eso da 404 real en
        # producción, ver comentario en core/horizon_rest.py. farm_id viene en cada item.
        "/rest/inventory/v1/rds-servers": [
            {"farm_id": "farm-1", "name": "RDSHOST01", "state": "OK", "session_count": 3, "enabled": True},
        ],
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen_factory(routes))

    client = HorizonRestClient(log_callback=lambda msg: None)
    datos = client.obtener_todo(servidor="fake-horizon.local", usuario="admin", password="x", dominio="CORP")

    assert len(datos["farms"]) == 1
    assert datos["farms"][0]["Name"] == "Farm-DT-01"
    assert datos["farms"][0]["RdsServerMaxSessions"] == 250

    assert len(datos["application_pools"]) == 1
    assert datos["application_pools"][0]["Name"] == "Excel"
    assert datos["application_pools"][0]["FarmName"] == "Farm-DT-01"

    assert len(datos["app_entitlements_locales"]) == 1
    assert datos["app_entitlements_locales"][0]["UserOrGroup"] == "jperez"
    assert datos["app_entitlements_locales"][0]["AplicacionNombre"] == "Excel"

    assert len(datos["entitlements_locales"]) == 1
    assert datos["entitlements_locales"][0]["UserOrGroup"] == "mgomez"
    assert datos["entitlements_locales"][0]["PoolName"] == "Pool-Ventas-MZ"

    assert len(datos["rds_servers"]) == 1
    assert datos["rds_servers"][0]["Name"] == "RDSHOST01"
    assert datos["rds_servers"][0]["FarmName"] == "Farm-DT-01"
    assert datos["rds_servers"][0]["SesionesActivas"] == 3
