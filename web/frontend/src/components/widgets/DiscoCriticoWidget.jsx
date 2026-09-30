import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { HardDrive, X, Monitor } from 'lucide-react';
import { getTeamsChatUrl } from '../../utils/navigation';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

function barColor(pct) {
  if (pct >= 90) return 'bg-rose-500';
  if (pct >= 80) return 'bg-amber-500';
  return 'bg-indigo-500';
}

function pctBadgeVariant(pct) {
  if (pct >= 90) return 'danger';
  if (pct >= 80) return 'warning';
  return 'info';
}

function DiscoBar({ pct }) {
  return (
    <div className="flex items-center space-x-2 min-w-[100px]">
      <div className="flex-1 bg-slate-900 h-1.5 rounded-full overflow-hidden border border-slate-800">
        <div className={`h-full rounded-full ${barColor(pct)}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="text-[11px] font-mono font-bold text-slate-300 w-9 text-right">{pct}%</span>
    </div>
  );
}

function DiscoCriticoModal({ items, onClose }) {
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        <div className="p-4 px-6 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400">
              <HardDrive className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-100">VDI/VM en riesgo de espacio (80-100% usado)</h2>
              <p className="text-xs text-slate-400">{items.length} máquinas con dato real de disco en ese rango</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full text-left text-xs text-slate-300 border-collapse">
              <thead className="bg-slate-950/80 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Nombre VM</th>
                  <th className="py-3 px-4">Pool</th>
                  <th className="py-3 px-4">Usuario</th>
                  <th className="py-3 px-4 text-right">Provisionado</th>
                  <th className="py-3 px-4 text-right">Usado</th>
                  <th className="py-3 px-4 text-right">Libre</th>
                  <th className="py-3 px-4">% Uso</th>
                  <th className="py-3 px-4 text-right">Writable Volumes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 bg-slate-900/30">
                {items.map((m) => (
                  <tr key={m.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-2.5 px-4 font-bold text-slate-100 whitespace-nowrap">
                      <Monitor className="w-3.5 h-3.5 inline mr-1.5 text-indigo-400" />
                      {m.nombre}
                    </td>
                    <td className="py-2.5 px-4 text-slate-400 whitespace-nowrap">{m.pool || '—'}</td>
                    <td className="py-2.5 px-4 text-slate-300 whitespace-nowrap">
                      {getTeamsChatUrl(m.usuario_asignado) ? (
                        <a
                          href={getTeamsChatUrl(m.usuario_asignado)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-indigo-400 hover:underline"
                        >
                          {m.usuario_asignado}
                        </a>
                      ) : (
                        <span className="text-slate-500 italic">{m.usuario_asignado || 'Sin usuario'}</span>
                      )}
                    </td>
                    <td className="py-2.5 px-4 text-right font-mono text-slate-300 whitespace-nowrap">{m.disk_provisioned_gb} GB</td>
                    <td className="py-2.5 px-4 text-right font-mono text-slate-300 whitespace-nowrap">{m.disk_used_gb} GB</td>
                    <td className="py-2.5 px-4 text-right font-mono text-slate-400 whitespace-nowrap">{m.disk_free_gb} GB</td>
                    <td className="py-2.5 px-4 min-w-[130px]">
                      <DiscoBar pct={m.pct_usado} />
                    </td>
                    <td className="py-2.5 px-4 text-right whitespace-nowrap">
                      {m.writables_cantidad > 0 ? (
                        <span
                          className={`font-mono text-xs px-2 py-0.5 rounded ${
                            m.writables_cantidad > 1
                              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                              : 'text-slate-400'
                          }`}
                          title={m.writables_cantidad > 1 ? 'Más de un Writable Volume acumulado -- candidato a revisar/limpiar' : ''}
                        >
                          {m.writables_cantidad} ({m.writables_gb} GB)
                        </span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="p-3 px-6 bg-slate-950/50 border-t border-slate-800 flex justify-end">
          <Button variant="secondary" size="sm" onClick={onClose}>Cerrar</Button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export function DiscoCriticoWidget({ id, title }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { intervalMs } = useSchedulerInterval();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['disco_criticos'],
    queryFn: () => api.get('/disco/criticos'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-40 bg-slate-800/50 rounded-lg"></div>
      </WidgetWrapper>
    );
  }

  const items = data?.items || [];
  const top = items.slice(0, 6);
  const criticas = data?.criticas_90_100 || 0;
  const advertencia = data?.advertencia_80_90 || 0;

  return (
    <>
      <WidgetWrapper id={id} title={title} onRefresh={refetch}>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>Disco usado entre 80% y 100% -- alerta temprana antes de quedarse sin espacio</span>
            <button
              onClick={() => setIsModalOpen(true)}
              className="cursor-pointer hover:scale-105 transition-transform flex items-center space-x-1"
            >
              {criticas > 0 && <Badge variant="danger">{criticas} ≥90%</Badge>}
              {advertencia > 0 && <Badge variant="warning">{advertencia} 80-90%</Badge>}
              {criticas === 0 && advertencia === 0 && <Badge variant="success">0 en riesgo</Badge>}
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/60 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-2 px-3">Nombre VM</th>
                  <th className="py-2 px-3">Pool</th>
                  <th className="py-2 px-3">% Uso</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {top.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-4 text-center text-slate-500">
                      Ninguna VM con dato real de disco en 80-100% ahora mismo
                    </td>
                  </tr>
                ) : (
                  top.map((m) => (
                    <tr key={m.id} className="hover:bg-slate-800/40 cursor-pointer" onClick={() => setIsModalOpen(true)}>
                      <td className="py-2 px-3 font-mono font-medium text-slate-100">{m.nombre}</td>
                      <td className="py-2 px-3 text-slate-400">{m.pool || '—'}</td>
                      <td className="py-2 px-3">
                        <DiscoBar pct={m.pct_usado} />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {items.length > top.length && (
            <button
              onClick={() => setIsModalOpen(true)}
              className="text-[11px] text-indigo-400 hover:text-indigo-300 hover:underline"
            >
              Ver las {items.length} máquinas en riesgo →
            </button>
          )}
        </div>
      </WidgetWrapper>

      {isModalOpen && <DiscoCriticoModal items={items} onClose={() => setIsModalOpen(false)} />}
    </>
  );
}
