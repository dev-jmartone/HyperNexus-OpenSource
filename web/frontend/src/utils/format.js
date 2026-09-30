// Helpers de formato para mostrar datos crudos de Horizon/vCenter en la UI.

/**
 * Acorta el path completo de una snapshot de Horizon (ej.
 * "/VM limpia + instaladores/Docker Configuraciones ALL/V4_.../V9_QUALYS+TEAMS")
 * al último segmento con un backslash adelante (ej. "\V9_QUALYS+TEAMS") -- es la
 * parte que identifica la snapshot real, el resto es la cadena de snapshots padre.
 */
export function acortarSnapshot(path) {
  if (!path) return '';
  const partes = String(path).split('/').filter(Boolean);
  if (partes.length === 0) return path;
  return '\\' + partes[partes.length - 1];
}

/**
 * Tiempo relativo simple, sin dependencia nueva -- alcanza con minutos/horas/días/meses
 * para lifecycle de una VM (no hace falta precisión de segundos ni i18n de librería).
 */
export function tiempoRelativo(iso) {
  if (!iso) return null;
  const diffMs = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diffMs)) return null;
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return 'recién';
  if (min < 60) return `hace ${min} min`;
  const hs = Math.floor(min / 60);
  if (hs < 24) return `hace ${hs} h`;
  const dias = Math.floor(hs / 24);
  if (dias < 30) return `hace ${dias} d`;
  const meses = Math.floor(dias / 30);
  return `hace ${meses} mes${meses > 1 ? 'es' : ''}`;
}

/**
 * `Maquina.fecha_ultimo_ingreso` es texto libre en DB: fecha ISO real (formato que
 * escribe el backend desde 2026-09-08, ver _normalizar_fecha_ingreso en
 * web/routes/inventario.py), epoch crudo en filas viejas (bug histórico: Horizon
 * devuelve start_time de sesión en epoch ms, se guardaba sin convertir -- de ahí se
 * veía "1725734400000" en vez de una fecha) o texto/fecha manual (edición desde la
 * ficha, formato libre). Se muestra formateada cuando se puede interpretar como fecha
 * real; si no matchea ningún formato conocido se deja el texto tal cual (nunca se
 * inventa una fecha ni se descarta la nota manual).
 */
export function formatFechaIngreso(valor) {
  if (valor === null || valor === undefined || valor === '') return null;
  const raw = String(valor).trim();
  if (!raw) return null;

  let fecha = null;
  if (/^\d{10,13}$/.test(raw)) {
    const n = Number(raw);
    fecha = new Date(raw.length > 10 ? n : n * 1000);
  } else if (/^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?/.test(raw)) {
    fecha = new Date(raw);
  }
  if (!fecha || Number.isNaN(fecha.getTime())) return raw;

  const texto = fecha.toLocaleString('es-AR', { dateStyle: 'medium', timeStyle: 'short' });
  const rel = tiempoRelativo(fecha.toISOString());
  return rel ? `${texto} (${rel})` : texto;
}
