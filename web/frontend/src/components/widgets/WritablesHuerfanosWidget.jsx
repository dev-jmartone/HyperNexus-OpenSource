import React from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { Badge } from '../ui/Badge';
import { HardDrive } from 'lucide-react';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

export function WritablesHuerfanosWidget({ id, title }) {
  const { intervalMs } = useSchedulerInterval();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['appvolumes_writables_huerfanos'],
    queryFn: () => api.get('/appvolumes/writables_huerfanos'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-40 bg-slate-800/50 rounded-lg"></div>
      </WidgetWrapper>
    );
  }

  const items = (data?.items || []).slice(0, 8);

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="space-y-3">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Write Volumes sin montar / marcados orphaned</span>
          <Badge variant="warning">{data?.count || 0} · {data?.total_gb_desperdiciado || 0} GB</Badge>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-900/60 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
              <tr>
                <th className="py-2 px-3">Usuario</th>
                <th className="py-2 px-3">Estado</th>
                <th className="py-2 px-3">Tamaño</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={3} className="py-4 text-center text-slate-500">Sin Write Volumes huérfanos</td>
                </tr>
              ) : (
                items.map((w, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/40">
                    <td className="py-2 px-3 font-medium text-slate-200 flex items-center">
                      <HardDrive className="w-3.5 h-3.5 mr-1.5 text-amber-400" />
                      {w.owner_display_name || w.entity_name || '—'}
                    </td>
                    <td className="py-2 px-3">
                      <Badge variant={w.estado === 'orphaned' ? 'danger' : 'warning'}>{w.estado || 'sin montar'}</Badge>
                    </td>
                    <td className="py-2 px-3 font-mono text-slate-400">{w.size_gb ?? '—'} GB</td>
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
