# Documento de Decisiones de Diseño de Base de Datos — `inventario-vdi` (v3.0)

## 1. Resumen Ejecutivo
Se auditó y rediseñó el esquema de base de datos de `inventario-vdi` para resolver la deuda técnica de escalabilidad (crecimiento de 1M de filas por duplicación de snapshots), mantener el estándar estricto de **SQLite**, y profesionalizar la estructura con normalización en catálogos, auditoría avanzada, trazabilidad de cambios (deltas) e infraestructura para jobs asincrónicos.

---

## 2. Decisiones Principales de Diseño

### A. Patrón Estado Actual vs. Historial de Cambios (Crecimiento N a 1)
- **`maquinas`**: Pasa a representar el **estado físico actual** de la máquina en infraestructura (`UNIQUE(servidor_id, nombre)`). En cada re-extracción se actualizan los datos vía `UPDATE`.
- **`maquinas_historial`**: Registra **únicamente las deltas** (los atributos que realmente cambiaron entre extracciones). Reduce el consumo de almacenamiento en más de un 90%.
- **Flag `activo`**: En lugar de borrar máquinas no detectadas en un snapshot, se marca `activo = False`.

### B. Normalización con Tablas Catálogo
- **`origenes`**: Normaliza los segmentos (`dt`, `su`, `core`, `mz`).
- **`empresas`**: Catálogo normalizado para consolidar empresas sincronizadas desde Outlook/GAL.
- **`pools`**: Catálogo normalizado de pools de Horizon.
- **`datastores`**: Registro de capacidad y almacenamiento de vCenter.

### C. Auditoría y Trazabilidad Extendida
- **`auditoria_logs`**: `usuario_id` con `FK (ON DELETE SET NULL)` manteniendo `username` denormalizado.
- **`usuarios`**: Añadidos campos `intentos_fallidos`, `bloqueado_hasta`, `created_by_id`, `updated_at`.
- **`inventario_snapshots`**: Añadidos `iniciado_en`, `finalizado_en`, `duracion_segundos`, `disparado_por_id`, `tarea_id`.

### D. Preparación para Escalabilidad Futura (Jobs & Alertas)
- **`tareas_extraccion`**: Registra jobs en segundo plano ejecutados con `threading.Thread` (se descartó la columna `celery_task_id`: nunca se instaló Celery, decisión confirmada de quedarse con threading).
- **`alertas`**: Persistencia de inconsistencias (máquinas huérfanas, desconexiones, errores).
- **`configuracion`**: Tabla clave-valor para settings globales (retención de snapshots, TTL de sesión).
- **`maquina_ips`**: Soporte para IPs secundarias por VM.
- **`metricas_rendimiento`**: Tabla lista para series temporales de %CPU y %RAM.

---

## 3. Compatibilidad e Integridad
- **Propiedades Retrocompatibles**: Se mantuvieron properties en el modelo `Maquina` (`disk_gb`, `ip`, `empresa`, `pool`, `origen`) para no romper las consultas de las vistas existentes.
- **Alembic / Flask-Migrate**: Migraciones versionadas y reversibles configuradas en `/migrations`.
- **Base de datos**: Totalmente basada en **SQLite** nativo con SQLAlchemy.
