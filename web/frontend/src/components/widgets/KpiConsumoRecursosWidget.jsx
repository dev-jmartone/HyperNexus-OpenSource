import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { Cpu, Database, HardDrive } from 'lucide-react';
import { WidgetWrapper } from './WidgetWrapper';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

// Fusión de KpiCpuConsumoWidget + KpiRamConsumoWidget + KpiDiscoConsumoWidget (2026-09-07,
// auditoría de dashboard) -- los 3 leían el mismo endpoint /api/kpis y ocupaban 3 columnas
// de grilla para la misma idea ("% VMs encendidas sobre lo asignado"), solo cambiaba el
// recurso. Un widget con tabs libera 2 espacios reales sin perder ningún dato.
const METRICS = {
  cpu: {
    label: 'CPU',
    icon: Cpu,
    titulo: '% VMs Encendidas (vCPUs asignadas)',
    nota: 'vCPUs asignadas a VMs encendidas / total asignado — no es uso real de hardware',
    tooltip: 'No mide uso real de CPU del hypervisor (MHz), solo cuanto de lo asignado esta prendido',
    tieneUnidad: false,
    campoData: 'cpu',
    campoDesglose: 'cpu_vcpus',
  },
  ram: {
    label: 'RAM',
    icon: Database,
    titulo: '% VMs Encendidas (RAM asignada)',
    nota: 'RAM asignada a VMs encendidas / total asignado — no es uso real de hardware',
    tooltip: 'No mide uso real de RAM del hypervisor, solo cuanto de lo asignado esta prendido',
    tieneUnidad: true,
    campoData: 'ram',
    campoDesglose: 'ram_gb',
  },
  disco: {
    label: 'Disco',
    icon: HardDrive,
    titulo: '% VMs Encendidas (Disco asignado)',
    nota: 'Disco asignado a VMs encendidas / total asignado — no es uso real de storage',
    tooltip: 'Disco provisionado, no uso real en el datastore',
    tieneUnidad: true,
    campoData: 'disco',
    campoDesglose: 'disco_gb',
  },
};

export function KpiConsumoRecursosWidget({ id, title }) {
  const [metric, setMetric] = useState('cpu');
  const [unit, setUnit] = useState('GB');
  const { intervalMs } = useSchedulerInterval();

  const { data, refetch } = useQuery({
    queryKey: ['kpis'],
    queryFn: () => api.get('/kpis'),
    refetchInterval: intervalMs,
  });

  const cfg = METRICS[metric];
  const Icon = cfg.icon;
  const metricData = data?.[cfg.campoData] || { active_vcpus: 0, active_gb: 0, total_vcpus: 0, total_gb: 0, pct: 0 };
  const desglose = data?.desglose_servidores || [];

  const activoBase = metric === 'cpu' ? metricData.active_vcpus : metricData.active_gb;
  const displayActive = cfg.tieneUnidad && unit === 'TB'
    ? (Number(activoBase || 0) / 1024).toFixed(2)
    : Number(activoBase || 0).toFixed(metric === 'cpu' ? 0 : 2);
  const sufijo = metric === 'cpu' ? 'vCPUs' : unit;

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 rounded-lg p-0.5">
          {Object.entries(METRICS).map(([key, m]) => (
            <button
              key={key}
              onClick={() => setMetric(key)}
              className={`px-2 py-1 rounded-md text-[10.5px] font-bold uppercase tracking-wide transition-colors ${
                metric === key ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className="flex items-center space-x-2">
          {cfg.tieneUnidad && (
            <button
              onClick={() => setUnit(unit === 'GB' ? 'TB' : 'GB')}
              className="px-1.5 py-0.5 rounded text-[10px] font-bold font-mono bg-slate-900 border border-slate-700 text-indigo-400 hover:text-white transition-colors"
              title="Cambiar unidad de medida (GB / TB)"
            >
              {unit}
            </button>
          )}
          <div className="p-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
            <Icon className="w-3.5 h-3.5" />
          </div>
        </div>
      </div>
      <p className="text-[10px] text-slate-500 mt-1" title={cfg.tooltip}>
        {cfg.nota}
      </p>

      <div className="mt-3 space-y-2">
        <div className="flex items-baseline justify-between">
          <div className="text-xl font-extrabold text-slate-100 font-mono">
            {displayActive} <span className="text-xs font-normal text-slate-400">{sufijo}</span>
          </div>
          <div className="text-xs font-bold text-indigo-400 font-mono">
            {Number(metricData.pct || 0).toFixed(2)}%
          </div>
        </div>

        <div className="w-full bg-slate-900 h-1.5 rounded-full overflow-hidden border border-slate-800">
          <div
            className="bg-gradient-to-r from-indigo-500 to-indigo-400 h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(metricData.pct, 100)}%` }}
          />
        </div>

        {desglose.length > 0 && (
          <div className="pt-2 border-t border-slate-800/60 space-y-1 text-[11px]">
            {desglose.map((s, idx) => {
              const valorCrudo = s[cfg.campoDesglose] ?? 0;
              const valorMostrado = cfg.tieneUnidad && unit === 'TB'
                ? (Number(valorCrudo) / 1024).toFixed(2)
                : Number(valorCrudo).toFixed(metric === 'cpu' ? 0 : 2);
              return (
                <div key={idx} className="flex items-center justify-between font-mono">
                  <span className="text-slate-400 truncate max-w-[140px]">{s.servidor}</span>
                  <span className="text-slate-200 font-bold">
                    {valorMostrado} {sufijo}{metric === 'cpu' ? ` (${s.vms} VMs)` : ''}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </WidgetWrapper>
  );
}
