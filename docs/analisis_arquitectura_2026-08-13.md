# Inventario VDI — Análisis completo de arquitectura y estado (2026-08-13)

Generado con el skill `vdi-audit` + exploración directa de código (codebase-memory-mcp reindexado: 1422 nodos, 4432 edges) + verificación en vivo contra vCenter/Horizon/App Volumes reales durante esta sesión. Reemplaza/actualiza la sección de deuda técnica de `CLAUDE.md`.

---

## PARTE 1 — Cómo funciona todo

### 1.1 Qué es esto

Sistema de inventario para una plataforma VDI (VMware Horizon + vCenter + App Volumes + Active Directory + Outlook/GAL) multi-sitio (4 sitios: DT, MZ, SU, Core). Dos productos en el mismo repo:

- **Web app (activa)**: Flask + React/Vite. Es donde está todo el desarrollo.
- **App de escritorio (congelada)**: CustomTkinter, vive en `Archive/legacy_desktop/`, empaquetada a `.exe` vía PyInstaller. No se toca salvo pedido explícito.

### 1.2 Entrypoints

| Archivo | Uso | Servidor | Puerto |
|---|---|---|---|
| `server.py` | Dev | Flask dev server (threaded) | 5000 |
| `server_prod.py` | Producción | Waitress WSGI, `threads=16` | 5000 (`HOST`/`PORT`/`THREADS` por env) |
| `server_legacy.py` | Fuerza `LEGACY_UI=1`, sirve Jinja viejo | Flask dev | 3001 |

Los 3 son wrappers de `web.app.create_app()`. `web/routes/dashboard.py` decide en runtime SPA React vs Jinja legacy según `LEGACY_UI`. `create_app()` arranca además, como hilos daemon en background: `AutoScheduler` (extracción periódica) y `RetentionPurger` (purga diaria) — ver 1.6.

### 1.3 Cómo se extrae la información — fuente por fuente

Todo el fetch es **REST puro por HTTPS** (`urllib.request` estándar de Python, sin librerías cliente oficiales de VMware/Omnissa). Nada de PowerCLI/SDKs en el pipeline activo — eso solo existe en la app legacy congelada.

#### Horizon (`core/horizon_rest.py`)
- Auth: `POST /rest/login` (Bearer token), reintentado con distintos formatos de usuario.
- Endpoints: `/rest/inventory/v2/desktop-pools` (pools + `provisioning_settings.parent_vm_id` = MoRef real del master), `/rest/inventory/v1/sessions`, `/rest/inventory/v1/machines` (o v3 según versión), `/rest/external/v1/audit-events` (auditoría — publish/unpublish de imagen, logins).
- Concurrencia: 2 servidores Horizon (DT, MZ) en paralelo vía `ThreadPoolExecutor(max_workers=4)`.
- Da: máquinas VDI, pools, entitlements (locales/globales), eventos de auditoría, y desde hoy `ParentVmId` por pool (ver 2.2).

#### vCenter (`core/vcenter_rest.py`)
- Auth: `POST /api/session` (vSphere 7.0+) o `/rest/com/vmware/cis/session` (6.x), sesión por cookie/token.
- Endpoints: `/api/vcenter/vm` (lista), `/api/vcenter/vm/{id}` (detalle: CPU/RAM/disco/HW version/SO), `/api/vcenter/vm/{id}/tools`, `/api/vcenter/vm/{id}/guest/local-filesystem` (disco usado real), `/api/vcenter/vm/{id}/guest/identity`, `/api/vcenter/vm/{id}/guest/networking/interfaces`, `/api/vcenter/host`, `/api/vcenter/datastore`, `/api/vcenter/vm-template/library-items`.
- Concurrencia: `ThreadPoolExecutor(max_workers=16)` para VMs en paralelo, con un **semáforo aparte de 4** (`_guest_sem`, bajado de 8 hoy) que limita específicamente cuántas llamadas guest-ops (tools/disco/identity/interfaces/detalle) están en vuelo a la vez — es lo que satura vpxd→hostd y dispara HTTP 503 si se sube.
- Reintentos: backoff exponencial (0.5/1.5/3.0s) solo ante 503, más un "pase 2" secuencial de 1 intento para lo que siguió fallando.
- 4 servidores vCenter (DT, MZ, SU, Core) en paralelo.

