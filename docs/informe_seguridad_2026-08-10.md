# Informe de Seguridad — Inventario VDI
**Fecha:** 2026-08-10 (actualizado 2026-08-10 tras aplicar correcciones)
**Alcance:** `web/`, `core/` (motor REST activo), dependencias (`requirements.txt`, `web/frontend/package.json`)
**Metodología:** revisión estática dirigida (grep + lectura de código) + `pip-audit`/`npm audit` + PoC ejecutados contra un entorno de test aislado (nunca contra `data/inventario.db` real) para confirmar explotabilidad real, no solo teórica.

## Resumen ejecutivo

| Severidad | Cantidad | Estado |
|---|---|---|
| Crítico | 2 | ✅ 2/2 resueltos |
| Alto | 2 | ✅ 2/2 resueltos (+1 gap adicional encontrado y resuelto durante el trabajo de MEDIO-1, ver ALTO-1) |
| Medio | 4 | ✅ 3/4 resueltos — MEDIO-3 (TLS) queda abierto a propósito, es decisión del usuario (ver esa sección) |
| Positivo confirmado | 6 | — |

Las dos vulnerabilidades críticas permitían, en cadena, **compromiso total de la aplicación** (lectura de secretos → forjar sesión de admin, y ejecución remota de comandos) desde una cuenta autenticada de **cualquier rol**, no solo admin. **Ambas ya están corregidas y con test de regresión.**

---

## ✅ RESUELTO — CRÍTICO-1 — Path traversal en descarga de reportes → fuga de `.env` → compromiso total

**Archivo:** `web/routes/reportes.py:70-75`, ruta `GET /reportes/descargar/<nombre>`

**Confirmado con PoC real** (entorno de test aislado): una sesión de usuario **no-admin** pidiendo
```
GET /reportes/descargar/..%5C.env
```
recibió el contenido completo de `.env`: `SECRET_KEY`, `FERNET_KEY`, `REDIS_URL`.

**Impacto:** con `SECRET_KEY` un atacante puede **forjar cookies de sesión de Flask firmadas** declarándose `admin` sin conocer ninguna contraseña (Flask solo verifica la firma, no consulta la DB). Con `FERNET_KEY` puede desencriptar **cualquier credencial de vCenter/Horizon** guardada en `sesiones_credenciales_temp`.

