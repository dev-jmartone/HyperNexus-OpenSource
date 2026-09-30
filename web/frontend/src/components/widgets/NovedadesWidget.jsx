import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import {
  Sparkles,
  LogIn,
  LogOut,
  Trash2,
  Clock,
  Activity,
  Server,
  AlertTriangle,
  ShieldAlert,
  ClipboardList,
  Search,
  User,
} from 'lucide-react';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

// Fusion de NovedadesWidget + EventosRealtimeWidget (2026-09-02) -- eran dos widgets
// pegandole a las mismas 4 tablas (MaquinaHistorial/HistorialUsuarioVDI/VMTareaEvento/
// InfraEvento) con feeds casi identicos, uno con polling fijo de 5s. Un solo widget,
// un solo query, polling estandar del scheduler (cap 60s) en vez de 5s fijo.
const TABS = [
  { id: 'alertas', label: 'Alertas Infra', icon: AlertTriangle, color: 'rose', hint: 'Datastore/Host/Pool' },
  { id: 'seguridad', label: 'Seguridad', icon: ShieldAlert, color: 'rose', hint: 'Bloqueos/Login fallido' },
  { id: 'auditoria', label: 'Auditoría', icon: ClipboardList, color: 'indigo', hint: 'Quién hizo qué' },
  { id: 'nuevas', label: 'VMs Nuevas', icon: Sparkles, color: 'emerald', hint: 'Creadas/Clonadas' },
  { id: 'logins', label: 'Inicios Sesión', icon: LogIn, color: 'indigo', hint: 'Live' },
  { id: 'logouts', label: 'Logouts', icon: LogOut, color: 'amber', hint: 'Cierres' },
  { id: 'eliminadas', label: 'Eliminadas', icon: Trash2, color: 'rose', hint: 'Bajas' },
  { id: 'infra', label: 'Cambios Infra', icon: Activity, color: 'sky', hint: 'Host/Pool' },
];

// Misma key sirve tanto para leer el conteo (data.kpis[key]) como la lista (data[key]).
const DATA_KEY_BY_TAB = {
  alertas: 'alertas', seguridad: 'seguridad', auditoria: 'auditoria',
  nuevas: 'vms_nuevas', logins: 'inicios_sesion', logouts: 'logouts',
  eliminadas: 'vms_eliminadas', infra: 'cambios_infra',
};

// Tailwind JIT escanea el archivo por strings literales completos -- NO puede resolver
// clases armadas con template-literal (`bg-${color}-500`). Todas las variantes de color
// usadas por los KPI cards y badges tienen que existir como string completo en algun
// lado de este archivo, de ahi los 3 lookup maps de abajo en vez de interpolar.
const COLOR_CLASSES = {
  emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  indigo: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30',
  amber: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  rose: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
  sky: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
};

const CARD_ACTIVE_CLASSES = {
  emerald: 'bg-emerald-500/20 border-emerald-500/50 shadow-md shadow-emerald-500/10',
  indigo: 'bg-indigo-500/20 border-indigo-500/50 shadow-md shadow-indigo-500/10',
  amber: 'bg-amber-500/20 border-amber-500/50 shadow-md shadow-amber-500/10',
  rose: 'bg-rose-500/20 border-rose-500/50 shadow-md shadow-rose-500/10',
  sky: 'bg-sky-500/20 border-sky-500/50 shadow-md shadow-sky-500/10',
};

const CARD_TEXT_CLASSES = {
  emerald: 'text-emerald-400', indigo: 'text-indigo-400', amber: 'text-amber-400',
  rose: 'text-rose-400', sky: 'text-sky-400',
};

const CARD_HINT_CLASSES = {
  emerald: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  indigo: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  amber: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  rose: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
  sky: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
};

function EventIcon({ evt }) {
  const cls = 'w-4 h-4 shrink-0 mt-0.5';
  if (evt.tipo === 'seguridad') return <ShieldAlert className={`${cls} text-rose-400`} />;
  if (evt.tipo === 'auditoria') return <ClipboardList className={`${cls} text-indigo-400`} />;
  if (evt.tipo?.startsWith('alerta_')) return <AlertTriangle className={`${cls} ${CARD_TEXT_CLASSES[evt.color] || CARD_TEXT_CLASSES.sky}`} />;
  if (evt.tipo === 'creacion') return <Sparkles className={`${cls} text-emerald-400`} />;
  if (evt.tipo === 'eliminacion') return <Trash2 className={`${cls} text-rose-400`} />;
  if (evt.tipo === 'login') return <LogIn className={`${cls} text-indigo-400`} />;
  if (evt.tipo === 'logout') return <LogOut className={`${cls} text-amber-400`} />;
  return <Activity className={`${cls} text-sky-400`} />;
}

