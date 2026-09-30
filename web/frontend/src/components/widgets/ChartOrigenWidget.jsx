import React from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, Legend } from 'recharts';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

const COLORS = ['#6366f1', '#10b981', '#f43f5e', '#38bdf8', '#a78bfa', '#f59e0b'];

export function ChartOrigenWidget({ id, title }) {
  const { intervalMs } = useSchedulerInterval();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['dist_origen'],
    queryFn: () => api.get('/distribucion/origen'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-52 bg-slate-800/50 rounded-lg"></div>
      </WidgetWrapper>
    );
  }

  const rawLabels = data?.labels || [];
  const rawData = data?.data || [];
  const rawSeg = data?.segmentado || [];
  const total = rawData.reduce((acc, curr) => acc + curr, 0);

  const chartData = rawLabels.map((label, idx) => ({
    name: label.toUpperCase(),
    value: rawData[idx] || 0,
    pct: total > 0 ? (((rawData[idx] || 0) / total) * 100).toFixed(1) : '0',
    seg: rawSeg[idx] || { vdi: 0, vm_estatica: 0, master: 0, plantilla: 0, infra_interna: 0 },
  }));

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const item = payload[0].payload;
      return (
        <div className="bg-slate-900 border border-slate-700 p-2.5 rounded-lg shadow-xl text-xs space-y-1">
          <div className="font-semibold text-slate-100">{item.name}</div>
          <div className="text-indigo-400 font-mono font-bold">
            {item.value} VMs ({item.pct}%)
          </div>
          <div className="text-slate-400 font-mono text-[11px] pt-1 border-t border-slate-800">
            <div>🖥️ {item.seg.vdi} VDI (en pool)</div>
            <div>📦 {item.seg.vm_estatica} VM estática</div>
            {item.seg.master > 0 && <div>🏆 {item.seg.master} Master</div>}
            {item.seg.plantilla > 0 && <div>📄 {item.seg.plantilla} Plantilla</div>}
            {item.seg.infra_interna > 0 && <div>⚙️ {item.seg.infra_interna} Infra Interna</div>}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="h-56 w-full relative flex items-center justify-center">
        {/* Center Donut Label */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none pb-6">
          <span className="text-xl font-extrabold text-slate-100 font-mono">{total}</span>
          <span className="text-[10px] text-slate-400 font-medium uppercase">Total VMs</span>
        </div>

        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              innerRadius={58}
              outerRadius={82}
              paddingAngle={5}
              dataKey="value"
              stroke="#0f172a"
              strokeWidth={2}
            >
              {chartData.map((_, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            <Legend 
              formatter={(value, entry) => {
                const item = chartData.find(d => d.name === value);
                return (
                  <span className="text-xs text-slate-300 font-medium">
                    {value} <span className="text-slate-400 text-[11px]">({item?.value || 0})</span>
                  </span>
                );
              }}
              wrapperStyle={{ paddingTop: '8px' }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Segmentacion VDI vs VM estatica visible sin hover -- el total solo no dice
          cuantas son escritorios VDI reales vs equipos estaticos (RPA, servidores). */}
      <div className="mt-1 space-y-1.5 text-[11px]">
        {chartData.map((d, idx) => (
          <div key={idx} className="flex items-center justify-between px-2 py-1 rounded-lg bg-slate-900/50 border border-slate-800/60">
            <span className="font-semibold text-slate-300">{d.name}</span>
            <span className="font-mono text-slate-400">
              <span className="text-indigo-400">{d.seg.vdi} VDI</span>
              {' · '}
              <span className="text-amber-400">{d.seg.vm_estatica} VM</span>
              {d.seg.master > 0 && <span className="text-purple-400">{' · '}{d.seg.master} Master</span>}
              {d.seg.infra_interna > 0 && <span className="text-slate-500">{' · '}{d.seg.infra_interna} Infra</span>}
            </span>
          </div>
        ))}
      </div>
    </WidgetWrapper>
  );
}
