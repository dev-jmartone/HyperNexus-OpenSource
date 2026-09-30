import React, { useState, useMemo } from 'react';
import { 
  Activity, 
  User, 
  Zap, 
  Cpu, 
  HardDrive, 
  Globe, 
  RefreshCw, 
  Calendar, 
  Search, 
  Filter, 
  ArrowRight,
  ShieldAlert,
  Clock,
  Layers,
  CheckCircle,
  ChevronDown,
  ChevronRight
} from 'lucide-react';
import { Badge } from '../ui/Badge';

export function VmTimelineView({ trazabilidadData, isLoading, vmName, embedded = false }) {
  const [categoryFilter, setCategoryFilter] = useState('all'); // 'all' | 'user' | 'state' | 'hardware' | 'system'
  const [collapsedDates, setCollapsedDates] = useState({});

  const toggleDateCollapse = (dateStr) => {
    setCollapsedDates((prev) => ({
      ...prev,
      [dateStr]: !prev[dateStr]
    }));
  };

  // Combine and unify all timeline events chronologically
  const unifiedEvents = useMemo(() => {
    if (!trazabilidadData) return [];
    const events = [];

    // 1. Add User Rotations
    (trazabilidadData.rotaciones || []).forEach((r) => {
      events.push({
        id: `rot-${r.id || Math.random()}`,
        type: 'user',
        categoryLabel: 'Rotación de Usuario',
        title: `Cambio de Usuario Asignado`,
        timestamp: r.detectado_en || '',
        userAnterior: r.usuario_anterior || 'Sin asignar',
        userNuevo: r.usuario_nuevo || 'Sin asignar',
        empresa: r.empresa_nueva || r.empresa_anterior || '—',
        rawDate: r.detectado_en || ''
      });
    });

    // 2. Add Deltas / Attribute Changes
    (trazabilidadData.cambios || []).forEach((c) => {
      let cat = 'state';
      const campo = (c.campo || '').toLowerCase();
      if (campo.includes('cpu') || campo.includes('ram') || campo.includes('disk') || campo.includes('memory')) {
        cat = 'hardware';
      } else if (campo.includes('creacion') || campo.includes('migracion') || campo.includes('eliminacion')) {
        cat = 'system';
      } else if (campo.includes('usuario')) {
        cat = 'user';
      }

      events.push({
        id: `delta-${c.id || Math.random()}`,
        type: cat,
        categoryLabel: c.campo,
        title: `Modificación de ${c.campo}`,
        timestamp: c.detectado_en || '',
        valAnterior: c.valor_anterior || '—',
        valNuevo: c.valor_nuevo || '—',
        rawDate: c.detectado_en || ''
      });
    });

    // 3. Add vCenter Events & Tasks
    (trazabilidadData.eventos || []).forEach((e) => {
      events.push({
        id: `vcevt-${e.id || Math.random()}`,
        type: 'system',
        categoryLabel: e.tipo === 'task' ? 'Tarea vCenter' : 'Evento vCenter',
        title: `${e.nombre_evento} (${e.usuario || 'vCenter'})`,
        timestamp: e.fecha || '',
        valAnterior: e.mensaje || '—',
        valNuevo: e.estado ? e.estado.toUpperCase() : 'OK',
        rawDate: e.fecha || ''
      });
    });

    // Sort by timestamp descending
    return events.sort((a, b) => (b.rawDate || '').localeCompare(a.rawDate || ''));
  }, [trazabilidadData]);

  // Filter events based on category
  const filteredEvents = useMemo(() => {
    return unifiedEvents.filter((ev) => categoryFilter === 'all' || ev.type === categoryFilter);
  }, [unifiedEvents, categoryFilter]);

  // Group events by Date string (e.g., "06/08/2026")
  const groupedEvents = useMemo(() => {
    const groups = {};
    filteredEvents.forEach((ev) => {
      const datePart = (ev.timestamp || 'Fecha desconocida').split(' ')[0] || 'Desconocida';
      if (!groups[datePart]) groups[datePart] = [];
      groups[datePart].push(ev);
    });
    return groups;
  }, [filteredEvents]);

  const getEventBadge = (type) => {
    switch (type) {
      case 'user':
        return {
          bg: 'bg-purple-500/10 text-purple-300 border-purple-500/30',
          dot: 'bg-purple-500',
          icon: <User className="w-3.5 h-3.5 text-purple-400" />
        };
      case 'hardware':
        return {
          bg: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
          dot: 'bg-emerald-500',
          icon: <Cpu className="w-3.5 h-3.5 text-emerald-400" />
        };
      case 'system':
        return {
          bg: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
          dot: 'bg-amber-500',
          icon: <RefreshCw className="w-3.5 h-3.5 text-amber-400" />
        };
      default:
        return {
          bg: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30',
          dot: 'bg-cyan-500',
          icon: <Zap className="w-3.5 h-3.5 text-cyan-400" />
        };
    }
  };

  if (isLoading) {
    return (
      <div className="py-12 text-center text-slate-400 animate-pulse flex flex-col items-center justify-center space-y-2">
        <Activity className="w-6 h-6 text-indigo-400 animate-spin" />
        <span>Cargando trazabilidad y deltas de cambios para {vmName}...</span>
      </div>
    );
  }

  return (
    <div className="space-y-4 text-xs">
      {/* Top Metric Summary Bar */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-slate-900/90 p-3 rounded-xl border border-slate-800 flex items-center space-x-3">
          <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Activity className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-400">Total Cambios</div>
            <div className="text-base font-bold text-slate-100">{trazabilidadData?.cambios?.length || 0}</div>
          </div>
        </div>

        <div className="bg-slate-900/90 p-3 rounded-xl border border-slate-800 flex items-center space-x-3">
          <div className="p-2 rounded-lg bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <User className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-400">Rotaciones Usuario</div>
            <div className="text-base font-bold text-slate-100">{trazabilidadData?.rotaciones?.length || 0}</div>
          </div>
        </div>

        <div className="bg-slate-900/90 p-3 rounded-xl border border-slate-800 flex items-center space-x-3">
          <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <Layers className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-400">Snapshots Evaluados</div>
            <div className="text-base font-bold text-slate-100">{trazabilidadData?.timeline?.length || 0}</div>
          </div>
        </div>
      </div>

      {/* Timeline Controls & Filter Bar */}
      <div className="flex items-center space-x-1 overflow-x-auto bg-slate-900/70 p-2.5 rounded-xl border border-slate-800">
        {[
          { id: 'all', label: 'Todos los Cambios' },
          { id: 'user', label: '👤 Usuarios' },
          { id: 'state', label: '⚡ Estado & Red' },
          { id: 'hardware', label: '💻 Hardware' },
          { id: 'system', label: '🔄 Sistema' },
        ].map((cat) => (
          <button
            key={cat.id}
            onClick={() => setCategoryFilter(cat.id)}
            className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all whitespace-nowrap cursor-pointer ${
              categoryFilter === cat.id
                ? 'bg-indigo-600 text-white shadow-xs'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/80'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Chronological Vertical Node Timeline */}
      {Object.keys(groupedEvents).length === 0 ? (
        <div className="py-12 text-center text-slate-500 bg-slate-900/40 rounded-xl border border-slate-800">
          No se encontraron eventos o cambios que coincidan con los filtros seleccionados.
        </div>
      ) : (
        <div className={`space-y-6 pr-1 ${embedded ? '' : 'max-h-[460px] overflow-y-auto'}`}>
          {Object.entries(groupedEvents).map(([dateStr, events]) => {
            const isCollapsed = !!collapsedDates[dateStr];
            return (
              <div key={dateStr} className="space-y-3">
                {/* Collapsible Date Accordion Header */}
                <div 
                  onClick={() => toggleDateCollapse(dateStr)}
                  className="sticky top-0 z-10 flex items-center space-x-2 bg-slate-950/90 hover:bg-slate-900 backdrop-blur-md py-1.5 px-2 rounded-xl border border-slate-800/80 cursor-pointer select-none transition-all group"
                >
                  {isCollapsed ? (
                    <ChevronRight className="w-4 h-4 text-indigo-400 group-hover:text-white transition-colors" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-indigo-400 group-hover:text-white transition-colors" />
                  )}
                  <Calendar className="w-3.5 h-3.5 text-indigo-400" />
                  <span className="font-bold text-slate-200 text-xs tracking-wide">{dateStr}</span>
                  <span className="text-[10px] text-slate-400 bg-slate-900 group-hover:bg-slate-800 px-2 py-0.5 rounded-full font-mono transition-colors">
                    {events.length} evento(s) {isCollapsed ? '(Minimizado)' : ''}
                  </span>
                  <div className="flex-1 h-px bg-slate-800/80" />
                </div>

                {/* Event Nodes List (rendered only if not collapsed) */}
                {!isCollapsed && (
                  <div className="relative pl-6 space-y-3 border-l-2 border-slate-800/80 ml-3">
                    {events.map((ev) => {
                      const style = getEventBadge(ev.type);
                      return (
                        <div key={ev.id} className="relative group">
                          {/* Timeline Node Icon Circle */}
                          <div className={`absolute -left-[31px] top-1.5 w-6 h-6 rounded-full ${style.bg} border flex items-center justify-center shadow-md`}>
                            {style.icon}
                          </div>

                          {/* Event Detail Card */}
                          <div className="bg-slate-900/80 hover:bg-slate-900 p-3 rounded-xl border border-slate-800/90 shadow-sm transition-all space-y-2">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center space-x-2">
                                <span className="font-bold text-slate-200">{ev.title}</span>
                                <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${style.bg}`}>
                                  {ev.categoryLabel}
                                </span>
                              </div>
                              <span className="font-mono text-[10px] text-slate-400 flex items-center">
                                <Clock className="w-3 h-3 mr-1 text-slate-500" /> {ev.timestamp}
                              </span>
                            </div>

                            {/* Diff Box */}
                            {ev.type === 'user' ? (
                              <div className="grid grid-cols-2 gap-2 bg-slate-950/80 p-2.5 rounded-lg border border-slate-800/80 font-mono text-xs">
                                <div className="space-y-0.5">
                                  <span className="text-[9px] uppercase font-bold text-slate-500">Propietario Saliente</span>
                                  <div className="text-slate-400 font-medium truncate">{ev.userAnterior}</div>
                                </div>
                                <div className="space-y-0.5">
                                  <span className="text-[9px] uppercase font-bold text-indigo-400">Propietario Entrante</span>
                                  <div className="text-indigo-300 font-bold truncate flex items-center">
                                    <span>{ev.userNuevo}</span>
                                  </div>
                                </div>
                              </div>
                            ) : (
                              <div className="flex flex-wrap items-center gap-2 bg-slate-950/80 p-2 rounded-lg border border-slate-800/80 font-mono text-xs">
                                <span className="text-[10px] text-slate-500 uppercase font-bold">Anterior:</span>
                                <span className="px-2 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-800">
                                  {ev.valAnterior}
                                </span>
                                <ArrowRight className="w-3 h-3 text-indigo-400 shrink-0" />
                                <span className="text-[10px] text-indigo-400 uppercase font-bold">Nuevo:</span>
                                <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 font-bold">
                                  {ev.valNuevo}
                                </span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
