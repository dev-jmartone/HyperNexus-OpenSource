import React from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { Badge } from '../ui/Badge';
import { Gauge } from 'lucide-react';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

// Ocupacion OBSERVADA de pools VDI (cuantas VMs ya existentes en el pool estan libres
// ahora), no la politica de auto-provisioning de Horizon (min/max spare desktops) --
// ese dato no lo expone la API que este proyecto consume hoy.
export function PoolsCapacidadWidget({ id, title }) {
  const { intervalMs } = useSchedulerInterval();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['pools_capacidad'],
    queryFn: () => api.get('/pools/capacidad'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-40 bg-slate-800/50 rounded-lg"></div>
      </WidgetWrapper>
    );
  }

  const items = (data?.items || []).filter((p) => p.riesgo !== 'normal').slice(0, 8);

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="space-y-3">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Pools sin escritorios disponibles u ocupación &gt;90%</span>
          <div className="flex items-center gap-1.5">
            {data?.criticos > 0 && <Badge variant="danger">{data.criticos} críticos</Badge>}
            {data?.altos > 0 && <Badge variant="warning">{data.altos} altos</Badge>}
            {(!data?.criticos && !data?.altos) && <Badge variant="success">Todo OK</Badge>}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-900/60 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
              <tr>
                <th className="py-2 px-3">Pool</th>
                <th className="py-2 px-3">Disponibles</th>
                <th className="py-2 px-3">Ocupación</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={3} className="py-4 text-center text-slate-500">Ningún pool en riesgo de capacidad</td>
                </tr>
              ) : (
                items.map((p, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/40">
                    <td className="py-2 px-3 font-medium text-slate-200 flex items-center">
                      <Gauge className={`w-3.5 h-3.5 mr-1.5 ${p.riesgo === 'critico' ? 'text-rose-400' : 'text-amber-400'}`} />
                      {p.pool}
                    </td>
                    <td className="py-2 px-3 font-mono">{p.disponibles} / {p.total}</td>
                    <td className="py-2 px-3">
                      <Badge variant={p.riesgo === 'critico' ? 'danger' : 'warning'}>{p.pct_ocupado}%</Badge>
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