#### App Volumes (`core/appvolumes_rest.py`)
- Auth: `POST /app_volumes/sessions` con cookie de sesión (no bearer), prueba varios formatos de usuario (username pelado primero, confirmado en vivo que es el que funciona).
- Endpoints: `/app_volumes/app_products` (apps + packages anidados), `/app_volumes/app_packages/{id}/programs` (software instalado real), `/app_volumes/app_products/{id}/assignments` (con query params específicos, no documentados de forma obvia — se corrigieron en vivo contra un HAR real), `/app_volumes/activity_logs`, y desde hoy `/app_volumes/writables` (sin validar aún contra servidor real, ver 2.6).
- 2 servidores (DT, MZ) en paralelo.

#### Active Directory (`core/ad_client.py`)
- **No es LDAP directo** — es `Get-ADUser` de PowerShell ejecutado como subproceso, en lotes de 100 usuarios, con los usernames pasados por archivo JSON (nunca interpolados en el texto del script — arreglo de un RCE real que existía antes). Implica que el proceso necesita correr en una máquina con el módulo AD de PowerShell (RSAT) y alcance al DC.

#### Outlook/GAL (`core/outlook_client.py`)
- **COM automation** vía `win32com.client` contra un Outlook instalado localmente — no es Graph API ni EWS. Solo funciona si el proceso corre en una máquina Windows con Outlook configurado con el perfil correcto. Cachea en `data/gal_cache.json`.

### 1.4 Cómo se guarda — pipeline de extracción

`web/routes/inventario.py::_ejecutar_extraccion()` orquesta todo, en 3 fases secuenciales (cada fase espera a que la anterior termine del todo antes de arrancar, vía bloques `with ThreadPoolExecutor(...)` separados):

1. **Fase 1 — Horizon** (paralelo entre servidores Horizon): guarda VDI machines y pools primero.
2. **Fase 2 — vCenter** (paralelo entre servidores vCenter): por cada VM, intenta matchear contra una VDI de Horizon ya guardada (por `external_id`/nombre/nombre-limpio, scopeado por origen). Si matchea, **enriquece** la fila existente (IP, host, CPU, RAM, disco, PowerState). Si no matchea, crea una fila nueva como "VM estática" (`_save_or_update_maquina`).
3. **Fase App Volumes** (paralelo entre servidores App Volumes): dominio de datos paralelo, no toca `maquinas`.
4. **Fase 3 — Reconciliación** (`_validar_y_reconciliar_payload`): fusiona duplicados por nombre limpio (con guardas por `external_id` desde hoy), genera `data/audit_reconciliacion.json`, cuenta eventos huérfanos reales vs. de VMs decomisionadas.

Todo corre en un `threading.Thread` daemon lanzado desde la ruta `POST /inventario/extraer` — no hay cola de trabajo real (Celery/RQ), es un thread suelto por extracción. `web/jobs.py` trackea el progreso (ver 1.7).

`_save_or_update_maquina_impl`: hace upsert por `external_id` (prioridad 1), luego por `(servidor_id, nombre)`, luego por nombre-limpio global — con una "regla anti-sobreescritura" que preserva el valor viejo si el nuevo llega vacío, excepto para un set de "campos dinámicos en vivo" (estado, IP, disco usado, etc.) que sí se pisan siempre.

### 1.5 Cómo se guarda — modelo de datos

