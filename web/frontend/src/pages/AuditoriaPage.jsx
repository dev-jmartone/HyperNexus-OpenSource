import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ShieldCheck, Clock, User, ChevronLeft, ChevronRight, RefreshCw, Filter } from 'lucide-react';

export function AuditoriaPage() {
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [accionFilter, setAccionFilter] = useState('');
  const [userFilter, setUserFilter] = useState('');

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['auditoria', page, perPage],
    queryFn: () => api.get('/auditoria', { params: { page, per_page: perPage } }),
  });

  const getActionBadge = (accion) => {
    const a = (accion || '').toLowerCase();
    if (a.includes('login') && !a.includes('fallido')) return <Badge variant="success">{accion}</Badge>;
    if (a.includes('fallido') || a.includes('error') || a.includes('eliminar')) return <Badge variant="danger">{accion}</Badge>;
    if (a.includes('crear') || a.includes('editar')) return <Badge variant="warning">{accion}</Badge>;
    return <Badge variant="info">{accion}</Badge>;
  };

  const filteredItems = (data?.items || []).filter(item => {
    if (accionFilter && item.accion !== accionFilter) return false;
    if (userFilter && !(item.username || '').toLowerCase().includes(userFilter.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <Card 
        title="Registro de Auditoría de Sistema (Audit Logs)" 
        subtitle="Eventos de seguridad y trazabilidad de acciones"
        action={
          <div className="flex items-center space-x-2">
            <select
              value={perPage}
              onChange={(e) => { setPerPage(parseInt(e.target.value)); setPage(1); }}
              className="bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none"
            >
              {[10, 20, 30, 40, 50, 100, 200, 300, 400, 500].map((n) => (
                <option key={n} value={n}>{n} registros por pág.</option>
              ))}
            </select>
            <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => refetch()}>
              Actualizar
            </Button>
          </div>
        }
      >
        {/* Quick Filter Bar */}
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="flex items-center space-x-2">
            <Filter className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-xs font-semibold text-slate-300 uppercase">Filtros:</span>
          </div>

          <input
            type="text"
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            placeholder="Filtrar por usuario..."
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 w-44"
          />

          {(userFilter || accionFilter) && (
            <button 
              onClick={() => { setUserFilter(''); setAccionFilter(''); }}
              className="text-xs text-rose-400 hover:underline"
            >
              ✕ Limpiar filtros
            </button>
          )}
        </div>

        {isLoading ? (
          <div className="py-20 text-center text-slate-400 animate-pulse">Cargando registros de auditoría...</div>
        ) : filteredItems.length === 0 ? (
          <div className="py-12 text-center text-slate-500">No hay registros de auditoría en la base de datos.</div>
        ) : (
          <div>
            <div className="overflow-x-auto rounded-xl border border-slate-800/80">
              <table className="w-full text-left text-xs text-slate-300 border-collapse">
                <thead className="bg-slate-900/90 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                  <tr>
                    <th className="py-3.5 px-4 min-w-[160px]">Fecha / Hora</th>
                    <th className="py-3.5 px-4 min-w-[140px]">Usuario</th>
                    <th className="py-3.5 px-4 min-w-[130px]">Acción</th>
                    <th className="py-3.5 px-4 min-w-[150px]">Recurso Afectado</th>
                    <th className="py-3.5 px-4 min-w-[120px]">IP Origen</th>
                    <th className="py-3.5 px-4">Detalle / Evento</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredItems.map((l) => (
                    <tr key={l.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-3 px-4 font-mono text-slate-300 whitespace-nowrap">
                        <Clock className="w-3.5 h-3.5 inline mr-2 text-indigo-400 shrink-0" />
                        {l.timestamp}
                      </td>
                      <td className="py-3 px-4 font-bold text-slate-100 whitespace-nowrap">
                        <User className="w-3.5 h-3.5 inline mr-1.5 text-slate-400 shrink-0" />
                        {l.username || '—'}
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        {getActionBadge(l.accion)}
                      </td>
                      <td className="py-3 px-4 font-mono font-medium text-indigo-300 whitespace-nowrap">
                        {l.recurso || '—'}
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-400 whitespace-nowrap">
                        <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-[11px]">
                          {l.ip_origen || '—'}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-slate-300" title={l.detalle}>
                        {l.detalle || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>


            {/* Pagination controls */}
            <div className="mt-4 pt-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
              <div>
                Página <span className="font-semibold text-slate-200">{data?.page || 1}</span> de{' '}
                <span className="font-semibold text-slate-200">{Math.ceil((data?.total || 0) / perPage) || 1}</span> ({data?.total || 0} total)
              </div>
              <div className="flex items-center space-x-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  icon={ChevronLeft}
                >
                  Anterior
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page >= Math.ceil((data?.total || 0) / perPage)}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Siguiente
                  <ChevronRight className="w-3.5 h-3.5 ml-1" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
