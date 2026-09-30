import { create } from 'zustand';
import api from '../services/api';

// w/h son unidades de grilla (react-grid-layout): 3 columnas en desktop, cada celda
// vertical vale ROW_HEIGHT_PX. x/y se calculan al armar el layout inicial (packer) o
// al guardar lo que el usuario arma arrastrando/redimensionando -- no van hardcodeados
// en la lista de defaults para no tener que mantenerlos a mano.
export const DEFAULT_WIDGETS = [
  { id: 'kpi_total_vdi',               title: 'Total VDI & Conexiones',                            category: 'kpi',      visible: true,  w: 3, h: 4  },
  { id: 'novedades_eventos',           title: 'Novedades y Eventos (Alertas, Seguridad, Auditoría, VMs, Logins)', category: 'kpi', visible: true, w: 3, h: 10 },
  { id: 'kpi_desglose_servidor_origen', title: 'Desglose por Servidor y Origen (Encendidas/Apagadas)', category: 'kpi',      visible: true,  w: 3, h: 9  },
  { id: 'top_esxi_hosts',              title: 'Carga por vCenter & Estado de Hosts ESXi',          category: 'vsphere',  visible: true,  w: 1, h: 8  },
  { id: 'infraestructura',             title: 'Datastores y Hosts ESXi',                           category: 'vsphere',  visible: true,  w: 1, h: 7  },
  // Fusión de consumo_cpu/consumo_ram/consumo_disco en un solo widget con tabs (2026-09-07,
  // auditoría de dashboard) -- los 3 mostraban la misma idea sobre el mismo endpoint,
  // ocupando 3 columnas por algo que un switcher resuelve en 1. IDs viejos: si quedaban en
  // localStorage/dashboard_prefs de algún usuario, mergeOrdered() los descarta solos (ya
  // no están en DEFAULT_WIDGETS) sin romper nada -- mismo mecanismo que limpiezas previas.
  { id: 'consumo_recursos',            title: '% VMs Encendidas (CPU/RAM/Disco asignado, no uso real)', category: 'recursos', visible: true,  w: 1, h: 5  },
  { id: 'disco_criticos',              title: 'VDI/VM en Riesgo de Espacio (80-100% uso)',         category: 'status',   visible: true,  w: 3, h: 7  },
  { id: 'vms_huerfanas',               title: 'Escritorios Huérfanos',                             category: 'kpi',      visible: true,  w: 1, h: 6  },
  { id: 'pools_capacidad',             title: 'Capacidad de Pools (Sin Disponibles / Ocupación Alta)', category: 'status', visible: true,  w: 1, h: 7  },
  { id: 'salud_agentes',               title: 'VMware Tools & Horizon Agent Caídos',               category: 'status',   visible: true,  w: 1, h: 7  },
  { id: 'writables_huerfanos',         title: 'Write Volumes Huérfanos (App Volumes)',             category: 'status',   visible: true,  w: 1, h: 7  },
  { id: 'vdis_retenidas',              title: 'VDIs Retenidas por Cuentas AD Deshabilitadas',      category: 'status',   visible: true,  w: 1, h: 7  },
  { id: 'dist_origen',                 title: 'Distribución por Origen/vCenter (VDI vs VM Estática)', category: 'chart', visible: true,  w: 1, h: 8  },
  { id: 'infra_interna',               title: 'Consumo de Infraestructura Interna (vCLS/Instant Clone)', category: 'vsphere', visible: true, w: 1, h: 7  },
];

export const GRID_COLS = 3;
export const ROW_HEIGHT_PX = 34;

const STORAGE_KEY = 'vdi_dashboard_widgets_v10'; // v10: modelo de layout real (x/y/w/h) en vez de size fijo

/** Empaqueta widgets sin x/y en columnas (algoritmo shelf/skyline simple) -- el resto
 * (compactType vertical de react-grid-layout) se encarga de ajustar huecos despues,
 * en vivo, cuando el usuario mueve/oculta/redimensiona cosas. */