SQLite (`data/inventario.db`, WAL mode), sin Postgres/MySQL. ~45 columnas en `Maquina` (tabla "estado actual", 1 fila por VM real — no crece con cada extracción). El historial de cambios va aparte en `MaquinaHistorial` (delta por campo). Snapshot en `InventarioSnapshot` (1 fila por corrida por servidor, agregados). Migraciones: Alembic configurado pero **no usado en la práctica** — todo vía `ALTER TABLE ... ADD COLUMN` en `try/except: pass` dentro de `init_db()`, más migraciones de tabla completa manuales cuando hace falta cambiar un constraint (SQLite no soporta `ALTER TABLE DROP CONSTRAINT`, hay que reconstruir la tabla — se hizo hoy para `Maquina`).

Tablas por dominio:
- **Inventario**: `maquinas`, `maquinas_historial`, `inventario_snapshots`, `vm_tareas_eventos`, `infra_eventos`, `pools`, `pool_entitlements`, `historial_usuario_vdi`.
- **App Volumes**: `appvolumes_aplicaciones`, `appvolumes_paquetes`, `appvolumes_programas`, `appvolumes_asignaciones`, `appvolumes_actividad`, `appvolumes_writables` (nueva hoy).
- **Directorio/AD**: `directorio_usuarios`, `maquina_usuario_dir`, `horizon_usuario_sid` (cache SID→nombre).
- **Sistema**: `servidores`, `usuarios`, `configuracion`, `alertas`, `tareas_extraccion`, `auditoria` (login/logout/acciones admin).

### 1.6 Scheduler y retención

`web/scheduler.py`, 2 hilos daemon independientes (ni Celery ni cron del SO):
- **AutoScheduler**: loop con `time.sleep(intervalo)`, dispara `_ejecutar_extraccion` si no hay una corriendo ya (chequea `jobs.get_active_job()` para no duplicar carga contra vCenter/Horizon). Intervalo configurable (off/1m/5m/15m/30m/1h), persistido en `Configuracion` para sobrevivir un restart. Usa la credencial temporal más reciente que no haya expirado — si nadie logueó con contraseña de sesión activa, no corre.
- **RetentionPurger**: una vez por día, borra `InventarioSnapshot`/`MaquinaHistorial` más viejos que `Configuracion.retencion_snapshots_dias` (default 90d) y `VMTareaEvento` de VMs decomisionadas hace más de esos días. Conserva siempre el snapshot más reciente de cada servidor.

### 1.7 Jobs / progreso en vivo (SSE)

`web/jobs.py`: estado de jobs de extracción + cola de eventos de progreso, **externalizado a Redis si `REDIS_URL` está configurada** (permite escalar a múltiples workers Waitress); si no, cae a dicts/`queue.Queue` en memoria del proceso (válido para 1 sola instancia). El stream real-time al navegador es SSE (`/inventario/stream/<job_id>`), implementado con `BLPOP` sobre una lista Redis (o la Queue local) — no pub/sub, porque pub/sub pierde el mensaje si el suscriptor conecta tarde.

### 1.8 Caché de lecturas (Redis, opcional)

`web/cache.py`: cachea KPIs calculados con TTL, mismo patrón de fallback silencioso a "calcular directo" si Redis no responde. **Ambos módulos** (`jobs.py` y `cache.py`) chequean Redis **una sola vez por proceso** (`_redis_checked` global) — si Redis no estaba listo en el momento exacto del primer chequeo, ese proceso queda en modo degradado para siempre hasta que se reinicie, aunque Redis se recupere después (confirmado como causa real de confusión en esta sesión).

### 1.9 Backend API (`web/routes/api.py`)

**67 rutas** bajo `/api` (Flask Blueprint), REST JSON. Cubre: KPIs y distribución (por pool/empresa/origen), semáforo de salud, detector de huérfanas (`/huerfanas`), alertas de disco (`/disco/criticos`, nuevo hoy), vista cruzada de masters (`/pools/masters`), SSE de eventos en tiempo real, CRUD de servidores/usuarios, trazabilidad completa por VM (`/maquinas/<id>/trazabilidad` — historial, eventos, App Volumes cruzado, pool/imagen), directorio de usuarios + verificación AD, auditoría, dashboard prefs. Protegido con `Flask-Limiter` (`10/min` en login) + CSRF double-submit (token en `/api/csrf-token`, header `X-CSRFToken` en cada mutación desde el frontend).

