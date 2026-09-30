import React from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { Badge } from '../ui/Badge';
import { UserX } from 'lucide-react';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

// VDI Persistente (Dedicated) asignada a una cuenta ya deshabilitada en AD -- escritorio
// que nadie mas puede usar mientras siga "reservado" para esa cuenta.
export function VdisRetenidasWidget({ id, title }) {
  const { intervalMs } = useSchedulerInterval();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['vdis_retenidas'],
    queryFn: () => api.get('/directorio/vdis_retenidas'),
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
          <span>VDI Persistente reservada para cuenta AD deshabilitada</span>
          <Badge variant="warning">{data?.count || 0}</Badge>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-900/60 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
              <tr>
                <th className="py-2 px-3">VM</th>
                <th className="py-2 px-3">Pool</th>
                <th className="py-2 px-3">Usuario (inactivo en AD)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={3} className="py-4 text-center text-slate-500">Ninguna VDI retenida por cuenta deshabilitada</td>
                </tr>
              ) : (
                items.map((v, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/40">
                    <td className="py-2 px-3 font-mono font-medium text-slate-200">{v.nombre_vm}</td>
                    <td className="py-2 px-3 text-slate-400">{v.pool || '—'}</td>
                    <td className="py-2 px-3 flex items-center">
                      <UserX className="w-3.5 h-3.5 mr-1.5 text-amber-400" />
                      {v.usuario_nombre_completo || v.usuario_asignado}
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
