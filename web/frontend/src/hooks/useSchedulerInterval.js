/**
 * useSchedulerInterval.js
 *
 * Hook centralizado que lee el intervalo de extracción automática
 * desde el backend (/config/intervalo) y lo expone en milisegundos
 * para que todos los widgets usen un `refetchInterval` dinámico
 * coherente con lo que muestra el IntervalSelector del navbar.
 */
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';

// Mapa de clave → milisegundos (refleja INTERVAL_OPTIONS del backend)
// 'off' pausa la EXTRACCIÓN automática (ver web/scheduler.py), pero los widgets
// igual releen la BD local cada minuto — barato, y sigue habiendo datos nuevos
// de extracciones manuales aunque el scheduler esté pausado.
const KEY_TO_MS = {
  'off': 60_000,
  '1m':  60_000,
  '5m':  300_000,
  '15m': 900_000,
  '30m': 1_800_000,
  '1h':  3_600_000,
};

// Fallback seguro: si no hay config aún, usar 5 minutos
const DEFAULT_MS = 300_000;

/**
 * Retorna el intervalo de polling (en ms) que los widgets deben usar
 * como su `refetchInterval`.
 *
 * Para que los KPIs no queden colgados esperando N minutos antes del
 * primer update visible, forzamos un cap de 60s para el polling de BD
 * (lectura barata). El scheduler backend extrae de vSphere cada N min;
 * el frontend relee la BD cada min(intervalMs, 60s) para reflejar esos
 * datos tan pronto como estén disponibles.
 *
 * @param {Object} options
 * @param {boolean} [options.capAt60s=true] - Si true, limita el refetch a máx 60s
 * @returns {{ intervalMs: number, intervalKey: string, isLoaded: boolean }}
 */
export function useSchedulerInterval({ capAt60s = true } = {}) {
  const { data, isSuccess } = useQuery({
    queryKey: ['scheduler_interval'],
    queryFn: () => api.get('/config/intervalo'),
    // Recheck cada 60s para detectar cambios hechos desde otro tab/sesión
    refetchInterval: 60_000,
    // Mantener dato anterior mientras recarga (sin parpadear)
    staleTime: 30_000,
  });

  const rawMs = KEY_TO_MS[data?.key] ?? DEFAULT_MS;
  // Cap: máx 60s entre refetches de widgets (la extracción real del scheduler
  // puede ser cada 5min+, pero los widgets refrescan contra BD local, barato)
  const intervalMs = capAt60s ? Math.min(rawMs, 60_000) : rawMs;

  return {
    intervalMs,
    intervalKey: data?.key ?? '5m',
    isLoaded: isSuccess,
  };
}