### 1.10 Frontend (React + Vite)

- **Servido estático**: Flask sirve `web/frontend/dist/assets` directo — no hay proxy a Vite embebido. Hay que correr `npm run build` para que los cambios se vean en `server.py`/`server_prod.py`. Para hot-reload real: `npm run dev` (puerto 3000, proxea `/api` a `127.0.0.1:5000`).
- **Cliente HTTP**: `axios` (`web/frontend/src/services/api.js`), con interceptor que agrega el token CSRF a mutaciones y dispara un evento `unauthorized` global en 401.
- **Estado**: `@tanstack/react-query` para data-fetching (cache, refetch por intervalo ligado al scheduler vía `useSchedulerInterval`), `zustand` para estado de UI (`useDashboardStore`, `useAuthStore`).
- **Dashboard**: sistema de widgets customizable — `DashboardGrid.jsx` con un mapa `WIDGET_COMPONENTS` (id → componente), `useDashboardStore` persiste layout/tamaño/visibilidad en `localStorage` + servidor (`/dashboard/prefs`), drag-and-drop vía `@hello-pangea/dnd`. Hoy tiene 18 widgets registrados (KPIs, gráficos, tablas, alertas).
- **Páginas principales**: Inventario (tabla completa con ficha por VM de varias pestañas: trazabilidad, eventos, App Volumes), Pools, Directorio, Actividad (feed), Extraer, Servidores, Usuarios, Auditoría, Reportes.
- Nota: hay un `web/frontend/src/store/widgetRegistry.js` que importa componentes que **no existen** en el repo actual — código muerto, nunca se importa desde `App.jsx`/`DashboardGrid.jsx`, no rompe el build por eso. Se puede borrar sin riesgo.

### 1.11 Seguridad implementada

Sesión Flask + `SECRET_KEY` obligatoria (sin fallback débil), passwords de `Servidor` cifradas con Fernet real (`FERNET_KEY` propia, obligatoria), rate limiting + lockout en login, CSRF double-submit, sin `admin/admin` por defecto (`must_change_password` forzado), AD query vía archivo en vez de interpolación de string (anti-RCE).

---

## PARTE 2 — Estado actual, hallazgos y prioridades

### 2.1 Resumen de esta sesión (2026-08-12/13)

Se encontraron y corrigieron **6 bugs de raíz reales**, verificados en vivo contra vCenter/Horizon/App Volumes de producción, no solo revisión de código:

1. **`Servidor.origen` es una `@property` de Python, no columna mapeada** — `filter_by(origen=...)` nunca matcheaba nada, para ningún valor. `horizon_srv_ids` quedaba `[]` en TODAS las corridas de vCenter, la práctica totalidad de la flota perdía su `estado_horizon` real cada vez que corría vCenter después de Horizon (confirmado con historial desde 2026-08-07). **Corregido**: filtrar por `_origen_str`.
2. **Respuestas de vSphere 7.0+ REST sin envolver** — 10 lugares en `core/vcenter_rest.py` hacían `.get("value")` asumiendo el formato viejo (REST 6.x envuelve en `{"value": {...}}`); en 7.0+ el objeto viene directo, y `.get("value")` daba `None` en silencio, sin excepción. Afectaba las 5 llamadas de detalle/guest-ops para el 100% de las VMs. **Corregido**: solo desenvolver si `"value"` está presente.
3. **`guest_OS`/`full_name` de vSphere a veces vienen como objeto de mensaje localizado** (`{"id":..., "default_message":..., "args":[]}`) en vez de string plano — se pasaba el dict crudo a SQLite (`type 'dict' is not supported`), rompiendo el `UPDATE` completo de esa VM en silencio (autoflush), perdiendo TODO lo demás que iba en el mismo flush (disco, tools, hardware). **Esta era la causa real y dominante** de por qué el 99% de la flota tenía datos fabricados/viejos pese a que el fetch funcionaba. **Corregido**: helper `_texto_vsphere()`.
4. **`UNIQUE(servidor_id, nombre)` en `Maquina`** asumía nombre único por servidor — vCenter real tiene VMs distintas con nombre idéntico (confirmado: 3 golden images de MZ con una copia vieja duplicada apagada, mismo nombre, MoRef distinto). Las dos competían por la misma fila. **Corregido**: constraint cambiada a `(servidor_id, external_id)` + guarda en el matching por nombre para no confundir dos `external_id` distintos; migración de schema aplicada a la DB real preservando las 1114 filas.
5. **`/api/pools/masters` ("en desuso") dependía solo de `Pool.master_vm_actual`**, que se llena parseando eventos de auditoría "Image Publish...succeeded" — en la práctica, solo 3 de 48 pools tenían ese evento capturado alguna vez. Resultado: casi todo salía "en desuso" y "VMs impactadas" subcontado a casi 0. **Corregido**: `Pool.master_moref` (de `provisioning_settings.parent_vm_id`, siempre presente, no depende de eventos) como fuente primaria.
6. **9 defaults fabricados** eliminados (CPU=2/RAM=4GB/PowerState="POWERED_OFF"/ConnectionState="connected" fijos en vCenter; BasicState="AVAILABLE" fijo en Horizon x2; fecha/usuario de eventos indistinguibles de reales cuando faltaban — ahora marcados como estimados).