export function NovedadesWidget({ id, title }) {
  const [activeTab, setActiveTab] = useState('todos');
  const [searchQuery, setSearchQuery] = useState('');
  const { intervalMs } = useSchedulerInterval();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['novedades'],
    queryFn: () => api.get('/novedades'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-48 bg-slate-800/50 rounded-xl"></div>
      </WidgetWrapper>
    );
  }

  const kpis = data?.kpis || {};
  const stats = data?.stats_vivo || {};

  let currentItems = data?.eventos_recientes || [];
  if (DATA_KEY_BY_TAB[activeTab]) currentItems = data?.[DATA_KEY_BY_TAB[activeTab]] || [];

  if (searchQuery.trim()) {
    const q = searchQuery.toLowerCase();
    currentItems = currentItems.filter((evt) =>
      (evt.nombre_vm || '').toLowerCase().includes(q) ||
      (evt.usuario || '').toLowerCase().includes(q) ||
      (evt.servidor || '').toLowerCase().includes(q) ||
      (evt.detalle || '').toLowerCase().includes(q) ||
      (evt.titulo || '').toLowerCase().includes(q)
    );
  }

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="space-y-4">
        {/* Barra de estado en vivo -- antes vivia sola en EventosRealtimeWidget */}
        <div className="p-3 bg-slate-900/80 border border-slate-800/80 rounded-2xl flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-center space-x-3">
            <div className="relative flex items-center justify-center">
              <span className="w-3 h-3 rounded-full bg-emerald-500 animate-ping absolute" />
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 relative" />
            </div>
            <p className="text-[11px] text-slate-400">
              Última detección: <span className="font-semibold text-slate-200">{stats.ultimo_evento_hace_str || '—'}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="px-3 py-1 bg-slate-950/60 border border-slate-800 rounded-xl text-center">
              <div className="text-[9px] text-slate-500 uppercase font-mono">Última Hora</div>
              <div className="text-xs font-bold text-slate-100 font-mono">{stats.total_ultimahora ?? 0} evts</div>
            </div>
            <div className="px-3 py-1 bg-slate-950/60 border border-slate-800 rounded-xl text-center">
              <div className="text-[9px] text-slate-500 uppercase font-mono">Tasa Evts</div>
              <div className="text-xs font-bold text-indigo-300 font-mono">{stats.eventos_por_minuto ?? 0} /min</div>
            </div>
          </div>
        </div>

        {/* KPI Mini-Cards Summary */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const count = kpis[DATA_KEY_BY_TAB[tab.id]] ?? 0;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(isActive ? 'todos' : tab.id)}
                className={`p-2.5 rounded-xl border transition-all text-left flex items-center justify-between ${
                  isActive ? CARD_ACTIVE_CLASSES[tab.color] : 'bg-slate-900/60 border-slate-800 hover:bg-slate-800/60'
                }`}
              >
                <div>
                  <div className={`text-[10px] font-semibold flex items-center gap-1 ${CARD_TEXT_CLASSES[tab.color]}`}>
                    <Icon className="w-3.5 h-3.5" />
                    <span>{tab.label}</span>
                  </div>
                  <div className="text-lg font-black text-slate-100 mt-0.5">{count}</div>
                </div>
                <span className={`px-1.5 py-0.5 text-[9px] font-bold rounded-full border ${CARD_HINT_CLASSES[tab.color]}`}>
                  {tab.hint}
                </span>
              </button>
            );
          })}
        </div>

        {/* Buscador */}
        <div className="relative flex items-center">
          <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 pointer-events-none" />
          <input
            type="text"
            placeholder="Buscar VM, usuario, servidor..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8 pr-3 py-1 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-slate-200 focus:outline-none focus:border-indigo-500/50 w-full transition-all placeholder:text-slate-600"
          />
        </div>

        {/* Event Feed List */}
        <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
          {currentItems.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-xl">
              No hay eventos o novedades registradas en este filtro.
            </div>
          ) : (
            currentItems.map((evt, idx) => (
              <div
                key={idx}
                className="p-3 bg-slate-900/40 border border-slate-800/70 rounded-xl hover:bg-slate-800/40 transition-colors flex items-start justify-between gap-3 text-xs"
              >
                <div className="flex items-start space-x-2.5">
                  <EventIcon evt={evt} />
                  <div>
                    <div className="font-bold text-slate-200 flex items-center gap-2 flex-wrap">
                      <span>{evt.titulo}</span>
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase ${COLOR_CLASSES[evt.color] || COLOR_CLASSES.sky}`}>
                        {evt.badge}
                      </span>
                      {evt.servidor && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-indigo-300 border border-slate-700 flex items-center gap-1">
                          <Server className="w-2.5 h-2.5" /> {evt.servidor}
                        </span>
                      )}
                      {evt.tipo === 'creacion' && (
                        evt.es_nueva_real ? (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold">
                            🆕 Creada Reciente
                          </span>
                        ) : (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                            ℹ️ Existente Previa
                          </span>
                        )
                      )}
                    </div>
                    <p className="text-slate-400 text-[11px] mt-0.5">
                      {evt.detalle}
                      {evt.usuario && evt.usuario !== '—' && (
                        <span className="ml-2 font-semibold text-slate-300 inline-flex items-center gap-1">
                          <User className="w-3 h-3 text-indigo-400" />{evt.usuario}
                        </span>
                      )}
                    </p>
                  </div>
                </div>

                <div className="flex flex-col items-end text-[10px] text-slate-500 font-mono shrink-0 gap-1">
                  <div className="flex items-center">
                    <Clock className="w-3 h-3 mr-1 text-slate-600" />
                    {evt.fecha}
                  </div>
                  {evt.primera_deteccion && (
                    <span className="text-[9px] text-slate-600" title="Primera aparición en el sistema">
                      Alta: {evt.primera_deteccion}
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </WidgetWrapper>
  );
}