function packMissingPositions(widgets) {
  const colHeights = new Array(GRID_COLS).fill(0);
  // Primero "reservar" el espacio de los que YA tienen posicion propia.
  for (const w of widgets) {
    if (typeof w.x === 'number' && typeof w.y === 'number') {
      const width = Math.min(w.w || 1, GRID_COLS);
      for (let x = w.x; x < w.x + width && x < GRID_COLS; x++) {
        colHeights[x] = Math.max(colHeights[x], w.y + (w.h || 4));
      }
    }
  }
  return widgets.map((w) => {
    if (typeof w.x === 'number' && typeof w.y === 'number') return w;
    const width = Math.min(w.w || 1, GRID_COLS);
    let bestX = 0, bestY = Infinity;
    for (let x = 0; x <= GRID_COLS - width; x++) {
      const y = Math.max(...colHeights.slice(x, x + width));
      if (y < bestY) { bestY = y; bestX = x; }
    }
    for (let x = bestX; x < bestX + width; x++) colHeights[x] = bestY + (w.h || 4);
    return { ...w, x: bestX, y: bestY };
  });
}

// Merge saved prefs with defaults (safe: adds new widgets, keeps user customizations)
function mergeWithDefaults(savedPrefs) {
  if (!savedPrefs || !Array.isArray(savedPrefs)) return packMissingPositions(DEFAULT_WIDGETS);
  const merged = DEFAULT_WIDGETS.map(dw => {
    const saved = savedPrefs.find(w => w.id === dw.id);
    return saved ? { ...dw, ...saved } : dw;
  });
  return packMissingPositions(merged);
}

// Reconstruct ordered list (saved order first, then new widgets appended)
function mergeOrdered(savedPrefs) {
  const merged = mergeWithDefaults(savedPrefs);
  if (!savedPrefs || !Array.isArray(savedPrefs)) return merged;
  const savedIds = savedPrefs.map(w => w.id);
  const known = merged.filter(w => savedIds.includes(w.id));
  const isNewWidget = merged.filter(w => !savedIds.includes(w.id));
  return [...known.sort((a, b) => savedIds.indexOf(a.id) - savedIds.indexOf(b.id)), ...isNewWidget];
}

// Initial load from localStorage
const getInitialWidgets = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return mergeOrdered(JSON.parse(saved));
  } catch (e) {
    console.error('Error loading dashboard layout from localStorage', e);
  }
  return packMissingPositions(DEFAULT_WIDGETS);
};

// Debounce helper for server saves
let _saveTimer = null;
function debouncedSaveToServer(widgets) {
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = setTimeout(async () => {
    try {
      const prefs = widgets.map(w => ({ id: w.id, visible: w.visible, x: w.x, y: w.y, w: w.w, h: w.h }));
      await api.post('/dashboard/prefs', { prefs });
    } catch (e) {
      console.warn('[Dashboard] No se pudo guardar prefs en servidor:', e);
    }
  }, 800);
}

export const useDashboardStore = create((set, get) => ({
  widgets: getInitialWidgets(),
  isCustomizing: false,

  setCustomizing: (val) => set({ isCustomizing: val }),

  // Sync from server (called on login / page load)
  syncFromServer: async () => {
    try {
      const res = await api.get('/dashboard/prefs');
      if (res?.prefs && Array.isArray(res.prefs)) {
        const merged = mergeOrdered(res.prefs);
        set({ widgets: merged });
        localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
      }
    } catch (e) {
      console.warn('[Dashboard] No se pudo cargar prefs del servidor:', e);
    }
  },

  // Toggle visibility
  toggleWidgetVisibility: (id) => {
    const updated = get().widgets.map(w =>
      w.id === id ? { ...w, visible: !w.visible } : w
    );
    set({ widgets: updated });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    debouncedSaveToServer(updated);
  },

  // Aplica un layout completo de react-grid-layout (drag y/o resize) -- se llama en
  // cada onLayoutChange, mapea cada {i,x,y,w,h} de vuelta al widget por id.
  applyLayout: (layout) => {
    const byId = Object.fromEntries(layout.map(l => [l.i, l]));
    const updated = get().widgets.map(w => {
      const l = byId[w.id];
      if (!l) return w;
      return { ...w, x: l.x, y: l.y, w: l.w, h: l.h };
    });
    set({ widgets: updated });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    debouncedSaveToServer(updated);
  },

  // Reset to defaults
  resetLayout: () => {
    const fresh = packMissingPositions(DEFAULT_WIDGETS);
    set({ widgets: fresh });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(fresh));
    debouncedSaveToServer(fresh);
  },
}));
