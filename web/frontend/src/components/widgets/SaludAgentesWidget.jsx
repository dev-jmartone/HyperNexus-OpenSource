import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { Badge } from '../ui/Badge';
import { Wrench, Radio } from 'lucide-react';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

export function SaludAgentesWidget({ id, title }) {
  const [tab, setTab] = useState('tools');
  const { intervalMs } = useSchedulerInterval();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['salud_agentes'],
    queryFn: () => api.get('/salud/agentes'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-40 bg-slate-800/50 rounded-lg"></div>
      </WidgetWrapper>
    );
  }

  const tools = data?.tools_caidos || { count: 0, items: [] };
  const agente = data?.agente_caido || { count: 0, items: [] };
  const items = tab === 'tools' ? tools.items : agente.items;

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => setTab('tools')}
            className={`p-2.5 rounded-xl border transition-all text-left flex items-center justify-between ${
              tab === 'tools' ? 'bg-rose-500/20 border-rose-500/50' : 'bg-slate-900/60 border-slate-800 hover:bg-slate-800/60'
            }`}
          >
            <div className="text-[10px] font-semibold text-rose-400 flex items-center gap-1">
              <Wrench className="w-3.5 h-3.5" /><span>VMware Tools caído</span>
            </div>
            <span className="text-lg font-black text-slate-100">{tools.count}</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('agente')}
            className={`p-2.5 rounded-xl border transition-all text-left flex items-center justify-between ${
              tab === 'agente' ? 'bg-rose-500/20 border-rose-500/50' : 'bg-slate-900/60 border-slate-800 hover:bg-slate-800/60'
            }`}
          >
            <div className="text-[10px] font-semibold text-rose-400 flex items-center gap-1">
              <Radio className="w-3.5 h-3.5" /><span>Horizon Agent caído</span>
            </div>
            <span className="text-lg font-black text-slate-100">{agente.count}</span>
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-900/60 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
              <tr>
                <th className="py-2 px-3">Nombre VM</th>
                <th className="py-2 px-3">Pool</th>
                <th className="py-2 px-3">Estado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={3} className="py-4 text-center text-slate-500">Sin problemas detectados</td>
                </tr>
              ) : (
                items.slice(0, 8).map((m, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/40">
                    <td className="py-2 px-3 font-mono font-medium text-slate-200">{m.nombre}</td>
                    <td className="py-2 px-3 text-slate-400">{m.pool || '—'}</td>
                    <td className="py-2 px-3">
                      <Badge variant="danger">{tab === 'tools' ? m.tools_status : m.estado_horizon_agente}</Badge>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </WidgetWrapper>
  );
}
