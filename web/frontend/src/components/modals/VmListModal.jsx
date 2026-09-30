import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { X, Search, Monitor, User, ArrowRight, ExternalLink } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { getTeamsChatUrl, getVmCenterUrl } from '../../utils/navigation';

export function VmListModal({ isOpen, onClose, title, filterType, filterValue, onNavigateInventario }) {
  if (!isOpen) return null;

  const [search, setSearch] = useState('');

  const { data: maquinas, isLoading } = useQuery({
    queryKey: ['vm_list_modal', filterType, filterValue],
    queryFn: async () => {
      const params = { simple: '1' };
      if (filterType === 'estado_horizon') params.estado_horizon = filterValue;
      if (filterType === 'estado_vcenter') params.estado_vcenter = filterValue;
      if (filterType === 'tipo') params.tipo = filterValue;
      if (filterType === 'huerfanas') {
        const res = await api.get('/huerfanas');
        return res.items || [];
      }
      const res = await api.get('/maquinas', { params: { per_page: 500, ...params } });
      return res.items || (Array.isArray(res) ? res : []);
    },
    enabled: isOpen,
  });

  const filteredItems = (maquinas || []).filter(m => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      (m.nombre || '').toLowerCase().includes(q) ||
      (m.usuario_asignado || '').toLowerCase().includes(q) ||
      (m.ip || '').toLowerCase().includes(q) ||
      (m.pool || '').toLowerCase().includes(q)
    );
  });

  const getStatusBadge = (m) => {
    const st = (m.estado_horizon || m.estado || '').toUpperCase();
    if (st === 'CONNECTED') return <Badge variant="success">CONECTADA</Badge>;
    if (st === 'AVAILABLE') return <Badge variant="info">DISPONIBLE</Badge>;
    if (st === 'DISCONNECTED') return <Badge variant="warning">DESCONECTADA</Badge>;
    if (st.includes('ERROR') || st.includes('UNREACHABLE')) return <Badge variant="danger">{st}</Badge>;
    return <Badge variant="slate">{st || '—'}</Badge>;
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-4 px-6 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Monitor className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-100">{title || 'Detalle de Máquinas Virtuales'}</h2>
              <p className="text-xs text-slate-400">
                Mostrando {filteredItems.length} máquinas asociadas a esta categoría
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            {onNavigateInventario && (
              <Button 
                variant="secondary" 
                size="sm" 
                onClick={() => { onClose(); onNavigateInventario(filterType, filterValue); }}
                className="text-xs"
              >
                <span>Ver en Inventario Completo</span>
                <ArrowRight className="w-3.5 h-3.5 ml-1 inline" />
              </Button>
            )}

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Search bar */}
        <div className="p-4 bg-slate-900/60 border-b border-slate-800/80 flex items-center space-x-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar por nombre, usuario, IP o pool en esta lista..."
              className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-4 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        {/* Table content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {isLoading ? (
            <div className="py-20 text-center text-slate-400 animate-pulse">Cargando detalle de máquinas...</div>
          ) : filteredItems.length === 0 ? (
            <div className="py-16 text-center text-slate-500">No se encontraron máquinas con este filtro.</div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-800">
              <table className="w-full text-left text-xs text-slate-300 border-collapse">
                <thead className="bg-slate-950/80 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                  <tr>
                    <th className="py-3 px-4">Nombre VM</th>
                    <th className="py-3 px-4">Tipo / Origen</th>
                    <th className="py-3 px-4">Usuario Asignado</th>
                    <th className="py-3 px-4">IP / Host</th>
                    <th className="py-3 px-4">Pool</th>
                    <th className="py-3 px-4">Estado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 bg-slate-900/30">
                  {filteredItems.map((m) => (
                    <tr key={m.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-2.5 px-4 font-bold text-slate-100 whitespace-nowrap">
                        <a
                          href={getVmCenterUrl(m)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-indigo-400 hover:underline flex items-center group"
                          title="Abrir VM en vCenter / Horizon Web UI"
                        >
                          <Monitor className="w-3.5 h-3.5 inline mr-1.5 text-indigo-400 group-hover:scale-110 transition-transform" />
                          <span>{m.nombre}</span>
                          <ExternalLink className="w-3 h-3 ml-1 text-slate-500 group-hover:text-indigo-400 inline" />
                        </a>
                      </td>
                      <td className="py-2.5 px-4 font-mono whitespace-nowrap text-slate-300">
                        <span className="px-2 py-0.5 rounded bg-slate-800 text-[11px] font-semibold text-indigo-300 mr-1">
                          {m.tipo}
                        </span>
                        <span className="uppercase text-[11px] text-slate-400">{m.origen}</span>
                      </td>
                      <td className="py-2.5 px-4 text-slate-200 whitespace-nowrap">
                        {getTeamsChatUrl(m.usuario_asignado) ? (
                          <a
                            href={getTeamsChatUrl(m.usuario_asignado)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:text-indigo-400 hover:underline flex items-center space-x-1 group"
                            title="Iniciar Chat en Microsoft Teams"
                          >
                            <User className="w-3 h-3 text-indigo-400" />
                            <span>{m.usuario_asignado}</span>
                            <span className="text-[10px] px-1 py-0.2 rounded bg-indigo-500/20 text-indigo-300 group-hover:bg-indigo-500 group-hover:text-white transition-colors">
                              💬 Teams
                            </span>
                          </a>
                        ) : (
                          <span className="text-slate-500 italic">{m.usuario_asignado || 'Sin usuario'}</span>
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-slate-400 whitespace-nowrap">
                        {m.ip || m.ip_principal || '—'}
                      </td>
                      <td className="py-2.5 px-4 font-medium text-slate-300 whitespace-nowrap">
                        {m.pool || '—'}
                      </td>
                      <td className="py-2.5 px-4 whitespace-nowrap">
                        {getStatusBadge(m)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-3 px-6 bg-slate-950/50 border-t border-slate-800 flex justify-end">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cerrar
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
