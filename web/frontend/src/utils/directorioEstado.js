// Deriva el estado de Directorio (AD) de una autorización (AplicacionEntitlement o
// PoolEntitlement enriquecidos con 'directorio' por web/granja_utils.py). Dos vistas del
// mismo dato: una etiqueta para mostrar (nombre real de la persona cuando se puede) y una
// categoría fija para agrupar/contar en estadísticas.

/** Texto para mostrar en una fila (nombre completo si está activo en AD). */
export function estadoDirectorioLabel(auth) {
  if (auth.es_grupo) return 'Grupo AD';
  if (auth.directorio) {
    return auth.directorio.activo_ad ? (auth.directorio.nombre_completo || 'Activo en AD') : 'Inactivo en AD';
  }
  return 'No encontrado en Directorio';
}

/** Una de 4 categorías fijas, para agrupar/contar (no varía por persona). */
export function estadoDirectorioCategoria(auth) {
  if (auth.es_grupo) return 'Grupo AD';
  if (auth.directorio) return auth.directorio.activo_ad ? 'Activo en AD' : 'Inactivo en AD';
  return 'No encontrado en Directorio';
}
