import React from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { HardDrive, Server, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

function barColor(pct) {
  if (pct >= 90) return 'bg-rose-500';
  if (pct >= 75) return 'bg-amber-500';
  return 'bg-emerald-500';
}

export function WidgetInfraestructura({ id, title }) {
  const { intervalMs } = useSchedulerInterval();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['infraestructura'],
    queryFn: () => api.get('/infraestructura'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-48 bg-slate-800/50 rounded-xl"></div>
      </WidgetWrapper>
    );
  }

  const datastores = data?.datastores || [];
  const hosts = data?.hosts || [];
  const dsCriticos = data?.datastores_criticos || 0;
  const hostsCaidos = data?.hosts_desconectados || 0;

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2">
          <div className={`p-2.5 rounded-xl border flex items-center justify-between ${
            dsCriticos > 0 ? 'bg-rose-500/10 border-rose-500/30' : 'bg-slate-900/50 border-slate-800/80'
          }`}>
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
              <HardDrive className="w-3.5 h-3.5 text-indigo-400" />
              <span>Datastores &gt;90%</span>
            </div>
            <strong className={dsCriticos > 0 ? 'text-rose-400' : 'text-emerald-400'}>{dsCriticos}</strong>
          </div>
          <div className={`p-2.5 rounded-xl border flex items-center justify-between ${
            hostsCaidos > 0 ? 'bg-rose-500/10 border-rose-500/30' : 'bg-slate-900/50 border-slate-800/80'
          }`}>
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
              <Server className="w-3.5 h-3.5 text-indigo-400" />
              <span>Hosts caídos</span>
            </div>
            <strong className={hostsCaidos > 0 ? 'text-rose-400' : 'text-emerald-400'}>{hostsCaidos}</strong>
          </div>
        </div>

        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">Datastores</div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
            {datastores.length === 0 ? (
              <div className="py-4 text-center text-[11px] text-slate-500">Sin datos de datastores todavía.</div>
            ) : (
              datastores.map((d) => (
                <div key={d.id} className="p-2 bg-slate-900/40 border border-slate-800/60 rounded-lg">
                  <div className="flex items-center justify-between text-[11px] mb-1">
                    <span className="font-mono text-slate-200 truncate">{d.nombre}</span>
                    <span className="text-slate-400 font-mono">{d.espacio_usado_pct ?? '—'}%</span>
                  </div>
                  <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${barColor(d.espacio_usado_pct || 0)}`}
                      style={{ width: `${Math.min(d.espacio_usado_pct || 0, 100)}%` }}
                    />
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">Hosts ESXi</div>
          <div className="space-y-1 max-h-32 overflow-y-auto pr-1">
            {hosts.length === 0 ? (
              <div className="py-4 text-center text-[11px] text-slate-500">Sin datos de hosts todavía.</div>
            ) : (
              hosts.map((h) => {
                const ok = h.connection_state === 'CONNECTED';
                return (
                  <div key={h.id} className="p-2 bg-slate-900/40 border border-slate-800/60 rounded-lg flex items-center justify-between text-[11px]">
                    <span className="font-mono text-slate-200 truncate">{h.nombre}</span>
                    <span className={`flex items-center gap-1 font-semibold ${ok ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {ok ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                      {h.connection_state || '—'}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </WidgetWrapper>
  );
}
