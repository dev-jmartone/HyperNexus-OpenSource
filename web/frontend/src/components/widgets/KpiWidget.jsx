import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { Monitor, Wifi, AlertTriangle, CheckCircle } from 'lucide-react';
import { WidgetWrapper } from './WidgetWrapper';
import { VmListModal } from '../modals/VmListModal';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

export function KpiWidget({ id, title, onNavigateInventario }) {
  const [modalConfig, setModalConfig] = useState(null);
  const { intervalMs } = useSchedulerInterval();

  const { data: kpis, isLoading, refetch } = useQuery({
    queryKey: ['kpis'],
    queryFn: () => api.get('/kpis'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 bg-slate-800/50 rounded-lg"></div>
          ))}
        </div>
      </WidgetWrapper>
    );
  }

  const items = [
    {
      label: 'Total VDI',
      val: kpis?.total || 0,
      sub: `${kpis?.vdi || 0} VDI / ${kpis?.vm || 0} VM`,
      icon: Monitor,
      color: 'text-indigo-400',
      bg: 'bg-indigo-500/10 border-indigo-500/20 hover:border-indigo-500/50',
      filterType: '',
      filterValue: '',
      title: 'Inventario Completo de Máquinas',
    },
    {
      label: 'Conectadas',
      val: kpis?.conectadas || 0,
      sub: 'Usuarios en sesión',
      icon: Wifi,
      color: 'text-emerald-400',
      bg: 'bg-emerald-500/10 border-emerald-500/20 hover:border-emerald-500/50',
      filterType: 'estado_horizon',
      filterValue: 'CONNECTED',
      title: 'Máquinas Conectadas (En Sesión)',
    },
    {
      label: 'Disponibles',
      val: kpis?.disponibles || 0,
      sub: 'Listas para asignar',
      icon: CheckCircle,
      color: 'text-sky-400',
      bg: 'bg-sky-500/10 border-sky-500/20 hover:border-sky-500/50',
      filterType: 'estado_horizon',
      filterValue: 'AVAILABLE',
      title: 'Máquinas Disponibles',
    },
    {
      label: 'Errores / Problem',
      val: kpis?.errores || 0,
      sub: 'Requiere atención',
      icon: AlertTriangle,
      color: 'text-rose-400',
      bg: 'bg-rose-500/10 border-rose-500/20 hover:border-rose-500/50',
      filterType: 'estado_horizon',
      filterValue: 'ERROR',
      title: 'Máquinas con Alerta o Error',
    },
  ];

  return (
    <>
      <WidgetWrapper id={id} title={title} onRefresh={refetch}>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {items.map((item, idx) => {
            const IconComponent = item.icon;
            return (
              <div
                key={idx}
                onClick={() => setModalConfig(item)}
                className={`p-4 rounded-xl border ${item.bg} flex flex-col justify-between transition-all hover:scale-[1.02] cursor-pointer group`}
                title="Hacer click para ver listado detallado"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-400 group-hover:text-slate-200 transition-colors">
                    {item.label}
                  </span>
                  <IconComponent className={`w-5 h-5 ${item.color}`} />
                </div>
                <div className="mt-3">
                  <div className="text-2xl font-bold text-slate-100 tracking-tight">{item.val}</div>
                  <div className="flex items-center justify-between mt-1">
                    <p className="text-[11px] text-slate-400">{item.sub}</p>
                    <span className="text-[10px] text-indigo-400 group-hover:underline font-medium">Ver ➔</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </WidgetWrapper>

      {modalConfig && (
        <VmListModal
          isOpen={Boolean(modalConfig)}
          onClose={() => setModalConfig(null)}
          title={modalConfig.title}
          filterType={modalConfig.filterType}
          filterValue={modalConfig.filterValue}
          onNavigateInventario={onNavigateInventario}
        />
      )}
    </>
  );
}

