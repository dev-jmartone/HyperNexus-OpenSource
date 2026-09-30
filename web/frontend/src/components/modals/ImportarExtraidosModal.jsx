import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { Button } from '../ui/Button';
import { Download, UserCheck, Search, Check, AlertCircle, Monitor } from 'lucide-react';
import { toastError } from '../../utils/alerts';

export function ImportarExtraidosModal({ isOpen, onClose, onImported }) {
  const [search, setSearch] = useState('');
  const [selectedUsers, setSelectedUsers] = useState({});
  const [isImporting, setIsImporting] = useState(false);
  const [statusMsg, setStatusMsg] = useState(null);

  const { data: extraidos, isLoading, refetch } = useQuery({
    queryKey: ['directorio_extraidos', search],
    queryFn: () => api.get('/directorio/extraidos', { params: { q: search } }),
    enabled: isOpen,
  });

  const handleToggleSelect = (username) => {
    setSelectedUsers(prev => ({
      ...prev,
      [username]: !prev[username]
    }));
  };

  const handleSelectAll = (e) => {
    if (e.target.checked && extraidos) {
      const map = {};
      extraidos.forEach(u => {
        if (!u.registrado) map[u.username] = true;
      });
      setSelectedUsers(map);
    } else {
      setSelectedUsers({});
    }
  };

  const handleImportSelected = async () => {
    const toImport = (extraidos || []).filter(u => selectedUsers[u.username]);
    if (toImport.length === 0) {
      toastError('Seleccioná al menos un usuario para importar.');
      return;
    }

    try {
      setIsImporting(true);
      setStatusMsg('Registrando usuarios seleccionados en el directorio...');
      
      const payload = toImport.map(u => ({
        username: u.username,
        nombre_completo: u.nombre_completo,
        empresa: u.empresa,
        maquina_ids: u.vms.map(v => v.id)
      }));

      const res = await api.post('/directorio/importar_extraidos', { usuarios: payload });
      setIsImporting(false);
      setStatusMsg(`¡Completado! ${res.importados} usuarios registrados, ${res.vinculos} vínculos creados.`);
      setSelectedUsers({});
      refetch();
      if (onImported) onImported();
      setTimeout(() => { setStatusMsg(null); onClose(); }, 2000);
    } catch (e) {
      setIsImporting(false);
      setStatusMsg('Error al registrar usuarios extraídos');
    }
  };

  if (!isOpen) return null;

  const noRegistrados = (extraidos || []).filter(u => !u.registrado);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/85 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-3xl glass-panel p-6 rounded-2xl border border-slate-800 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-2">
            <UserCheck className="w-5 h-5 text-indigo-400" />
            <h3 className="text-base font-bold text-slate-100">Importar Usuarios Detectados en Extracciones</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200 text-xl font-bold">×</button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filtrar por usuario, empresa o VM..."
              className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-4 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex items-center space-x-3">
            <label className="flex items-center space-x-2 text-slate-400 cursor-pointer">
              <input
                type="checkbox"
                onChange={handleSelectAll}
                className="w-4 h-4 accent-indigo-600 rounded"
              />
              <span>Seleccionar no registrados ({noRegistrados.length})</span>
            </label>
          </div>
        </div>

        {statusMsg && (
          <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-indigo-300 text-xs font-medium flex items-center">
            {isImporting && <div className="w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mr-2 shrink-0"></div>}
            <span>{statusMsg}</span>
          </div>
        )}

        {isLoading ? (
          <div className="py-16 text-center text-slate-400 animate-pulse">Cargando usuarios detectados en los escaneos...</div>
        ) : (
          <div className="overflow-x-auto max-h-80 overflow-y-auto border border-slate-800 rounded-xl">
            <table className="w-full text-left text-xs text-slate-300 border-collapse">
              <thead className="bg-slate-900 sticky top-0 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800 z-10">
                <tr>
                  <th className="py-2.5 px-3 w-10 text-center">Sel.</th>
                  <th className="py-2.5 px-3">Usuario AD</th>
                  <th className="py-2.5 px-3">Empresa</th>
                  <th className="py-2.5 px-3">VMs & Pools Detectados</th>
                  <th className="py-2.5 px-3 text-center">Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {extraidos?.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-slate-500">No se detectaron usuarios sin registrar en los escaneos.</td>
                  </tr>
                ) : (
                  extraidos?.map((u, idx) => (
                    <tr key={idx} className="hover:bg-slate-800/40">
                      <td className="py-2.5 px-3 text-center">
                        <input
                          type="checkbox"
                          disabled={u.registrado}
                          checked={!!selectedUsers[u.username]}
                          onChange={() => handleToggleSelect(u.username)}
                          className="w-4 h-4 accent-indigo-600 rounded disabled:opacity-30"
                        />
                      </td>
                      <td className="py-2.5 px-3 font-mono font-bold text-slate-100">{u.username}</td>
                      <td className="py-2.5 px-3 text-slate-300">{u.empresa || '—'}</td>
                      <td className="py-2.5 px-3">
                        <div className="flex flex-wrap gap-1">
                          {u.vms?.map((vm, vidx) => (
                            <span key={vidx} className="bg-slate-900 border border-slate-800 text-slate-300 px-2 py-0.5 rounded text-[11px] font-mono">
                              {vm.nombre} ({vm.pool})
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        {u.registrado ? (
                          <span className="text-emerald-400 font-semibold text-[11px]">✔ Registrado</span>
                        ) : (
                          <span className="text-amber-400 font-semibold text-[11px]">Pendiente</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="primary" size="sm" icon={Download} disabled={isImporting} onClick={handleImportSelected}>
            {isImporting ? 'Importando...' : 'Registrar Seleccionados'}
          </Button>
        </div>
      </div>
    </div>
  );
}
