import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { VmTimelineView } from '../modals/VmTimelineView';
import { VmEventsView } from '../modals/VmEventsModal';
import { VcSessionModal } from '../modals/VcSessionModal';
import { toastExito, toastError } from '../../utils/alerts';
import { getTeamsChatUrl, getVmCenterUrl } from '../../utils/navigation';
import { tiempoRelativo, formatFechaIngreso } from '../../utils/format';
import {
  Save,
  CheckCircle,
  Cpu,
  MemoryStick,
  HardDrive,
  History,
  Activity,
  FileText,
  UserCog,
  X,
  ExternalLink,
  Copy,
  MessageSquare,
  AlertTriangle,
  Wrench,
  Package,
  Server,
  Wifi,
  Image as ImageIcon,
  ShieldCheck,
  ShieldOff,
  Monitor,
  Check,
} from 'lucide-react';

// ── Colores por tipo de máquina -- misma paleta que los badges de InventarioPage, acá
// también manejan la franja de identidad del header (mejora 2026-09-04 v2). ──────────
const TIPO_COLOR = {
  MASTER: '#a78bfa',
  TEMPLATE: '#818cf8',
  VDI_POOL: '#34d399',
  VM_ESTATICA: '#94a3b8',
};

// Pill de estado -- variante propia de este panel (no el <Badge> genérico de tabla):
// borde de color sólido + ícono (check para segmentación, punto lleno para estado en
// vivo) en vez de solo texto sobre fondo tenue, más legible de un vistazo en la ficha.
const PILL_TONE = {
  success: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/40',
  info: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/40',
  warning: 'bg-amber-500/10 text-amber-400 border-amber-500/40',
  danger: 'bg-rose-500/10 text-rose-400 border-rose-500/40',
  neutral: 'bg-slate-800 text-slate-400 border-slate-700',
  purple: 'bg-purple-500/10 text-purple-400 border-purple-500/40',
};

