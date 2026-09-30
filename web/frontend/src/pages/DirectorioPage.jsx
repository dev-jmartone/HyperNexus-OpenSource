import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ImportarExtraidosModal } from '../components/modals/ImportarExtraidosModal';
import { confirmar, toastError } from '../utils/alerts';
import { 
  Users, 
  Search, 
  UserCheck, 
  Eye, 
  Monitor, 
  RefreshCw, 
  Zap, 
  ShieldCheck, 
  Mail, 
  CheckCircle,
  XCircle,
  Building,
  Unlink,
  Link,
  Phone,
  Calendar,
  Download,
  Package,
  Activity,
  Sprout
} from 'lucide-react';

import { getTeamsChatUrl } from '../utils/navigation';

export function DirectorioPage({ globalSearch }) {
  const [search, setSearch] = useState('');
  const [empresaFilter, setEmpresaFilter] = useState('');
  const [estadoAdFilter, setEstadoAdFilter] = useState('todos');
  const [conVmsFilter, setConVmsFilter] = useState('todos');

  const activeQuery = globalSearch || search;

  const [selectedUser, setSelectedUser] = useState(null);
  const [userFichaData, setUserFichaData] = useState(null);
  const [isFichaLoading, setIsFichaLoading] = useState(false);

  // Sync Action States
  const [syncStatus, setSyncStatus] = useState(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);


  // Link VM state inside modal
  const [linkSearch, setLinkSearch] = useState('');
  const [availableVms, setAvailableVms] = useState([]);
  const [selectedVmToLink, setSelectedVmToLink] = useState('');

  const { data: usuarios, isLoading, refetch } = useQuery({
    queryKey: ['directorio_usuarios', activeQuery, empresaFilter, estadoAdFilter, conVmsFilter],
    queryFn: () => api.get('/directorio/usuarios', {
      params: { 
        q: activeQuery, 
        empresa: empresaFilter || undefined,
        estado_ad: estadoAdFilter !== 'todos' ? estadoAdFilter : undefined,
        con_vms: conVmsFilter !== 'todos' ? conVmsFilter : undefined,
      }
    }),
  });

  // Lista única de empresas para el selector
  const empresasList = Array.from(
    new Set((usuarios || []).map(u => u.empresa).filter(Boolean))
  ).sort();

  const handleClearFilters = () => {
    setSearch('');
    setEmpresaFilter('');
    setEstadoAdFilter('todos');
    setConVmsFilter('todos');
  };


  const handleOpenFicha = async (user) => {
    setSelectedUser(user);
    setIsFichaLoading(true);
    try {
      const res = await api.get(`/directorio/usuarios/${user.id}`);
      setUserFichaData(res);
      setIsFichaLoading(false);
    } catch (e) {
      setIsFichaLoading(false);
    }
  };

  const handleSincronizarTodo = async () => {
    try {
      setIsSyncing(true);
      setSyncStatus('Sincronizando todas las máquinas extraídas con el directorio...');
      const res = await api.post('/directorio/sincronizar_todo');
      setIsSyncing(false);
      setSyncStatus(`¡Sincronización completada! ${res.usuarios_creados} usuarios creados, ${res.vinculos_creados} vínculos establecidos.`);
      refetch();
      setTimeout(() => setSyncStatus(null), 5000);
    } catch (e) {
      setIsSyncing(false);
      setSyncStatus('Error durante la sincronización');
    }
  };

  const handleVerificarAD = async () => {
    try {
      setIsSyncing(true);
      setSyncStatus('Consultando Active Directory...');
      const res = await api.post('/directorio/verificar_ad');
      setIsSyncing(false);
      setSyncStatus(`¡Verificación AD completada! ${res.encontrados} encontrados, ${res.actualizados} actualizados.`);
      refetch();
      setTimeout(() => setSyncStatus(null), 5000);
    } catch (e) {
      setIsSyncing(false);
      setSyncStatus('Error al consultar Active Directory');
    }
  };

  const handleEnriquecerGAL = async () => {
    try {
      setIsSyncing(true);
      setSyncStatus('Consultando catálogo Outlook GAL...');
      const res = await api.post('/directorio/enriquecer_gal');
      setIsSyncing(false);
      setSyncStatus(`¡Enriquecimiento completado! ${res.enriquecidos} usuarios actualizados.`);
      refetch();
      setTimeout(() => setSyncStatus(null), 5000);
    } catch (e) {
      setIsSyncing(false);
      setSyncStatus('Error al consultar Outlook GAL');
    }
  };

  const handleSearchVmsToLink = async (val) => {
    setLinkSearch(val);
    if (!val || val.length < 2) {
      setAvailableVms([]);
      return;
    }
    try {
      const res = await api.get('/maquinas', { params: { q: val, simple: '1' } });
      setAvailableVms(res);
    } catch (e) {
      setAvailableVms([]);
    }
  };

  const handleVincularVm = async () => {
    if (!selectedUser || !selectedVmToLink) return;
    try {
      await api.post('/directorio/vincular', {
        directorio_usuario_id: selectedUser.id,
        maquina_id: parseInt(selectedVmToLink),
        tipo: 'principal'
      });
      setSelectedVmToLink('');
      setLinkSearch('');
      setAvailableVms([]);
      handleOpenFicha(selectedUser);
      refetch();
    } catch (e) {
      toastError(e.response?.data?.error || 'Error al vincular máquina');
    }
  };

  const handleDesvincularVm = async (vinculoId) => {
    if (!vinculoId) return;
    const confirmado = await confirmar({
      titulo: '¿Desvincular este escritorio del usuario?',
      texto: 'Podés volver a vincularlo después si te equivocaste.',
      icon: 'warning',
      confirmText: 'Sí, desvincular',
    });
    if (!confirmado) return;
    try {
      await api.post(`/directorio/desvincular/${vinculoId}`);
      handleOpenFicha(selectedUser);
      refetch();
    } catch (e) {
      toastError('Error al desvincular');
    }
  };

  return (
    <div className="space-y-6">
      {/* Sync Toolbar */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <Users className="w-5 h-5 text-indigo-400" />
            <div>
              <h3 className="text-sm font-bold text-slate-100">Directorio Corporativo de Usuarios</h3>
              <p className="text-xs text-slate-400">Integración con Active Directory (AD) y Vinculación VDI</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" size="sm" icon={Download} onClick={() => setIsImportModalOpen(true)}>
              Importar Extraídos
            </Button>
            <Button variant="secondary" size="sm" icon={Zap} disabled={isSyncing} onClick={handleSincronizarTodo}>
              Sincronizar Todo
            </Button>
            <Button variant="secondary" size="sm" icon={ShieldCheck} disabled={isSyncing} onClick={handleVerificarAD}>
              Verificar AD
            </Button>
            <Button variant="secondary" size="sm" icon={Mail} disabled={isSyncing} onClick={handleEnriquecerGAL}>
              Enriquecer GAL
            </Button>
            <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => refetch()}>
              Recargar
            </Button>
          </div>

        </div>

        {syncStatus && (
          <div className="mt-3 p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-indigo-300 text-xs font-medium flex items-center">
            {isSyncing && <div className="w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mr-2 shrink-0"></div>}
            <span>{syncStatus}</span>
          </div>
        )}
      </Card>

      {/* Main Users Table */}
      <Card>
        <div className="space-y-3 mb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="relative flex-1 min-w-[240px] max-w-md">
              <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar usuario, legajo, departamento, empresa..."
                className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-10 pr-4 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2.5 text-xs">
              <div>
                <select
                  value={empresaFilter}
                  onChange={(e) => setEmpresaFilter(e.target.value)}
                  className="bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="">Todas las Empresas</option>
                  {empresasList.map((emp) => (
                    <option key={emp} value={emp}>{emp}</option>
                  ))}
                </select>
              </div>

              <div>
                <select
                  value={estadoAdFilter}
                  onChange={(e) => setEstadoAdFilter(e.target.value)}
                  className="bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="todos">Estado AD: Todos</option>
                  <option value="activo">Solo Activos AD</option>
                  <option value="inactivo">Solo Inactivos AD</option>
                </select>
              </div>

              <div>
                <select
                  value={conVmsFilter}
                  onChange={(e) => setConVmsFilter(e.target.value)}
                  className="bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="todos">Escritorios: Todos</option>
                  <option value="con_vms">Con VMs Asignadas</option>
                  <option value="sin_vms">Sin VMs (0 Asignaciones)</option>
                </select>
              </div>

              <span className="text-slate-500">|</span>
              <span className="text-slate-400">Total: <strong className="text-slate-200">{usuarios?.length || 0}</strong></span>
            </div>
          </div>

          {/* Active filter pills for Directorio */}
          {(search || empresaFilter || estadoAdFilter !== 'todos' || conVmsFilter !== 'todos') && (
            <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-800/60 text-xs">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Activos:</span>

              {search && (
                <span className="px-2.5 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-[11px] font-medium flex items-center space-x-1">
                  <span>Búsqueda: "{search}"</span>
                  <button onClick={() => setSearch('')} className="hover:text-white ml-1">✕</button>
                </span>
              )}

              {empresaFilter && (
                <span className="px-2.5 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-[11px] font-medium flex items-center space-x-1">
                  <span>Empresa: {empresaFilter}</span>
                  <button onClick={() => setEmpresaFilter('')} className="hover:text-white ml-1">✕</button>
                </span>
              )}

              {estadoAdFilter !== 'todos' && (
                <span className="px-2.5 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-[11px] font-medium flex items-center space-x-1">
                  <span>Estado AD: {estadoAdFilter}</span>
                  <button onClick={() => setEstadoAdFilter('todos')} className="hover:text-white ml-1">✕</button>
                </span>
              )}

              {conVmsFilter !== 'todos' && (
                <span className="px-2.5 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-[11px] font-medium flex items-center space-x-1">
                  <span>VMs: {conVmsFilter}</span>
                  <button onClick={() => setConVmsFilter('todos')} className="hover:text-white ml-1">✕</button>
                </span>
              )}

              <button 
                onClick={handleClearFilters}
                className="text-[11px] font-semibold text-rose-400 hover:text-rose-300 hover:underline ml-2"
              >
                Limpiar Todos
              </button>
            </div>
          )}
        </div>


        {isLoading ? (
          <div className="py-20 text-center text-slate-400 animate-pulse">Cargando directorio corporativo...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300 border-collapse">
              <thead className="bg-slate-900/90 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Usuario AD</th>
                  <th className="py-3 px-4">Nombre Completo</th>
                  <th className="py-3 px-4">Correo Electrónico</th>
                  <th className="py-3 px-4">Empresa / Depto</th>
                  <th className="py-3 px-4">Estado AD</th>
                  <th className="py-3 px-4">Asignación (VMs & Pools)</th>
                  <th className="py-3 px-4 text-center">Carta Ficha</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {usuarios?.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-8 text-center text-slate-500">No se encontraron usuarios en el directorio.</td>
                  </tr>
                ) : (
                  usuarios?.map((u) => {
                    const vmsCount = u.vms?.length || 0;
                    const poolsCount = new Set((u.vms || []).map(v => v.pool).filter(Boolean)).size;
                    const teamsUrl = getTeamsChatUrl(u);

                    return (
                      <tr key={u.id} className="hover:bg-slate-800/40 transition-colors cursor-pointer" onClick={() => handleOpenFicha(u)}>
                        <td className="py-3 px-4 font-bold text-slate-100 flex items-center whitespace-nowrap">
                          <UserCheck className="w-4 h-4 mr-2 text-indigo-400 shrink-0" />
                          {teamsUrl ? (
                            <a
                              href={teamsUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="hover:text-indigo-400 hover:underline flex items-center group"
                              title="Iniciar Chat en Microsoft Teams"
                            >
                              <span>{u.username}</span>
                              <span className="ml-1 text-[10px] px-1 py-0.2 rounded bg-indigo-500/20 text-indigo-300 group-hover:bg-indigo-500 group-hover:text-white transition-colors">
                                💬 Teams
                              </span>
                            </a>
                          ) : (
                            <span>{u.username || '—'}</span>
                          )}
                        </td>
                        <td className="py-3 px-4 font-semibold text-slate-200">{u.nombre_completo || '—'}</td>
                        <td className="py-3 px-4 font-mono text-slate-400">
                          {u.email && getTeamsChatUrl(u.email) ? (
                            <a
                              href={getTeamsChatUrl(u.email)}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="hover:text-indigo-300 hover:underline"
                              title="Chat Teams"
                            >
                              {u.email}
                            </a>
                          ) : (
                            u.email || '—'
                          )}
                        </td>
                        <td className="py-3 px-4 text-slate-300">
                          {u.empresa || '—'} {u.departamento ? `• ${u.departamento}` : ''}
                        </td>
                        <td className="py-3 px-4 whitespace-nowrap">
                          {u.activo_ad ? (
                            <Badge variant="success"><CheckCircle className="w-3 h-3 mr-1 inline" /> ACTIVO AD</Badge>
                          ) : (
                            <Badge variant="danger"><XCircle className="w-3 h-3 mr-1 inline" /> INACTIVO AD</Badge>
                          )}
                        </td>
                        <td className="py-3 px-4 whitespace-nowrap">
                          {vmsCount > 0 ? (
                            <Badge variant="purple" className="font-mono font-bold">
                              {vmsCount} {vmsCount === 1 ? 'VM' : 'VMs'} • {poolsCount} {poolsCount === 1 ? 'Pool' : 'Pools'}
                            </Badge>
                          ) : (
                            <span className="text-slate-500 font-mono text-[11px]">0 Asignaciones</span>
                          )}
                        </td>

                        <td className="py-3 px-4 text-center" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-center space-x-2">
                            {teamsUrl && (
                              <a
                                href={teamsUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="p-1.5 rounded-lg text-indigo-400 hover:text-white hover:bg-indigo-600/30 border border-indigo-500/20 transition-colors"
                                title="Iniciar Chat en Microsoft Teams"
                              >
                                💬 Teams
                              </a>
                            )}
                            <button
                              onClick={() => handleOpenFicha(u)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-400 hover:bg-slate-800 transition-colors"
                              title="Abrir Carta Ficha de Usuario"
                            >
                              <Eye className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* User Card Ficha Modal */}
      {selectedUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/85 backdrop-blur-md animate-fade-in">
          <div className="w-full max-w-3xl glass-panel p-6 rounded-2xl border border-slate-800 shadow-2xl space-y-5 max-h-[90vh] overflow-y-auto">
            {/* Header with User Info */}
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center space-x-4">
                <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-indigo-600 to-indigo-400 flex items-center justify-center text-white font-bold text-lg shadow-lg shadow-indigo-600/30">
                  {selectedUser.username.substring(0, 2).toUpperCase()}
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <h3 className="text-lg font-bold text-slate-100">{selectedUser.nombre_completo || selectedUser.username}</h3>
                    {selectedUser.activo_ad ? (
                      <Badge variant="success">ACTIVO AD</Badge>
                    ) : (
                      <Badge variant="danger">INACTIVO AD</Badge>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 font-mono mt-0.5">@{selectedUser.username} • {selectedUser.empresa || 'Sin Empresa'}</p>
                </div>
              </div>

              <div className="flex items-center space-x-2">
                {getTeamsChatUrl(selectedUser) && (
                  <a
                    href={getTeamsChatUrl(selectedUser)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center space-x-1.5 transition-colors shadow-md shadow-indigo-600/30"
                    title="Iniciar Chat en Microsoft Teams"
                  >
                    <span>💬 Chat en Teams</span>
                  </a>
                )}
                <button onClick={() => setSelectedUser(null)} className="text-slate-400 hover:text-slate-200 text-2xl font-bold p-1">×</button>
              </div>
            </div>

            {/* Profile Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                <div className="text-slate-500 uppercase text-[10px] font-semibold flex items-center"><Mail className="w-3 h-3 mr-1 text-indigo-400" /> Email</div>
                <div className="font-mono text-slate-200 mt-1 truncate" title={selectedUser.email}>{selectedUser.email || '—'}</div>
              </div>

              <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                <div className="text-slate-500 uppercase text-[10px] font-semibold flex items-center"><Building className="w-3 h-3 mr-1 text-indigo-400" /> Departamento</div>
                <div className="text-slate-200 mt-1 truncate" title={selectedUser.departamento}>{selectedUser.departamento || '—'}</div>
              </div>

              <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                <div className="text-slate-500 uppercase text-[10px] font-semibold flex items-center"><Phone className="w-3 h-3 mr-1 text-indigo-400" /> Teléfono</div>
                <div className="font-mono text-slate-200 mt-1">{selectedUser.telefono || '—'}</div>
              </div>

              <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                <div className="text-slate-500 uppercase text-[10px] font-semibold flex items-center"><Calendar className="w-3 h-3 mr-1 text-indigo-400" /> Registro</div>
                <div className="text-slate-300 mt-1">{selectedUser.created_at ? new Date(selectedUser.created_at).toLocaleDateString('es-AR') : '—'}</div>
              </div>
            </div>

            {selectedUser.notas && (
              <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800/80 text-xs text-slate-300">
                <span className="font-semibold text-slate-400 uppercase text-[10px] block mb-0.5">Notas de Usuario</span>
                {selectedUser.notas}
              </div>
            )}

            {/* Linked VMs and Pools Section */}
            <div className="space-y-3 pt-3 border-t border-slate-800">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-wider flex items-center">
                  <Monitor className="w-4 h-4 mr-1.5" /> Escritorios VDI y VMs Asignadas ({userFichaData?.asignaciones?.length || 0})
                </h4>
              </div>

              {isFichaLoading ? (
                <div className="py-8 text-center text-slate-400 animate-pulse text-xs">Cargando datos detallados de escritorios...</div>
              ) : (
                <div className="space-y-2.5 max-h-60 overflow-y-auto pr-1">
                  {userFichaData?.asignaciones?.length === 0 ? (
                    <div className="p-4 bg-slate-900/40 rounded-xl text-center text-slate-500 text-xs italic">
                      Este usuario no tiene escritorios ni pools vinculados actualmente.
                    </div>
                  ) : (
                    userFichaData?.asignaciones?.map((item, idx) => {
                      const m = item.maquina || {};
                      return (
                        <div key={idx} className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800/90 space-y-2 hover:border-slate-700 transition-colors text-xs">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center space-x-2">
                              <Monitor className="w-4 h-4 text-indigo-400" />
                              <span className="font-mono font-bold text-slate-100">{m.nombre}</span>
                              <Badge variant={m.tipo === 'VDI' ? 'info' : 'neutral'}>{m.tipo}</Badge>
                              {m.origen && <span className="text-[10px] font-mono text-indigo-400 uppercase">[{m.origen}]</span>}
                            </div>

                            <div className="flex items-center space-x-2">
                              <Badge variant={m.estado_horizon === 'CONNECTED' ? 'success' : 'neutral'}>
                                {m.estado_horizon || 'DISPONIBLE'}
                              </Badge>

                              {item.vinculo_id && (
                                <button
                                  onClick={() => handleDesvincularVm(item.vinculo_id)}
                                  className="p-1 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded transition-colors"
                                  title="Desvincular de usuario"
                                >
                                  <Unlink className="w-4 h-4" />
                                </button>
                              )}
                            </div>
                          </div>

                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] text-slate-400 pt-1 border-t border-slate-800/60">
                            <div>Pool: <strong className="text-slate-200">{m.pool || 'Sin Pool'}</strong></div>
                            <div>Empresa: <span className="text-slate-200">{m.empresa || '—'}</span></div>
                            <div>IP: <span className="font-mono text-slate-200">{m.ip || '—'}</span></div>
                            <div>Recursos: <span className="font-mono text-slate-200">{m.cpu ? `${m.cpu}CPU / ${m.ram_gb}GB` : '—'}</span></div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>

            {/* App Volumes — apps asignadas + actividad reciente */}
            <div className="space-y-3 pt-3 border-t border-slate-800">
              <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center">
                <Package className="w-4 h-4 mr-1.5" /> Aplicaciones App Volumes ({userFichaData?.appvolumes_apps?.length || 0})
              </h4>

              {isFichaLoading ? (
                <div className="py-4 text-center text-slate-400 animate-pulse text-xs">Cargando aplicaciones asignadas...</div>
              ) : (userFichaData?.appvolumes_apps?.length || 0) === 0 ? (
                <div className="p-4 bg-slate-900/40 rounded-xl text-center text-slate-500 text-xs italic">
                  Sin asignaciones de App Volumes detectadas para este usuario.
                </div>
              ) : (
                <div className="space-y-2 max-h-44 overflow-y-auto pr-1">
                  {userFichaData.appvolumes_apps.map((a, idx) => (
                    <div key={idx} className="p-3 rounded-xl bg-slate-900/90 border border-slate-800/90 text-xs flex items-center justify-between">
                      <div className="flex items-center space-x-2 min-w-0">
                        <Package className="w-4 h-4 text-emerald-400 shrink-0" />
                        <span className="font-bold text-slate-100 truncate">{a.aplicacion_nombre || a.paquete_nombre || `App ${a.av_id}`}</span>
                      </div>
                      <div className="flex items-center space-x-1.5 shrink-0">
                        {a.delivery && <Badge variant="info">{a.delivery}</Badge>}
                        {(a.servidores || []).map((srv) => (
                          <Badge key={srv} variant="success">{srv}</Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {(userFichaData?.appvolumes_actividad?.length || 0) > 0 && (
                <div className="space-y-2 pt-1">
                  <h5 className="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center">
                    <Activity className="w-3.5 h-3.5 mr-1" /> Actividad reciente
                  </h5>
                  <div className="space-y-1.5 max-h-32 overflow-y-auto pr-1">
                    {userFichaData.appvolumes_actividad.map((e, idx) => (
                      <div key={idx} className="px-3 py-1.5 rounded-lg bg-slate-900/70 border border-slate-800/70 text-[11px] flex items-center justify-between">
                        <span className="font-mono text-slate-300 truncate">{e.accion || '—'} — {e.target_name || '—'}</span>
                        <span className="text-slate-500 shrink-0 ml-2">{e.event_time || '—'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Granja RDS — aplicaciones publicadas autorizadas + VDI-VMs existentes */}
            <div className="space-y-3 pt-3 border-t border-slate-800">
              <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center">
                <Sprout className="w-4 h-4 mr-1.5" /> Accesos de Granja RDS ({userFichaData?.granja_aplicaciones?.length || 0})
              </h4>

              {isFichaLoading ? (
                <div className="py-4 text-center text-slate-400 animate-pulse text-xs">Cargando accesos de granja...</div>
              ) : (userFichaData?.granja_aplicaciones?.length || 0) === 0 ? (
                <div className="p-4 bg-slate-900/40 rounded-xl text-center text-slate-500 text-xs italic">
                  Sin autorizaciones de Granja RDS detectadas para este usuario.
                </div>
              ) : (
                <div className="space-y-2 max-h-44 overflow-y-auto pr-1">
                  {userFichaData.granja_aplicaciones.map((a, idx) => (
                    <div key={idx} className="p-3 rounded-xl bg-slate-900/90 border border-slate-800/90 text-xs flex items-center justify-between">
                      <div className="flex items-center space-x-2 min-w-0">
                        <Sprout className="w-4 h-4 text-emerald-400 shrink-0" />
                        <span className="font-bold text-slate-100 truncate">{a.aplicacion_nombre}</span>
                        {a.farm_nombre && <span className="text-slate-500 font-mono">({a.farm_nombre})</span>}
                      </div>
                      <Badge variant={a.tipo_entitlement === 'Global' ? 'purple' : 'neutral'}>{a.tipo_entitlement}</Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Link New VM Search Select */}
            <div className="pt-3 border-t border-slate-800 space-y-2">
              <label className="block text-xs font-semibold text-slate-300">Vincular Nuevo Escritorio VDI / VM a este Usuario</label>
              <div className="flex items-center space-x-2">
                <div className="relative flex-1">
                  <input
                    type="text"
                    value={linkSearch}
                    onChange={(e) => handleSearchVmsToLink(e.target.value)}
                    placeholder="Buscar VM por nombre o pool..."
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                  {availableVms.length > 0 && (
                    <div className="absolute left-0 right-0 top-full mt-1 bg-slate-900 border border-slate-700 rounded-xl max-h-36 overflow-y-auto shadow-2xl z-20">
                      {availableVms.map((vm) => (
                        <div
                          key={vm.id}
                          onClick={() => { setSelectedVmToLink(vm.id); setLinkSearch(`${vm.nombre} (${vm.pool})`); setAvailableVms([]); }}
                          className="p-2 hover:bg-slate-800 text-xs text-slate-200 cursor-pointer flex justify-between"
                        >
                          <span className="font-mono font-bold">{vm.nombre}</span>
                          <span className="text-slate-400">{vm.pool || 'Sin Pool'}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <Button variant="primary" size="sm" icon={Link} disabled={!selectedVmToLink} onClick={handleVincularVm}>
                  Vincular
                </Button>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-800 flex justify-end">
              <Button variant="secondary" size="sm" onClick={() => setSelectedUser(null)}>
                Cerrar Carta
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modal para importar usuarios extraídos */}
      <ImportarExtraidosModal
        isOpen={isImportModalOpen}
        onClose={() => setIsImportModalOpen(false)}
        onImported={() => refetch()}
      />
    </div>
  );
}

