import React from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { Badge } from '../ui/Badge';
import { Cpu } from 'lucide-react';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

const LABELS = {
  vcls: 'vCLS (vSphere Cluster Services)',
  cp_parent: 'cp-parent (Instant Clone)',
  cp_replica: 'cp-replica (Instant Clone)',
  cp_template: 'cp-template (Instant Clone)',
  otro: 'Otro',
};

const ORDEN = ['vcls', 'cp_parent', 'cp_replica', 'cp_template', 'otro'];

export function InfraInternaWidget({ id, title }) {
  const { intervalMs } = useSchedulerInterval();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['infraestructura_consumo_interno'],
    queryFn: () => api.get('/infraestructura/consumo_interno'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-40 bg-slate-800/50 rounded-lg"></div>
      </WidgetWrapper>
    );
  }

  const total = data?.total || { count: 0, encendidas: 0, cpu_vcpus: 0, ram_gb: 0, disco_gb: 0 };
  const porCategoria = data?.por_categoria || {};
  const filas = ORDEN.filter((k) => porCategoria[k]).map((k) => ({ key: k, ...porCategoria[k] }));

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="space-y-3">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Plomería de plataforma, fuera de los KPIs de negocio</span>
          <Badge variant="info">{total.count} VMs · {total.disco_gb.toLocaleString('es-AR')} GB disco</Badge>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-900/60 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
              <tr>
                <th className="py-2 px-3">Categoría</th>
                <th className="py-2 px-3 text-right">VMs</th>
                <th className="py-2 px-3 text-right">Encendidas</th>
                <th className="py-2 px-3 text-right">vCPU</th>
                <th className="py-2 px-3 text-right">RAM GB</th>
                <th className="py-2 px-3 text-right">Disco GB</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {filas.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-4 text-center text-slate-500">Sin VMs de infraestructura interna</td>
                </tr>
              ) : (
                filas.map((f) => (
                  <tr key={f.key} className="hover:bg-slate-800/40">
                    <td className="py-2 px-3 font-medium text-slate-200 flex items-center">
                      <Cpu className="w-3.5 h-3.5 mr-1.5 text-indigo-400" />
                      {LABELS[f.key] || f.key}
                    </td>
                    <td className="py-2 px-3 text-right font-mono">{f.count}</td>
                    <td className="py-2 px-3 text-right font-mono">{f.encendidas}</td>
                    <td className="py-2 px-3 text-right font-mono">{f.cpu_vcpus}</td>
                    <td className="py-2 px-3 text-right font-mono">{f.ram_gb}</td>
                    <td className="py-2 px-3 text-right font-mono">{f.disco_gb.toLocaleString('es-AR')}</td>
                  </tr>
                ))
              )}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-700 font-semibold text-slate-200">
                <td className="py-2 px-3">Total</td>
                <td className="py-2 px-3 text-right font-mono">{total.count}</td>
                <td className="py-2 px-3 text-right font-mono">{total.encendidas}</td>
                <td className="py-2 px-3 text-right font-mono">{total.cpu_vcpus}</td>
                <td className="py-2 px-3 text-right font-mono">{total.ram_gb}</td>
                <td className="py-2 px-3 text-right font-mono">{total.disco_gb.toLocaleString('es-AR')}</td>
              </tr>
            </tfoot>
          </table>
        </div>

        <p className="text-[11px] text-slate-500">
          cp-replica/cp-template quedan siempre apagadas (no consumen CPU/RAM, sólo ocupan datastore) &mdash; su Disco GB es costo real de almacenamiento acumulado, candidato a limpieza en vCenter.
        </p>
      </div>
    </WidgetWrapper>
  );
}
