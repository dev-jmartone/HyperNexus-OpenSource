import React from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { Badge } from '../ui/Badge';
import { Server, Cpu, Database, HardDrive } from 'lucide-react';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

// Nota real (investigado 2026-09-02): no hay hoy un cruce confiable VM-a-host-ESXi-real
// en los datos (bug de extraccion en core/vcenter_rest.py, requiere prueba en vivo para
// arreglar). Este widget muestra las dos cosas que SI son reales por separado: carga por
// vCenter (servidor de gestion) y estado de conexion de cada host ESXi.
export function WidgetTopESXiHosts({ id, title }) {
  const { intervalMs } = useSchedulerInterval();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['hosts_summary'],
    queryFn: () => api.get('/hosts/summary'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-48 bg-slate-800/50 rounded-xl"></div>
      </WidgetWrapper>
    );
  }

  const porVcenter = data?.por_vcenter || [];
  const hostsEsxi = data?.hosts_esxi || [];
  const caidos = data?.hosts_esxi_caidos || 0;

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="space-y-4">
        {/* Carga por vCenter */}
        <div>
          <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Carga por vCenter</div>
          <div className="space-y-2 max-h-40 overflow-y-auto pr-1">
            {porVcenter.length === 0 ? (
              <div className="py-4 text-center text-xs text-slate-500">Sin datos de vCenter</div>
            ) : (
              porVcenter.map((v, idx) => (
                <div key={idx} className="p-2.5 bg-slate-900/40 border border-slate-800/60 rounded-xl space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-100 font-mono truncate max-w-[160px]">{v.vcenter}</span>
                    <div className="flex items-center space-x-1.5 text-[10px] font-mono">
                      <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">{v.powered_on} On</span>
                      <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">{v.powered_off} Off</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[10px] font-mono text-slate-400">
                    <div className="flex items-center space-x-1"><span className="text-slate-500">VMs:</span><strong className="text-slate-200">{v.total_vms}</strong></div>
                    <div className="flex items-center space-x-1"><Cpu className="w-3 h-3 text-indigo-400" /><strong className="text-slate-200">{v.cpu_vcpus}</strong></div>
                    <div className="flex items-center space-x-1"><Database className="w-3 h-3 text-sky-400" /><strong className="text-slate-200">{v.ram_gb} GB</strong></div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Estado de hosts ESXi reales */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Hosts ESXi</span>
            <Badge variant={caidos > 0 ? 'danger' : 'success'}>{caidos > 0 ? `${caidos} caídos` : 'Todos OK'}</Badge>
          </div>
          <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto pr-1">
            {hostsEsxi.length === 0 ? (
              <div className="py-2 text-center text-xs text-slate-500 w-full">Sin hosts ESXi registrados</div>
            ) : (
              hostsEsxi.map((h, idx) => {
                const ok = h.connection_state.toUpperCase() === 'CONNECTED';
                return (
                  <span
                    key={idx}
                    className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-mono border ${
                      ok ? 'bg-slate-900/40 border-slate-800 text-slate-300' : 'bg-rose-500/10 border-rose-500/40 text-rose-300'
                    }`}
                    title={`${h.host} — ${h.connection_state}`}
                  >
                    <Server className="w-3 h-3" />
                    {h.host.split('.')[0]}
                  </span>
                );
              })
            )}
          </div>
        </div>
      </div>
    </WidgetWrapper>
  );
}
