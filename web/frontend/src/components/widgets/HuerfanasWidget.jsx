import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { WidgetWrapper } from './WidgetWrapper';
import { Badge } from '../ui/Badge';
import { UserX } from 'lucide-react';
import { VmListModal } from '../modals/VmListModal';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

export function HuerfanasWidget({ id, title, onNavigateInventario }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { intervalMs } = useSchedulerInterval();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['huerfanas'],
    queryFn: () => api.get('/huerfanas'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse h-40 bg-slate-800/50 rounded-lg"></div>
      </WidgetWrapper>
    );
  }

  const items = (data?.items || []).slice(0, 5);

  return (
    <>
      <WidgetWrapper id={id} title={title} onRefresh={refetch}>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>Escritorios Available sin usuario asignado</span>
            <button 
              onClick={() => setIsModalOpen(true)} 
              className="cursor-pointer hover:scale-105 transition-transform"
            >
              <Badge variant="warning">{data?.count || 0} sin asignar ➔</Badge>
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/60 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-2 px-3">Nombre VM</th>
                  <th className="py-2 px-3">Pool</th>
                  <th className="py-2 px-3">Empresa</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-4 text-center text-slate-500">No hay máquinas huérfanas</td>
                  </tr>
                ) : (
                  items.map((m, idx) => (
                    <tr key={idx} className="hover:bg-slate-800/40 cursor-pointer" onClick={() => setIsModalOpen(true)}>
                      <td className="py-2 px-3 font-mono font-medium text-amber-300 flex items-center">
                        <UserX className="w-3.5 h-3.5 mr-1.5 text-amber-400" />
                        {m.nombre}
                      </td>
                      <td className="py-2 px-3 text-slate-400">{m.pool || '—'}</td>
                      <td className="py-2 px-3 text-slate-400">{m.empresa || '—'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </WidgetWrapper>

      {isModalOpen && (
        <VmListModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          title="Máquinas Huérfanas (Sin Usuario)"
          filterType="huerfanas"
          filterValue="1"
          onNavigateInventario={onNavigateInventario}
        />
      )}
    </>
  );
}

