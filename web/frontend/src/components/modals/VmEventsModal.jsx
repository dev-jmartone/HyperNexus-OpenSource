import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { X, Search, Activity, ShieldAlert, CheckCircle2, Clock, User, HardDrive } from 'lucide-react';
import { Badge } from '../ui/Badge';

export function VmEventsView({ maquinaId, vmName, embedded = false }) {
  const [search, setSearch] = useState('');
  const [filterTipo, setFilterTipo] = useState(''); // 'task' | 'evento' | ''

  const { data, isLoading } = useQuery({
    queryKey: ['vm_tareas_eventos', maquinaId],
    queryFn: () => api.get(`/maquinas/${maquinaId}/tareas_eventos`),
    enabled: !!maquinaId,
  });

  const eventos = data?.eventos || [];

  const eventosFiltrados = eventos.filter((ev) => {
    if (filterTipo && ev.tipo !== filterTipo) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      (ev.nombre_evento || '').toLowerCase().includes(q) ||
      (ev.mensaje || '').toLowerCase().includes(q) ||
      (ev.usuario || '').toLowerCase().includes(q)
    );
  });

  return (
    <div className="flex flex-col h-full space-y-3">
      {/* Toolbar */}
      <div className="p-3 bg-slate-950/60 rounded-xl border border-slate-800 flex flex-col sm:flex-row items-center gap-3">
        <div className="relative flex-1 w-full">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar en tareas/eventos por mensaje, tipo o usuario..."
            className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-4 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <button
            onClick={() => setFilterTipo('')}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors ${
              filterTipo === '' ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            Todos ({eventos.length})
          </button>
          <button
            onClick={() => setFilterTipo('task')}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors ${
              filterTipo === 'task' ? 'bg-purple-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            Tareas ({eventos.filter(e => e.tipo === 'task').length})
          </button>
          <button
            onClick={() => setFilterTipo('evento')}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors ${
              filterTipo === 'evento' ? 'bg-cyan-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            Eventos ({eventos.filter(e => e.tipo === 'evento').length})
          </button>
        </div>
      </div>

      {/* Content list */}
      <div className={`space-y-2 pr-1 ${embedded ? '' : 'flex-1 overflow-y-auto max-h-[55vh]'}`}>
        {isLoading ? (
          <div className="py-16 text-center text-xs text-slate-400 animate-pulse">
            Obteniendo historial de tareas y eventos vCenter...
          </div>
        ) : eventosFiltrados.length === 0 ? (
          <div className="py-16 text-center text-xs text-slate-500">
            No hay tareas ni eventos vCenter registrados para esta máquina virtual.
          </div>
        ) : (
          eventosFiltrados.map((ev) => (
            <div
              key={ev.id}
              className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 hover:border-slate-700 transition-colors flex flex-col space-y-1.5"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                    ev.tipo === 'task'
                      ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                      : 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                  }`}>
                    {ev.tipo === 'task' ? '⚙️ TAREA' : '📋 EVENTO'}
                  </span>
                  <span className="text-xs font-bold text-slate-200 font-mono">{ev.nombre_evento}</span>
                </div>

                <span className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
                  <Clock className="w-3 h-3 text-slate-500" />
                  {ev.fecha}
                </span>
              </div>

              <p className="text-xs text-slate-300 font-sans leading-relaxed">{ev.mensaje}</p>

              <div className="pt-1 flex items-center justify-between text-[11px] text-slate-400 font-mono">
                <span className="flex items-center gap-1 text-slate-400">
                  <User className="w-3 h-3 text-slate-500" />
                  Iniciado por: <strong className="text-slate-300 font-semibold">{ev.usuario || 'vCenter System'}</strong>
                </span>
                <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold uppercase ${
                  ev.estado === 'error' ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' :
                  ev.estado === 'warning' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                  'bg-slate-800 text-slate-400'
                }`}>
                  {ev.estado}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export function VmEventsModal({ isOpen, onClose, maquinaId, vmName }) {
  if (!isOpen || !maquinaId) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-4 px-6 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Activity className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-100">Supervisar vCenter — Tareas y Eventos</h2>
              <p className="text-xs text-slate-400 font-mono">
                VM: <span className="text-indigo-400 font-bold">{vmName || `ID #${maquinaId}`}</span>
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 flex-1 overflow-hidden">
          <VmEventsView maquinaId={maquinaId} vmName={vmName} />
        </div>
      </div>
    </div>
  );
}