Todo verificado con una extracción real completa post-fix: 774/840 VMs con disco real (antes: 8/825), 652 con `tools_status` real (antes: 0), masters de MZ correctamente separados.

### 2.2 Funcionalidad nueva agregada esta sesión

- Widget + endpoint `/api/disco/criticos`: VDI/VM con % de disco usado 80-100%, alerta temprana (antes solo se sabía al 2% libre).
- `Pool.master_moref`: identidad real de master por pool, no dependiente de eventos.
- `AppVolumesWritable` (modelo + fetch + cruce en ficha): Writable Volumes de App Volumes anclados a la VM/usuario, con aviso si hay más de uno acumulado. **Sin validar contra servidor real todavía** (ver 2.6).
- Concurrencia de Guest Ops bajada de 8→4 (el semáforo ya existía de una sesión anterior, contrario a lo que sugería el reporte externo de Gemini que decía que eran 16 sin límite).

### 2.3 Deuda técnica conocida — qué sigue abierto de `CLAUDE.md`

- ⚠️ **`migrations/versions/` sigue vacío** pese a Alembic configurado — sigue siendo todo ALTER TABLE best-effort. Abierto.
- ⚠️ **Estado de jobs/SSE en memoria de proceso** — **parcialmente resuelto**: si `REDIS_URL` está configurada y Redis responde, ya escala a multi-worker (`web/jobs.py`, agregado en una sesión anterior a esta). Sin Redis, sigue atado a un proceso. Verificar que `REDIS_URL` esté seteada en producción real, no solo en `.env` de dev.
- ⚠️ **`server.py` no está en la raíz** (archivado en `Archive/stray/server.py`) — sigue sin resolver, sigue sin `.bat` que lo levante.

### 2.4 Hallazgos nuevos de esta sesión — no en `CLAUDE.md` todavía

