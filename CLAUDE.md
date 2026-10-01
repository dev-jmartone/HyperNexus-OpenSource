# HyperNexus (Open Source Edition)

Enterprise Multi-Hypervisor & Virtual Desktop Infrastructure (VDI) management, inventory, and analytics platform. Unifies 4x VMware vCenter servers, 4x VMware Horizon Connection Servers, VMware App Volumes, and Active Directory into a single pane of glass with real-time health telemetry, cross-cluster search, capacity tracking, orphaned VM detection, and automated directory reconciliation.

---

## 🏛️ Architecture Overview

The system is organized into modular layers:

- **Web Application Backend (`web/`)**:
  - Flask application with Blueprint routing (`web/routes/`).
  - SQLAlchemy 2.0 ORM with SQLite (default) and PostgreSQL/MySQL support (`web/db.py`).
  - ThreadPool-driven multi-hypervisor extractor (`web/routes/inventario.py`).
  - Real-time Server-Sent Events (SSE) stream (`web/jobs.py`) with optional Redis state backend.
  - Background scheduler (`web/scheduler.py`) for automated extractions and data retention policies.
- **Frontend SPA (`web/frontend/`)**:
  - React 18 single-page application built with Vite, Tailwind CSS, and Lucide React.
  - High-performance virtualized tables, dynamic interactive filters, and rich drawer inspections.
  - Production distribution is pre-compiled into `web/frontend/dist/` and served directly by Flask.
- **Integration Engine (`core/`)**:
  - `core/horizon_rest.py`: VMware Horizon REST API client (Connection Servers, Desktop Pools, Sessions).
  - `core/vcenter_rest.py`: VMware vSphere vCenter REST API client (VMs, datastores, hardware metrics).
  - `core/vcenter_soap.py`: PyVmomi / vSphere SOAP client for deep annotations, folder hierarchy, and events.
  - `core/appvolumes_rest.py`: VMware App Volumes Manager REST client (Applications, Packages, Writables).
  - `core/ad_client.py`: Active Directory LDAP client (LDAP query, account status, UPN resolution).
  - `core/outlook_client.py`: Global Address List (GAL) directory scraper and email enrichment.

---

## 🚀 Entrypoints & Launchers

- `server.py` — Flask development server (Port `5000`, debug/threaded mode).
- `server_prod.py` — Waitress production WSGI server (Port `5000`, 16 worker threads).
- `iniciar_prod.bat` — One-click launcher for Windows production service.
- `iniciar_dev.bat` — One-click launcher for local development environment.
- `docker-compose.yml` — Containerized deployment with optional Redis cache.

---

## 🧪 Testing & Quality Assurance

### Python Backend Tests
Run the comprehensive test suite using `pytest`:
```bash
pytest tests/ -v
```

Tests cover:
- Health status classification & KPI calculations (`tests/test_kpi_utils.py`).
- Active Directory candidate deduplication & canonical resolution (`tests/test_directorio_dedup.py`).
- Security boundaries & path traversal protections (`tests/test_security_findings.py`).
- Horizon REST farm/pool parsing (`tests/test_horizon_rest_granja.py`).
- Batch extraction processing (`tests/test_extraccion_batch.py`).

### Frontend Tests
Run Vitest unit tests:
```bash
cd web/frontend
npm test
```

### Frontend Build
Compile React SPA assets for Flask static serving:
```bash
cd web/frontend
npm run build
```

---

## ⚙️ Key Environment Variables

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Flask session cryptographic key | Random string required |
| `FERNET_KEY` | Fernet 32-byte key for credentials encryption | Base64-encoded key required |
| `DEMO_MODE` | When `1`, operates entirely on simulated offline mock data | `0` |
| `AD_DOMAIN` | Target Active Directory domain | `corp.local` |
| `HORIZON_DEFAULT_DOMAIN` | Default domain for Horizon authentication | `CORP` |
| `REDIS_URL` | Optional Redis URI for multi-worker SSE & cache | None (in-memory fallback) |
| `INVENTARIO_DB_PATH` | Absolute path to SQLite database | `data/inventario.db` |

---

## 🔒 Security Best Practices

1. **Credentials Encryption**: Server passwords stored in the database are encrypted at rest using Fernet symmetric encryption (`Servidor.password`).
2. **Session Security**: Cookies are configured with `HttpOnly`, `SameSite=Lax`, and configurable `Secure` flags.
3. **No Hardcoded Secrets**: All infrastructure credentials, domain names, and external APIs are loaded via environment variables or runtime database configurations.