function Pill({ tone = 'neutral', dot, check, children, title }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border ${PILL_TONE[tone]}`}>
      {dot && <span className="w-1.5 h-1.5 rounded-full bg-current" />}
      {check && <Check className="w-2.5 h-2.5" strokeWidth={3} />}
      {children}
    </span>
  );
}

function segmentacionBadge(tp, categoriaEstatica) {
  if (tp === 'VM_ESTATICA' && categoriaEstatica === 'Infraestructura Interna') {
    return <Pill tone="neutral" title="Agente/artefacto interno de vSphere u Horizon -- no es inventario de usuario/negocio">INFRA INTERNA</Pill>;
  }
  if (tp === 'VM_ESTATICA' && categoriaEstatica === 'RPA') {
    return <Pill tone="info" check>RPA</Pill>;
  }
  if (tp === 'VM_ESTATICA' && categoriaEstatica === 'Copia (no activa)') {
    return <Pill tone="warning">COPIA (VIEJA)</Pill>;
  }
  if (tp === 'VM_ESTATICA' && categoriaEstatica === 'VDI Huérfana (sin pool Horizon)') {
    return <Pill tone="danger" title="Nombre de VDI pero Horizon no tiene ningún registro con ese nombre">VDI HUÉRFANA</Pill>;
  }
  switch (tp) {
    case 'MASTER': return <Pill tone="purple" check>MASTER</Pill>;
    case 'TEMPLATE': return <Pill tone="info" check>PLANTILLA</Pill>;
    case 'VDI_POOL': return <Pill tone="success" check>VDI POOL</Pill>;
    case 'VM_ESTATICA': return <Pill tone="neutral">ESTÁTICA</Pill>;
    default: return null;
  }
}

function estadoHorizonBadge(status, tieneUsuario) {
  const s = (status || '').toUpperCase();
  if (!s) return <span className="text-slate-600 text-xs">—</span>;
  if (s.includes('N/A') || s.includes('VCENTER')) return <Pill tone="neutral">vCenter</Pill>;
  if (s === 'CONNECTED') return <Pill tone="success" dot>CONNECTED</Pill>;
  if (s === 'DISCONNECTED') return <Pill tone="warning" dot>DISCONNECTED</Pill>;
  if (s === 'AVAILABLE' && !tieneUsuario) {
    return (
      <span className="inline-flex items-center gap-1">
        <Pill tone="info" dot>AVAILABLE</Pill>
        <Pill tone="warning">HUÉRFANA</Pill>
      </span>
    );
  }
  if (s === 'AVAILABLE') return <Pill tone="info" dot>AVAILABLE</Pill>;
  if (s.includes('ERROR') || s.includes('UNREACHABLE') || s.includes('PROBLEM')) return <Pill tone="danger">{s}</Pill>;
  return <Pill tone="neutral">{s}</Pill>;
}

function iniciales(nombre) {
  if (!nombre) return '?';
  const partes = nombre.trim().split(/\s+/).filter(Boolean);
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
}

function copiarTexto(texto) {
  if (!texto) return;
  navigator.clipboard.writeText(texto).then(
    () => toastExito('Copiado al portapapeles.'),
    () => toastError('No se pudo copiar.')
  );
}

function Field({ label, value, mono, copiable }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 group">
      <span className="text-[11.5px] text-slate-500 shrink-0">{label}</span>
      <span className="flex items-center gap-1.5 min-w-0">
        <span className={`text-[13px] text-slate-200 text-right truncate ${mono ? 'font-mono' : ''}`}>
          {value || value === 0 ? value : <span className="text-slate-600">—</span>}
        </span>
        {copiable && value && (
          <button
            onClick={() => copiarTexto(value)}
            className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-slate-500 hover:text-indigo-400 transition-opacity shrink-0"
            title={`Copiar ${label}`}
          >
            <Copy className="w-3 h-3" />
          </button>
        )}
      </span>
    </div>
  );
}

function Section({ title, icon: Icon, children, action, className = '' }) {
  return (
    <div className={`bg-slate-800/40 border border-slate-700/60 rounded-xl p-3.5 ${className}`}>
      <div className="flex items-center justify-between mb-1">
        <h3 className="flex items-center gap-1.5 text-[10.5px] font-bold text-indigo-400 uppercase tracking-wider">
          {Icon && <Icon className="w-3 h-3" />}
          {title}
        </h3>
        {action}
      </div>
      <div className="divide-y divide-slate-800/60">{children}</div>
    </div>
  );
}

// Anillo de uso -- CPU no tiene un %/total real (no guardamos MHz por core), RAM/Disco
// sí: reemplaza la barra lineal plana por el mismo lenguaje visual que un summary de
// vSphere Client (gauges circulares), un poco más lejos: color semántico por severidad.
function pctColor(pct) {
  if (pct == null) return '#475569';
  if (pct >= 90) return '#fb7185';
  if (pct >= 70) return '#fbbf24';
  return '#34d399';
}

function RingCard({ icon: Icon, label, centerValue, pct, sub }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  const clamped = pct != null ? Math.max(0, Math.min(100, pct)) : null;
  const dash = clamped != null ? (clamped / 100) * c : 0;
  const color = pctColor(clamped);
  return (
    <div className="bg-slate-800/40 border border-slate-700/60 rounded-xl p-3 flex flex-col items-center text-center gap-1">
      <div className="relative w-[72px] h-[72px]">
        <svg viewBox="0 0 72 72" className="w-full h-full -rotate-90">
          <circle cx="36" cy="36" r={r} fill="none" stroke="currentColor" className="text-slate-800" strokeWidth="6.5" />
          {clamped != null && (
            <circle
              cx="36" cy="36" r={r} fill="none" stroke={color} strokeWidth="6.5" strokeLinecap="round"
              strokeDasharray={`${dash} ${c - dash}`}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="font-mono font-bold text-slate-100 text-[14px]">{centerValue}</span>
        </div>
      </div>
      <div className="flex items-center gap-1.5 text-slate-500">
        <Icon className="w-3 h-3" />
        <span className="text-[9.5px] font-bold uppercase tracking-wide">{label}</span>
      </div>
      {sub && <div className="font-mono text-[10px] text-slate-500">{sub}</div>}
    </div>
  );
}

// Card de persona -- misma forma para Usuario Asignado (dinámico, sesión Horizon) y
// Responsable (manual, MaquinaUsuarioDir), lado a lado en grid de 2 en vez de filas
// apiladas -- antes vivían en secciones separadas con tratamiento distinto (uno sin
// Teams ni avatar). Suma cruce con Directorio/AD (departamento, estado) cuando existe.
function PersonaCard({ label, nombre, teamsTarget, sub, activoAd, accion }) {
  const teamsUrl = nombre ? getTeamsChatUrl(teamsTarget ?? nombre) : null;
  return (
    <div className="bg-slate-800/40 border border-slate-700/60 rounded-xl p-3 flex items-start gap-2.5">
      <div className="w-9 h-9 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-[11px] font-bold text-slate-400 shrink-0">
        {nombre ? iniciales(nombre) : '—'}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[9.5px] uppercase font-bold text-slate-500 tracking-wide">{label}</div>
        {nombre ? (
          <div className="flex items-center gap-1.5 min-w-0 mt-0.5">
            <span className="text-[13.5px] font-semibold text-slate-200 truncate">{nombre}</span>
            {activoAd === false && (
              <span title="Usuario inactivo en Active Directory" className="shrink-0"><ShieldOff className="w-3 h-3 text-rose-400" /></span>
            )}
          </div>
        ) : (
          <div className="text-[13px] text-slate-600 italic mt-0.5">Sin asignar</div>
        )}
        {sub && <div className="text-[11px] text-slate-500 truncate mt-0.5">{sub}</div>}
        {activoAd === true && (
          <span className="inline-flex items-center gap-1 text-[9.5px] font-bold px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 mt-1.5">
            <ShieldCheck className="w-2.5 h-2.5" /> Activo en AD
          </span>
        )}
        {accion && <div className="flex items-center gap-1.5 mt-2">{accion}</div>}
      </div>
      {teamsUrl && (
        <a
          href={teamsUrl} target="_blank" rel="noopener noreferrer"
          className="p-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 transition-colors shrink-0"
          title="Chat en Microsoft Teams"
        >
          <MessageSquare className="w-3.5 h-3.5" />
        </a>
      )}
    </div>
  );
}

const TABS = [
  { id: 'ficha', label: 'Ficha', icon: FileText },
  { id: 'trazabilidad', label: 'Trazabilidad', icon: History },
  { id: 'eventos', label: 'Eventos', icon: Activity },
  { id: 'appvolumes', label: 'App Volumes', icon: Package },
];

export function VmDetailPanel({ vmId, onClose }) {
  const [activeTab, setActiveTab] = useState('ficha');
  const [editAnotacion, setEditAnotacion] = useState('');
  const [editEstado, setEditEstado] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isVcModalOpen, setIsVcModalOpen] = useState(false);

  const [showResponsablePicker, setShowResponsablePicker] = useState(false);
  const [responsableSearch, setResponsableSearch] = useState('');
  const [responsableResults, setResponsableResults] = useState([]);
  const [isResponsableSearching, setIsResponsableSearching] = useState(false);
  const [isAssigningResponsable, setIsAssigningResponsable] = useState(false);

  const { data: vm, isLoading, refetch } = useQuery({
    queryKey: ['maquina_detalle', vmId],
    queryFn: () => api.get(`/maquinas/${vmId}`),
    enabled: Boolean(vmId),
  });

  const { data: vcStatus } = useQuery({
    queryKey: ['vc_status'],
    queryFn: () => api.get('/auth/vc_status'),
    refetchInterval: 30000,
  });

  // Trazabilidad y App Volumes vienen del MISMO endpoint (ya trae ambos payloads) --
  // se pide una sola vez y se comparte entre esos 2 tabs, no dos fetches separados.
  const necesitaTrazabilidad = activeTab === 'trazabilidad' || activeTab === 'appvolumes';
  const { data: trazabilidadData, isLoading: isTrazLoading } = useQuery({
    queryKey: ['maquina_trazabilidad', vmId],
    queryFn: () => api.get(`/maquinas/${vmId}/trazabilidad`),
    enabled: Boolean(vmId) && necesitaTrazabilidad,
  });

  useEffect(() => {
    setActiveTab('ficha');
    setShowResponsablePicker(false);
    setSaveSuccess(false);
  }, [vmId]);

  useEffect(() => {
    if (vm) {
      setEditAnotacion(vm.annotation || '');
      setEditEstado(vm.estado || '');
    }
  }, [vm]);

  useEffect(() => {
    if (!showResponsablePicker || !responsableSearch.trim()) {
      setResponsableResults([]);
      return;
    }
    setIsResponsableSearching(true);
    const timer = setTimeout(async () => {
      try {
        const res = await api.get('/directorio/usuarios', { params: { q: responsableSearch.trim() } });
        setResponsableResults(Array.isArray(res) ? res.slice(0, 10) : []);
      } catch (e) {
        setResponsableResults([]);
      } finally {
        setIsResponsableSearching(false);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [responsableSearch, showResponsablePicker]);

  if (!vmId) return null;

  if (isLoading || !vm) {
    return (
      <div className="p-6 animate-pulse space-y-3">
        <div className="h-6 w-2/3 bg-slate-800/60 rounded" />
        <div className="h-4 w-1/3 bg-slate-800/60 rounded" />
        <div className="h-24 bg-slate-800/40 rounded-xl mt-4" />
        <div className="h-40 bg-slate-800/40 rounded-xl" />
      </div>
    );
  }

  const cambio = editAnotacion !== (vm.annotation || '') || editEstado !== (vm.estado || '');

  const handleSave = async () => {
    const anotacionCambio = editAnotacion !== (vm.annotation || '');
    if (anotacionCambio && vm.external_id && !vcStatus?.has_credentials) {
      setIsVcModalOpen(true);
      return;
    }
    try {
      setIsSaving(true);
      const res = await api.post(`/maquinas/${vm.id}/editar`, { annotation: editAnotacion, estado: editEstado });
      setIsSaving(false);
      setSaveSuccess(true);
      refetch();
      setTimeout(() => setSaveSuccess(false), 2500);
      if (res?.notas_sync_vcenter === 'error') {
        toastError('Anotación guardada localmente, pero no se pudo sincronizar con vCenter.');
      } else if (res?.notas_sync_vcenter === 'skipped_sin_vinculo') {
        toastError('Anotación guardada localmente. Esta VM no tiene vínculo con vCenter todavía.');
      }
    } catch (e) {
      setIsSaving(false);
      if (e?.response?.data?.requiere_sesion_vcenter) {
        setIsVcModalOpen(true);
      } else {
        toastError(e?.response?.data?.error || 'Error al guardar cambios');
      }
    }
  };

  const handleAssignResponsable = async (usuario) => {
    try {
      setIsAssigningResponsable(true);
      if (vm.responsable_vinculo_id) {
        await api.post(`/directorio/desvincular/${vm.responsable_vinculo_id}`);
      }
      await api.post('/directorio/vincular', {
        maquina_id: vm.id,
        directorio_usuario_id: usuario.id,
        tipo: 'principal',
      });
      setShowResponsablePicker(false);
      setResponsableSearch('');
      setResponsableResults([]);
      refetch();
      toastExito(`Responsable asignado: ${usuario.nombre_completo || usuario.username}`);
    } catch (e) {
      toastError(e?.response?.data?.error || 'Error al asignar responsable');
    } finally {
      setIsAssigningResponsable(false);
    }
  };

  const handleRemoveResponsable = async () => {
    if (!vm.responsable_vinculo_id) return;
    try {
      setIsAssigningResponsable(true);
      await api.post(`/directorio/desvincular/${vm.responsable_vinculo_id}`);
      refetch();
    } catch (e) {
      toastError('Error al quitar responsable');
    } finally {
      setIsAssigningResponsable(false);
    }
  };

  const toolsUp = (vm.tools_status || '').toUpperCase();
  const colorTipo = TIPO_COLOR[vm.tipo_provisionamiento] || '#475569';

  const ramPct = vm.ram_gb && vm.memory_usage_mb ? (vm.memory_usage_mb / 1024 / vm.ram_gb) * 100 : null;
  const diskPct = vm.disk_gb && vm.disk_used_gb != null ? (vm.disk_used_gb / vm.disk_gb) * 100 : null;

  // Banner de alertas -- antes in_error_state/maintenance_mode/connection_state no se
  // mostraban en ningún lado de la ficha (solo existían como columna oculta en la tabla
  // de Inventario). Acá es justo donde más importan: estás mirando ESTA VM puntual.
  const alertas = [];
  if (vm.in_error_state) alertas.push({ icon: AlertTriangle, text: 'Horizon reporta esta máquina en estado de error.', tone: 'danger' });
  if (vm.maintenance_mode) alertas.push({ icon: Wrench, text: 'En modo mantenimiento.', tone: 'warning' });
  if (vm.connection_state && vm.connection_state.toLowerCase() !== 'connected') {
    alertas.push({ icon: Wifi, text: `Estado de conexión vCenter: ${vm.connection_state}.`, tone: 'warning' });
  }
  // Mismo umbral y cálculo que /api/disco/criticos (KPI "Disco Crítico" del dashboard,
  // 80-100% de uso) -- antes esa señal solo vivía en un widget aparte, había que ir a
  // buscar la VM en esa lista para enterarse. Acá es donde más importa: mirando la VM.
  if (diskPct != null && diskPct >= 80) {
    alertas.push({
      icon: HardDrive,
      text: `Disco al ${Math.round(diskPct)}% de uso -- dentro del rango crítico (mismo umbral que el KPI "Disco Crítico" del dashboard).`,
      tone: diskPct >= 90 ? 'danger' : 'warning',
    });
  }

  const appsAsignadas = trazabilidadData?.appvolumes_apps || [];
  const writables = trazabilidadData?.appvolumes_writables;
  const actividadAv = trazabilidadData?.appvolumes_actividad || [];

  return (
    <div className="flex flex-col h-full">
      {/* Header -- identidad + estado. Franja de color por tipo (Master/Template/VDI/
          Estática) arriba de todo, y el mismo color en el ícono de identidad: se
          reconoce el tipo de máquina antes de leer una letra. */}
      <div className="border-b border-slate-800/80 shrink-0">
        <div className="h-[3px]" style={{ background: colorTipo }} />
        <div className="px-5 pt-4 pb-3">
          <div className="flex items-start gap-3">
            <div
              className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: `${colorTipo}26`, color: colorTipo }}
            >
              <Monitor className="w-[22px] h-[22px]" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 group">
                <span className="font-mono text-[15px] font-bold text-slate-100 truncate">{vm.nombre}</span>
                <button
                  onClick={() => copiarTexto(vm.nombre)}
                  className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-slate-500 hover:text-indigo-400 transition-opacity shrink-0"
                  title="Copiar nombre"
                >
                  <Copy className="w-3 h-3" />
                </button>
              </div>
              <div className="text-[12px] text-slate-500 mt-0.5 truncate">
                {vm.tipo || '—'} · {(vm.origen || '—').toUpperCase()}
                {vm.pool ? <> · Pool: <span className="text-slate-400">{vm.pool}</span></> : null}
              </div>
              {(vm.primera_deteccion || vm.updated_at) && (
                <div className="text-[10.5px] text-slate-600 mt-0.5">
                  {vm.primera_deteccion && <>Detectada {tiempoRelativo(vm.primera_deteccion)}</>}
                  {vm.primera_deteccion && vm.updated_at && ' · '}
                  {vm.updated_at && <>Actualizada {tiempoRelativo(vm.updated_at)}</>}
                </div>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <a
                href={getVmCenterUrl(vm)}
                target="_blank" rel="noopener noreferrer"
                className="w-8 h-8 rounded-lg border border-slate-800 bg-slate-900/60 flex items-center justify-center text-slate-500 hover:text-indigo-400 hover:border-indigo-500/40 transition-colors"
                title="Abrir en vCenter"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
              {onClose && (
                <button onClick={onClose} className="w-8 h-8 rounded-lg border border-slate-800 bg-slate-900/60 flex items-center justify-center text-slate-500 hover:text-slate-200 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
          <div className="flex items-center flex-wrap gap-1.5 mt-3">
            {segmentacionBadge(vm.tipo_provisionamiento, vm.categoria_estatica)}
            {estadoHorizonBadge(vm.estado_horizon, vm.usuario_asignado)}
            {toolsUp && (
              <span
                className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                  toolsUp === 'RUNNING'
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                    : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${toolsUp === 'RUNNING' ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                Tools {vm.tools_status}
              </span>
            )}
            {vm.estado && <Pill tone="info" title="Estado operacional manual">{vm.estado}</Pill>}
          </div>

          {/* Tabs tipo segmented-control -- antes eran underline tabs pegados al borde
              del header; esto separa mejor "identidad" de "navegación" y es más fácil
              de tocar (target más grande, sin depender del borde para ver el activo). */}
          <div className="flex gap-1 mt-4 bg-slate-950/60 p-1 rounded-xl w-fit max-w-full overflow-x-auto">
            {TABS.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id)}
                  className={`flex items-center gap-1.5 text-[12px] font-semibold px-3 py-1.5 rounded-lg transition-colors whitespace-nowrap ${
                    activeTab === t.id
                      ? 'bg-slate-800 text-indigo-400 shadow-sm'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {activeTab === 'ficha' && (
          <div className="space-y-5">
            {saveSuccess && (
              <div className="p-2.5 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-xs font-semibold flex items-center gap-2">
                <CheckCircle className="w-4 h-4" /> Cambios guardados.
              </div>
            )}

            {alertas.length > 0 && (
              <div className="space-y-1.5">
                {alertas.map((a, idx) => {
                  const AIcon = a.icon;
                  const tone = a.tone === 'danger'
                    ? 'bg-rose-500/10 border-rose-500/25 text-rose-300'
                    : 'bg-amber-500/10 border-amber-500/25 text-amber-300';
                  return (
                    <div key={idx} className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-medium ${tone}`}>
                      <AIcon className="w-3.5 h-3.5 shrink-0" />
                      {a.text}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Recursos -- CPU no tiene un %/total real que mostrar (no guardamos MHz por
                core, queda solo la cuenta de vCPUs); RAM/Disco sí, muestran el anillo con
                el % real de uso, color semántico (verde/ámbar/rojo por severidad). */}
            <div className="grid grid-cols-3 gap-2.5">
              <RingCard icon={Cpu} label="CPU" centerValue={vm.cpu || '—'} sub={vm.cpu_usage_mhz ? `${vm.cpu_usage_mhz} MHz` : null} />
              <RingCard
                icon={MemoryStick} label="RAM"
                centerValue={ramPct != null ? `${Math.round(ramPct)}%` : (vm.ram_gb ? `${vm.ram_gb} GB` : '—')}
                pct={ramPct}
                sub={vm.ram_gb ? (vm.memory_usage_mb ? `${Math.round(vm.memory_usage_mb / 1024)} / ${vm.ram_gb} GB` : `${vm.ram_gb} GB`) : null}
              />
              <RingCard
                icon={HardDrive} label="Disco"
                centerValue={diskPct != null ? `${Math.round(diskPct)}%` : (vm.disk_gb ? `${vm.disk_gb} GB` : '—')}
                pct={diskPct}
                sub={vm.disk_gb ? `${vm.disk_used_gb ?? '—'} / ${vm.disk_gb} GB` : null}
              />
            </div>

            {/* Dos columnas -- antes todo era una sola lista larga de filas; Infraestructura
                y Red son dominios distintos, separarlos en columnas reduce el scroll y deja
                escanear cada uno de un vistazo (paridad con el layout de doble panel del
                summary de vSphere Client, con más campos que el original). */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
              <Section title="Infraestructura" icon={Server}>
                <Field label="vCenter Host" value={vm.vcenter_host} mono copiable />
                <Field label="Resource Pool" value={vm.resource_pool} />
                <Field label="Datastores" value={vm.datastores} />
                <Field label="Hardware Version" value={vm.hardware_version} mono />
                <Field label="Estado Conexión" value={vm.connection_state} />
                <Field label="Carpeta (vCenter real)" value={vm.folder} />
              </Section>

              <Section title="Red" icon={Wifi} className="mt-5 sm:mt-0">
                <Field label="Dirección IP" value={vm.ip} mono copiable />
                <Field label="DNS" value={vm.dns} mono copiable />
                <Field label="IP Cliente Horizon" value={vm.client_ip} mono />
                <Field label="Equipo Cliente" value={vm.client_name} mono />
                <Field label="Gateway/UAG" value={vm.gateway_name ? `${vm.gateway_name}${vm.gateway_ip ? ` (${vm.gateway_ip})` : ''}` : null} mono />
              </Section>
            </div>

            {(vm.master_vm_actual || vm.snapshot_actual) && (
              <Section title="Imagen del Pool" icon={ImageIcon}>
                <Field label="Master VM actual" value={vm.master_vm_actual} mono />
                <Field label="Snapshot actual" value={vm.snapshot_actual} mono />
              </Section>
            )}

            <Section title="Estado y ciclo de vida">
              <Field label="Empresa" value={vm.empresa} />
              <Field label="Estado Agente Horizon" value={vm.estado_horizon_agente} />
              <Field label="Persistencia" value={vm.persistencia} />
              <Field label="Manager" value={vm.manager} />
              <Field label="Versión Agent" value={vm.agent_version} mono />
              <Field label="Fecha último ingreso" value={formatFechaIngreso(vm.fecha_ultimo_ingreso)} />
            </Section>

            <div>
              <h3 className="text-[11px] font-bold text-indigo-400 uppercase tracking-wider mb-1.5">Personas</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <PersonaCard
                  label="Usuario · sesión Horizon"
                  nombre={vm.usuario_asignado}
                  teamsTarget={vm.usuario_asignado_email || vm.usuario_asignado}
                  sub={vm.usuario_asignado_departamento || vm.usuario_asignado_email || null}
                  activoAd={vm.usuario_asignado_activo_ad}
                />
                <PersonaCard
                  label="Responsable · manual"
                  nombre={vm.responsable}
                  teamsTarget={vm.responsable_username || vm.responsable_email}
                  sub={vm.responsable && (vm.responsable_username || vm.responsable_email)
                    ? [vm.responsable_username, vm.responsable_email].filter(Boolean).join(' · ')
                    : 'Persiste entre extracciones'}
                  accion={
                    <>
                      {vm.responsable && (
                        <Button variant="secondary" size="sm" disabled={isAssigningResponsable} onClick={handleRemoveResponsable}>Quitar</Button>
                      )}
                      <Button variant="secondary" size="sm" icon={UserCog} onClick={() => setShowResponsablePicker((v) => !v)}>
                        {vm.responsable ? 'Cambiar' : 'Asignar'}
                      </Button>
                    </>
                  }
                />
              </div>

              {showResponsablePicker && (
                <div className="bg-slate-900/80 p-2.5 mt-2 rounded-xl border border-slate-800 space-y-2">
                  <input
                    type="text" autoFocus
                    value={responsableSearch}
                    onChange={(e) => setResponsableSearch(e.target.value)}
                    placeholder="Buscar por nombre, usuario o email..."
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                  {isResponsableSearching && <div className="text-[11px] text-slate-500">Buscando...</div>}
                  {!isResponsableSearching && responsableSearch.trim() && responsableResults.length === 0 && (
                    <div className="text-[11px] text-slate-500">Sin resultados.</div>
                  )}
                  {responsableResults.length > 0 && (
                    <div className="max-h-36 overflow-y-auto divide-y divide-slate-800">
                      {responsableResults.map((u) => (
                        <button
                          key={u.id} type="button" disabled={isAssigningResponsable}
                          onClick={() => handleAssignResponsable(u)}
                          className="w-full text-left px-2 py-1.5 hover:bg-slate-800 rounded text-xs text-slate-200"
                        >
                          <div className="font-semibold">{u.nombre_completo || u.username}</div>
                          <div className="text-slate-500 text-[10px]">{u.username}{u.email ? ` · ${u.email}` : ''}</div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Edición manual -- tinte propio para separar "esto es editable" de todo lo
                de arriba (solo lectura, viene de la extracción). */}
            <div className="bg-indigo-500/10 border border-indigo-500/25 rounded-xl p-3.5">
              <h3 className="text-[11px] font-bold text-indigo-400 uppercase tracking-wider mb-2.5">Edición manual</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 mb-1">Estado operacional</label>
                  <input
                    type="text"
                    value={editEstado}
                    onChange={(e) => setEditEstado(e.target.value)}
                    placeholder="Ej: Esperando contacto, Eliminar, Ok..."
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-[13px] text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 mb-1">Anotación</label>
                  <textarea
                    value={editAnotacion}
                    onChange={(e) => setEditAnotacion(e.target.value)}
                    placeholder="Notas sobre este equipo o su usuario..."
                    rows={3}
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-[13px] text-slate-100 focus:outline-none focus:border-indigo-500 resize-none"
                  />
                  {vm.external_id && (
                    <p className="text-[10.5px] text-slate-500 mt-1">Se sincroniza como Notes real en vCenter al guardar.</p>
                  )}
                </div>
                <Button variant="primary" size="sm" icon={Save} disabled={isSaving || !cambio} onClick={handleSave}>
                  {isSaving ? 'Guardando...' : 'Guardar cambios'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'trazabilidad' && (
          <VmTimelineView trazabilidadData={trazabilidadData} isLoading={isTrazLoading} vmName={vm.nombre} embedded />
        )}

        {activeTab === 'eventos' && (
          <VmEventsView maquinaId={vm.id} vmName={vm.nombre} embedded />
        )}

        {activeTab === 'appvolumes' && (
          <div className="space-y-4">
            {isTrazLoading ? (
              <div className="py-8 text-center text-slate-400 animate-pulse text-xs">Cargando datos de App Volumes...</div>
            ) : (
              <>
                <Section title={`Aplicaciones Asignadas (${appsAsignadas.length})`} icon={Package}>
                  {appsAsignadas.length === 0 ? (
                    <div className="py-4 text-center text-slate-500 text-xs italic">Sin asignaciones de App Volumes para esta VM o su usuario.</div>
                  ) : (
                    <div className="divide-y divide-slate-800/60">
                      {appsAsignadas.map((a, idx) => (
                        <div key={idx} className="py-2 flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-[13px] text-slate-200 truncate">{a.aplicacion_nombre || a.paquete_nombre || `App ${a.av_id}`}</div>
                            {a.paquete_nombre && a.aplicacion_nombre && <div className="text-[10.5px] text-slate-500 truncate">Paquete: {a.paquete_nombre}</div>}
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <Badge variant="neutral">{a.entity_type}</Badge>
                            {a.delivery && <Badge variant="info">{a.delivery}</Badge>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </Section>

                <Section title={`Writable Volumes (${writables?.cantidad || 0})`} icon={HardDrive}
                  action={writables?.cantidad > 1 ? <Badge variant="warning">{writables.total_gb} GB acumulados</Badge> : null}
                >
                  {(writables?.cantidad || 0) === 0 ? (
                    <div className="py-4 text-center text-slate-500 text-xs italic">Sin Writable Volumes detectados.</div>
                  ) : (
                    <div className="divide-y divide-slate-800/60">
                      {writables.items.map((w, idx) => (
                        <div key={idx} className="py-2 flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-[13px] text-slate-200 truncate">{w.owner_display_name || w.nombre}</div>
                            <div className="text-[10.5px] text-slate-500 truncate">{w.attached_to ? `Montado en ${w.attached_to}` : 'Desmontado'}</div>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <span className="font-mono text-[12px] text-slate-300">{w.size_gb ?? '—'} GB</span>
                            <Badge variant={w.estado === 'Attached' ? 'success' : 'neutral'}>{w.estado || '—'}</Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </Section>

                <Section title={`Actividad Reciente (${actividadAv.length})`} icon={Activity}>
                  {actividadAv.length === 0 ? (
                    <div className="py-4 text-center text-slate-500 text-xs italic">Sin eventos de attach/login registrados.</div>
                  ) : (
                    <div className="divide-y divide-slate-800/60">
                      {actividadAv.map((e, idx) => (
                        <div key={idx} className="py-2 flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="font-mono text-[12px] text-slate-300 truncate">{e.source_name || '—'} → {e.target_name || '—'}</div>
                            <div className="text-[10.5px] text-slate-500">{e.event_time || 'Sin fecha'}</div>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <Badge variant="neutral">{e.accion || '—'}</Badge>
                            <Badge variant={e.resultado === 'Success' ? 'success' : 'danger'}>{e.resultado || '—'}</Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </Section>
              </>
            )}
          </div>
        )}
      </div>

      <VcSessionModal isOpen={isVcModalOpen} onClose={() => setIsVcModalOpen(false)} onSaved={() => setIsVcModalOpen(false)} />
    </div>
  );
}