**Causa:** `send_file(os.path.join(REPORTES_DIR, nombre))` sin sanitizar `nombre`. En Windows, backslashes en el parámetro (`..\.env`) escapan el directorio — el conversor `<string>` de Flask solo bloquea `/`, no `\`.

**Contraste:** `web/routes/api.py:2389-2396` (mismo propósito, `/api/reportes/descargar/<filename>`) **sí** usa `send_from_directory` correctamente — inconsistencia entre dos rutas casi idénticas para el mismo fin.

**Fix:**
```python
return send_from_directory(REPORTES_DIR, nombre, as_attachment=True, download_name=nombre)
```
`send_from_directory` valida internamente (vía `werkzeug.utils.safe_join`) que el path resuelto siga dentro del directorio, en cualquier SO.

**Aplicado:** `web/routes/reportes.py` ahora usa `send_from_directory` (el fix descrito arriba, tal cual).

**Test de regresión:** `tests/test_security_findings.py::test_path_traversal_en_descarga_de_reportes_bloqueado`

---

## ✅ RESUELTO — CRÍTICO-2 — Inyección de comandos PowerShell (RCE) vía verificación de Active Directory

**Archivo:** `core/ad_client.py:57-59` (`ADClient.verificar_usuarios`)

**Cadena de ataque completa, sin necesitar rol admin:**
1. `POST /api/importar_extraidos` (sin restricción de rol) — cualquier usuario autenticado planta un `username` malicioso en `DirectorioUsuario`.
2. `POST /api/verificar_ad` o `GET /stream_verificar_ad` (tampoco restringidos a admin) — el mismo atacante dispara la verificación.

**Causa:**
```python
json_usernames = json.dumps(chunk, ensure_ascii=False)
ps_script = f"""
$rawInput = '{json_usernames}'
...
"""
```
JSON **no escapa comillas simples**. Un username como `a'; <código PowerShell>; $x='b` rompe el string de PowerShell y el resto se ejecuta como código, con los privilegios del proceso del servidor (típicamente una cuenta de servicio de dominio con lectura de AD — potencialmente más).

**Fix recomendado:** no interpolar el JSON en el texto del script. Escribir el JSON a un archivo temporal (ya se escribe un `.ps1` temporal de todos modos) y que PowerShell lo **lea**:
```powershell
$rawInput = Get-Content -Raw -Path $jsonPath
```
en vez de recibirlo embebido en el string. Alternativa mínima (más frágil, no usar como única defensa): `.Replace("'", "''")` sobre cada username antes de interpolar.

**Aplicado:** `core/ad_client.py` ya no interpola el JSON en el texto del script — lo escribe a un archivo temporal separado (`_ad_query_<token>.json`) y el `.ps1` lo lee con `Get-Content -Raw | ConvertFrom-Json`. Ambos temporales se borran en el `finally`.

**Test de regresión (mockeando `subprocess.run`, inspecciona el `.ps1` real generado):** `tests/test_security_findings.py::test_ad_client_usernames_maliciosos_no_llegan_al_texto_del_script`

---

## ✅ RESUELTO — ALTO-1 — Sin límite de intentos de login (fuerza bruta)

**Archivo:** `web/routes/auth_routes.py` `login()`; columnas `Usuario.intentos_fallidos`/`bloqueado_hasta` (`web/db.py`) **existen en el modelo pero nunca se leen ni escriben**.

**Impacto:** un atacante puede probar contraseñas indefinidamente contra cualquier username conocido — sin cooldown, sin captcha, sin más consecuencia que una fila pasiva en `AuditoriaLog`.

**Fix:** incrementar `intentos_fallidos` en cada fallo; al superar un umbral (ej. 5) setear `bloqueado_hasta = ahora + N minutos`; chequear `bloqueado_hasta` **antes** de `check_password` y rechazar con el mismo mensaje genérico (no revelar que la cuenta está bloqueada vs. contraseña incorrecta, para no facilitar enumeración de usuarios).

**Aplicado:** `web/routes/auth_routes.py::login()` (vista Jinja legacy) implementa exactamente ese fix (`MAX_INTENTOS_FALLIDOS=5`, `BLOQUEO_MINUTOS=15`).

**Gap adicional encontrado al implementar MEDIO-1 (CSRF):** el fix original solo cubría la vista Jinja. El **SPA React (producto activo)** autentica contra `web/routes/api.py::auth_login` (`POST /api/auth/login`), que tenía la misma falta de límite de intentos y quedó sin corregir en la primera pasada. Ya corregido — reusa las mismas constantes `MAX_INTENTOS_FALLIDOS`/`BLOQUEO_MINUTOS`.

**Tests de regresión:** `tests/test_auth.py::test_login_bloquea_tras_intentos_fallidos_repetidos`, `tests/test_auth.py::test_login_correcto_antes_del_umbral_resetea_intentos`, `tests/test_security_findings.py::test_usuario_se_bloquea_tras_intentos_fallidos_repetidos`, `tests/test_security_findings.py::test_api_auth_login_se_bloquea_tras_intentos_fallidos_repetidos`

---

## ✅ RESUELTO — ALTO-2 — Dependencias con CVEs conocidos

`pip-audit` sobre `requirements.txt`:

| Paquete | Versión actual | CVEs | Fix |
|---|---|---|---|
| `cryptography` | 43.0.3 | PYSEC-2026-35, PYSEC-2026-1284, PYSEC-2026-2141, PYSEC-2026-3553, PYSEC-2026-3554, GHSA-537c-gmf6-5ccf (6 en total) | 49.0.0 |
| `python-dotenv` | 1.0.1 | PYSEC-2026-2270 | 1.2.2 |

`cryptography` es la librería que cifra **cada credencial guardada** (Fernet) — prioridad alta pese a no tener PoC de explotación específico contra este uso puntual.

`npm audit` sobre `web/frontend`: **0 vulnerabilidades** — limpio.

**Fix:** `pip install -U cryptography python-dotenv`, correr `run_tests.bat`, redeploy.

**Aplicado:** `requirements.txt` fijado a `cryptography==50.0.0` / `python-dotenv==1.2.2`. `pip-audit` post-upgrade: **0 vulnerabilidades**. Suite completa sigue en verde (Fernet/credenciales sin cambios de comportamiento).

---

## ✅ RESUELTO — MEDIO-1 — CSRF exento en todo el blueprint `/api/*`

`web/app.py:90` — `csrf.exempt(bp_api)` cubre **todos** los endpoints POST/PUT/DELETE bajo `/api/`, sin token CSRF. Mitigado parcialmente por `SESSION_COOKIE_SAMESITE=Lax` (bloquea la mayoría de los vectores prácticos de CSRF en navegadores modernos), pero no es una defensa dedicada. Riesgo real bajo-medio dado el SameSite, pero vale una decisión consciente (header custom tipo `X-Requested-With`, o doble-submit cookie, es el patrón estándar para SPAs).

**Aplicado:** patrón doble-submit token. `GET /api/csrf-token` (`web/routes/api.py`) expone el token vía `flask_wtf.csrf.generate_csrf()`, accesible sin login (ver `allowed_endpoints` en `web/app.py`). El SPA (`web/frontend/src/services/api.js`) lo cachea en memoria y lo manda en header `X-CSRFToken` en cada request POST/PUT/PATCH/DELETE vía un interceptor de axios; se invalida (`invalidateCsrfToken()`) tras login/logout porque ambos hacen `session.clear()` en el backend, lo que rota el token de sesión. `csrf.exempt(bp_api)` fue eliminado — `CSRFProtect` ahora cubre `/api/*` igual que las vistas Jinja. Se agregó un `errorhandler(CSRFError)` que devuelve JSON (no la página HTML default) cuando la ruta es `/api/*`.

**Tests de regresión:** `tests/test_security_findings.py::test_csrf_bloquea_post_a_api_sin_token`, `tests/test_security_findings.py::test_csrf_token_valido_permite_post_a_api`

## ✅ RESUELTO — MEDIO-2 — `SESSION_COOKIE_SECURE` no configurado

Solo `HTTPONLY` y `SAMESITE` están seteados en `web/app.py`. Sin `SECURE=True`, la cookie de sesión viaja en claro si el deployment no fuerza HTTPS de punta a punta. **Fix:** activar `SESSION_COOKIE_SECURE=True` si hay TLS en el deployment (reverse proxy delante de Waitress).

**Aplicado:** `SESSION_COOKIE_SECURE = (FORCE_HTTPS == "1")`, nueva env var documentada en `.env.example`, default `0` para no romper el deployment HTTP actual. Activarla requiere que **todo** el tráfico llegue por HTTPS (incluido el proxy).

**Tests de regresión:** `tests/test_security_findings.py::test_session_cookie_secure_off_por_defecto`, `tests/test_security_findings.py::test_session_cookie_secure_se_activa_con_force_https`

## ⚠️ ABIERTO A PROPÓSITO — MEDIO-3 — Validación de certificado TLS deshabilitada contra vCenter/Horizon

Todo `core/vcenter_rest.py` y `core/horizon_rest.py`: `ctx.check_hostname=False; ctx.verify_mode=CERT_NONE`. Permite MITM en la red interna. Común/aceptable si los certificados son self-signed sin CA corporativa — pero debería ser una **decisión explícita y documentada**, no el default silencioso. Si existe CA interna, considerar validar contra ella en vez de deshabilitar la verificación por completo.

**No corregido en esta pasada, a propósito:** forzar verificación de certificado rompería la conexión con TODOS los vCenter/Horizon actuales (certificados self-signed internos, confirmado durante toda la sesión). Corregirlo requiere saber si existe una CA interna corporativa contra la cual validar — decisión pendiente del usuario, no técnica.

## ✅ RESUELTO — MEDIO-4 — Sin rate limiting general en la API

Ningún `Flask-Limiter` ni equivalente. Cualquier endpoint (no solo login) puede recibir tráfico sin límite — riesgo de abuso/DoS a nivel aplicación. La mitigación de DDoS volumétrico de red es responsabilidad de la capa de infraestructura (WAF, proxy), no del código Flask en sí.

**Aplicado:** `Flask-Limiter` (`web/extensions.py`, singleton compartido para evitar import circular). Límite estricto de `10 por minuto` por IP en `/login` (Jinja) y `/api/auth/login` (SPA) — capa extra sobre el lockout por cuenta, cubre también el escaneo de usernames inexistentes que nunca dispara el lockout. Límite general de `300 por minuto` por IP en el resto de `/api/*`. Storage en memoria del proceso, coherente con el resto del sistema (threading, no multi-worker).

**Tests de regresión:** `tests/test_security_findings.py::test_rate_limit_bloquea_login_tras_muchos_intentos_por_ip`

---

## Positivos confirmados (no re-derivar en el futuro)

- **Contraseñas:** `werkzeug` PBKDF2 (`generate_password_hash`/`check_password_hash`) — correcto.
- **SQL Injection:** revisión exhaustiva de todo el acceso a datos — 100% vía ORM de SQLAlchemy parametrizado. Las únicas queries con f-strings son `ALTER TABLE` de auto-migración con valores **hardcodeados del código fuente** (nunca input de usuario) — no explotables.
- **XSS:** sin `| safe` en ningún template Jinja, sin `dangerouslySetInnerHTML`/`eval` en React — auto-escaping intacto en ambos lados.
- Sin `eval`/`exec`/`os.system`/`subprocess(shell=True)` en el código activo.
- **`admin`/`admin` por defecto: ya no existe** — requiere `ADMIN_BOOTSTRAP_USER`/`ADMIN_BOOTSTRAP_PASSWORD` explícitos en `.env`, y fuerza `must_change_password=True`. *(CLAUDE.md está desactualizado en este punto — corregir la nota ahí.)*
- **`SECRET_KEY` con fallback hardcodeado: ya no existe** — `create_app()` explota (`RuntimeError`) si falta. *(CLAUDE.md desactualizado en este punto también.)*

---

## Suite de tests agregada esta sesión

- **Backend:** 46 tests (`pytest tests/`) — cubre `kpi_utils`, credenciales encriptadas, `web/jobs.py` (cancelación, detección de jobs abandonados), auth/roles, CSRF, rate limiting, y los hallazgos de este informe como regresión.
- **Frontend:** 24 tests (`npm test` en `web/frontend`) — utils de navegación, `IntervalSelector`, `useSchedulerInterval`.
- **Automatización:** `run_tests.bat` en la raíz corre ambas suites con un solo comando, siempre disponible.

Durante la construcción de esta suite se encontró y corrigió un bug real (no de seguridad): `web/jobs.py` — la rama en memoria (sin Redis) de `push_event` no marcaba un job como `cancelled`, solo la rama Redis lo hacía.

---

## Estado final

1. ✅ **CRÍTICO-1** (path traversal) — resuelto.
2. ✅ **CRÍTICO-2** (RCE PowerShell) — resuelto.
3. ✅ **ALTO-1** (fuerza bruta, Jinja + SPA) — resuelto.
4. ✅ **ALTO-2** (CVEs de dependencias) — resuelto, `pip-audit` limpio.
5. ✅ **MEDIO-1** (CSRF en `/api/*`), **MEDIO-2** (`SESSION_COOKIE_SECURE`), **MEDIO-4** (rate limiting) — resueltos.
6. ⚠️ **MEDIO-3** (TLS sin verificar) — abierto a propósito, pendiente de decisión del usuario sobre CA interna.