- **`web/frontend/src/store/widgetRegistry.js` es código muerto** — importa componentes que no existen (`KpiTotalVdisWidget`, `ChartPoolsWidget`, etc., nombres que no coinciden con los reales). No rompe nada porque nunca se importa, pero confunde a cualquiera que lo lea pensando que es el sistema de widgets real (el real es `DashboardGrid.jsx` + `useDashboardStore.js`). Candidato a borrar.
- **`appvolumes_actividad` da 0 filas siempre** — `GET /app_volumes/activity_logs` devuelve HTTP 403 Forbidden contra los 2 servidores reales (permisos de la cuenta de servicio usada, no bug de código). Sin esto, se pierde la única fuente con el link "en vivo" VM+usuario+AppStack real — hoy la ficha de App Volumes depende 100% de `appvolumes_asignaciones` (estático, no dice qué está montado *ahora mismo*).
- **`maquinas_historial` tiene 181,362 filas** para 1,114 VMs (~163 por VM) — con extracciones cada 5 min vía AutoScheduler, esto crece rápido. El RetentionPurger existe y corre (90 días default), pero vale la pena confirmar que el intervalo de retención configurado en producción sea razonable dado este volumen, y que el purger no esté fallando en silencio (solo loguea si borró algo, no hay alerta si `_purgar_historial_viejo` tira excepción más allá del print).
- **"Base de datos bloqueada" (`database is locked`)** — visto en vivo hoy: `[Horizon MZ] Error guardando autorizaciones de pools: sqlite3.OperationalError: database is locked`, cuando Horizon DT y MZ escriben en paralelo (2 threads del mismo `ThreadPoolExecutor(max_workers=4)`). SQLite solo permite 1 escritor genuino a la vez; hay un `_db_write_lock` (Python `threading.Lock`) pero no cubre `_guardar_pools_y_autorizaciones_horizon` con margen suficiente contra el timeout default de SQLite. No es nuevo, pero no estaba documentado como visto en producción.

### 2.5 Fortalezas reales (no solo "no tiene bugs")

- El código tiene una cultura fuerte de **dejar comentarios con la causa raíz y la fecha** cuando se corrige un bug real (no genéricos) — hace que auditar el historial de decisiones sea mucho más rápido que en un repo típico.
- Manejo defensivo consistente de **"dato ausente ≠ dato inventado"** ya era una preocupación activa antes de esta sesión (ver comentarios pre-existentes sobre "sin valores inventados" en `vcenter_rest.py` para OS/IP) — el problema no era falta de intención, era cobertura incompleta.
- Separación real entre lo estático (`AppVolumesAsignacion`) y lo dinámico en vivo (`AppVolumesActividad`) en el modelo de App Volumes — decisión de diseño correcta, aunque activity_logs esté bloqueado por permisos ahora mismo.
- Seguridad: nada de lo "grave" de la lista original de `CLAUDE.md` sigue abierto (SECRET_KEY, passwords en claro, admin/admin, RCE en AD) — todo verificado como resuelto con evidencia de código, no solo de memoria.

### 2.6 Puntos débiles / riesgos activos

- **App Volumes Writables sin validar contra servidor real** — la sesión de prueba de hoy falló del lado del servidor ("Unable to contact ActiveDirectory"), así que el mapeo de campos (`size_mb`, `used_mb`, `entity`, `attached_to`) está escrito contra documentación oficial, no contra un payload real. Tiene logging defensivo que avisa si el formato no matchea, pero hasta la próxima extracción real, es una hipótesis, no un hecho confirmado.
- **`activity_logs` de App Volumes bloqueado (403)** — sin esto, "qué está montado en qué VM ahora mismo" para AppStacks es inferido, no observado directamente.
- **Concurrencia de escritura SQLite** — con 8 servidores extrayendo en paralelo (2 fases de a 4), y ahora también writables/pools nuevos escribiendo más, el riesgo de "database is locked" no baja con más features, sube.
- **Sin medición de cobertura de tests** — 51 tests hoy (`test_auth`, `test_credenciales`, `test_jobs`, `test_kpi_utils`, `test_security_findings`, `test_directorio_dedup`), pero ninguno cubre el pipeline de extracción real (`_ejecutar_extraccion`, `_save_or_update_maquina_impl`, el matching Horizon↔vCenter) — que es justo donde vivían los 6 bugs de raíz de esta sesión. Los tests existentes no los habrían atrapado.
- **Dependencia de infraestructura externa para AD/GAL** — `ad_client.py` necesita PowerShell+RSAT+alcance al DC, `outlook_client.py` necesita Outlook local instalado. Ninguno de los dos es portable a un despliegue containerizado/headless sin repensar esa pieza.

### 2.7 Áreas de información no cubiertas — qué se podría extraer y no se extrae

Datos que las APIs ya exponen (confirmado en las respuestas reales vistas hoy) y que hoy no se persisten ni se muestran:

- **Datastores**: se extraen (`Datastore` model, capacidad/libre) pero **no hay endpoint ni vista** que los muestre — un datastore al límite de capacidad no es visible en ningún dashboard hoy, aunque el dato ya está en la DB.
- **Hosts ESXi**: `connection_state`/`power_state` se guardan pero `WidgetTopESXiHosts` no distingue un host caído de uno sano en el resumen.
- **`Maquina.annotation`** (notas de vSphere Client, ej. "No apagar - Servidor DB"): se extrae y se guarda, pero está omitida de la tabla principal de Inventario y de `VmTimelineView` — comentarios críticos de sysadmins quedan invisibles en la UI aunque estén en la DB.
- **Snapshots de VM reales de vCenter** (no confundir con `InventarioSnapshot`, que es snapshot de *nuestros datos*) — no se extraen. Una VM con snapshots viejos acumulados (fuente clásica de que un datastore se llene) no se detecta.
- **Resource Pools de vCenter** (límites de CPU/RAM configurados a nivel resource pool): se guarda el nombre (`resource_pool` string) pero no sus límites/reservas reales — no se puede saber si una VM está siendo throttleada por su resource pool.
- **Uso de red** (`nics`/tráfico) de las VMs: la API de detalle trae `nics`, no se persiste nada de eso hoy — sin visibilidad de qué VM satura la red del host.
- **Membresía de grupos AD**: `ad_client.py` resuelve usuarios individuales, no expande pertenencia a grupos — las asignaciones de App Volumes/Horizon por grupo AD (`entity_type=Group`) no se pueden resolver a usuarios finales reales, solo se ve "Grupo X" sin saber quién es miembro.
- **Licencias de VMware** (vCenter expone uso de licencias por producto/host) — cero visibilidad de si se está por pisar un límite de licenciamiento.
- **Tendencia histórica de capacidad** (forecast: "a este ritmo de crecimiento de disco, el datastore X se llena en N días") — hay historial (`MaquinaHistorial`) pero nada calcula tendencia, todo es snapshot del momento. Con `disco_criticos` ya viendo el % actual, el siguiente paso natural es proyectar cuándo una VM/datastore cruza el umbral, no solo alertar cuando ya lo cruzó.
- **Costos/chargeback**: no hay ningún cálculo de costo por VM/pool/empresa (CPU+RAM+disco asignado × algún factor) — dato que Finanzas/gerencia suele pedir en este tipo de sistemas y que ya está toda la materia prima (CPU, RAM, disco, empresa) para calcular.

### 2.8 Prioridades de mejora sugeridas (orden)

1. **Confirmar Writable Volumes contra un servidor real** en la próxima extracción — es la única pieza de esta sesión sin verificar en vivo.
2. **Investigar el 403 de `activity_logs`** — probablemente falta un permiso en la cuenta de servicio de App Volumes; sin esto, "qué VM tiene qué AppStack montado ahora" sigue siendo indirecto.
3. **Anclar Datastores/ESXi hosts/`annotation`** a la UI — el dato ya existe en la DB, es trabajo de frontend, no de extracción.
4. **Tests sobre el pipeline de extracción real** (`_save_or_update_maquina_impl`, matching Horizon↔vCenter, `_texto_vsphere`) — es donde vivían los bugs reales de esta sesión; los 51 tests actuales no tocan esa superficie.
5. **Revisar timeout/reintento de SQLite** para el error "database is locked" visto en producción hoy — subir `PRAGMA busy_timeout` o ampliar el scope de `_db_write_lock`.
6. **Snapshots de VM + Resource Pools** — extensión natural de lo que ya se extrae, mismo patrón que Datastores.

---

*Documento generado el 2026-08-13. Reemplaza como referencia de estado la sección "Deuda técnica y seguridad conocida" de `CLAUDE.md` — actualizar ese archivo con un puntero a este documento en la próxima edición.*
