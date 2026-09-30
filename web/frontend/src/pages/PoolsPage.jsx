import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { acortarSnapshot } from '../utils/format';
import { Button } from '../components/ui/Button';
import {
  Layers,
  Search,
  UserCheck,
  Globe,
  Monitor,
  Users,
  CheckCircle,
  XCircle,
  Filter,
  X,
  ExternalLink,
  Shield,
  Clock,
  AlertTriangle,
  Crown,
  Copy,
  MonitorSmartphone,
  Box
} from 'lucide-react';

export function PoolsPage() {
  const [pageTab, setPageTab] = useState('pools'); // 'pools' | 'masters'
  const [search, setSearch] = useState('');
  const [origenFilter, setOrigenFilter] = useState('');
  const [tipoFilter, setTipoFilter] = useState('');
  const [assignmentFilter, setAssignmentFilter] = useState('');
  const [enabledFilter, setEnabledFilter] = useState('');
  const [selectedPool, setSelectedPool] = useState(null);
  const [activeModalTab, setActiveModalTab] = useState('autorizaciones'); // 'autorizaciones' | 'vms'

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['pools_detalladas'],
    queryFn: () => api.get('/pools/detalladas'),
  });

  const { data: mastersData, isLoading: isLoadingMasters, refetch: refetchMasters } = useQuery({
    queryKey: ['pools_masters'],
    queryFn: () => api.get('/pools/masters'),
    enabled: pageTab === 'masters',
  });
  const masters = mastersData?.items || [];

  const pools = data?.items || [];

  // Filtrado de pools
  const poolsFiltradas = pools.filter((p) => {
    if (origenFilter && (p.origen || '').toLowerCase() !== origenFilter.toLowerCase()) return false;
    if (tipoFilter && (p.tipo || '').toLowerCase() !== tipoFilter.toLowerCase()) return false;
    if (assignmentFilter && (p.user_assignment || '').toLowerCase() !== assignmentFilter.toLowerCase()) return false;
    if (enabledFilter && String(!!p.enabled) !== enabledFilter) return false;

    if (!search) return true;
    const q = search.toLowerCase();
    const matchName = (p.nombre || '').toLowerCase().includes(q) || (p.display_name || '').toLowerCase().includes(q);
    const matchEnt = (p.autorizaciones_locales || []).some(e => (e.usuario_o_grupo || '').toLowerCase().includes(q)) ||
                     (p.autorizaciones_globales || []).some(e => (e.usuario_o_grupo || '').toLowerCase().includes(q));
    return matchName || matchEnt;
  });

  // Métricas globales
  const totalPools = pools.length;
  const totalAutorizacionesLocales = pools.reduce((acc, p) => acc + (p.autorizaciones_locales?.length || 0), 0);
  const totalAutorizacionesGlobales = pools.reduce((acc, p) => acc + (p.autorizaciones_globales?.length || 0), 0);
  const totalVmsEnPools = pools.reduce((acc, p) => acc + (p.metricas?.total_vms || 0), 0);
  const totalErrores = pools.reduce((acc, p) => acc + (p.metricas?.errores || 0), 0);
  const seg = data?.segmentacion_global || { masters: 0, plantillas: 0, vdi_pool: 0, estaticas: 0 };

  // Consulta de VMs de la pool seleccionada
  const { data: vmsPoolData, isLoading: isLoadingVmsPool } = useQuery({
    queryKey: ['vms_pool', selectedPool?.nombre],
    queryFn: () => api.get('/maquinas', { params: { pool: selectedPool?.nombre, per_page: 500 } }),
    enabled: !!selectedPool && activeModalTab === 'vms',
  });

  const vmsPool = vmsPoolData?.items || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-tr from-cyan-500/20 to-indigo-500/20 border border-cyan-500/30 text-cyan-400">
              <Layers className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl font-black text-slate-100 tracking-tight">Gestión de Pools & Autorizaciones</h1>
              <p className="text-xs text-slate-400">
                Catálogo de Desktop Pools de Horizon, autorizaciones locales y globales (Pod Federation / Cloud)
              </p>
            </div>
          </div>
        </div>

        <Button variant="secondary" size="sm" onClick={() => pageTab === 'pools' ? refetch() : refetchMasters()}>
          Actualizar Datos
        </Button>
      </div>

      {/* Tabs de página */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-2">
        <button
          onClick={() => setPageTab('pools')}
          className={`px-3.5 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 ${
            pageTab === 'pools'
              ? 'bg-cyan-600 text-white shadow-md shadow-cyan-600/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Layers className="w-4 h-4" />
          <span>Pools</span>
        </button>
        <button
          onClick={() => setPageTab('masters')}
          className={`px-3.5 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 ${
            pageTab === 'masters'
              ? 'bg-purple-600 text-white shadow-md shadow-purple-600/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Crown className="w-4 h-4" />
          <span>Masters {mastersData?.total ? `(${mastersData.en_desuso} en desuso)` : ''}</span>
        </button>
      </div>

      {pageTab === 'masters' ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Card className="p-4 bg-slate-900/60 border-slate-800">
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Total Masters</div>
              <div className="text-xl font-extrabold text-slate-100 mt-0.5">{mastersData?.total || 0}</div>
            </Card>
            <Card className="p-4 bg-emerald-500/10 border-emerald-500/20">
              <div className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">En Uso</div>
              <div className="text-xl font-extrabold text-emerald-300 mt-0.5">{mastersData?.en_uso || 0}</div>
            </Card>
            <Card className="p-4 bg-rose-500/10 border-rose-500/20">
              <div className="text-[10px] font-bold text-rose-400 uppercase tracking-wider">En Desuso</div>
              <div className="text-xl font-extrabold text-rose-300 mt-0.5">{mastersData?.en_desuso || 0}</div>
            </Card>
            <Card className="p-4 bg-slate-900/60 border-slate-800">
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">VMs en Masters Activas</div>
              <div className="text-xl font-extrabold text-slate-100 mt-0.5">
                {masters.reduce((acc, m) => acc + (m.total_vms || 0), 0)}
              </div>
            </Card>
          </div>

          <Card>
            <div className="p-4 border-b border-slate-800">
              <h2 className="text-sm font-bold text-slate-200">Uso de Imágenes Master</h2>
              <p className="text-xs text-slate-400 mt-0.5">Derivado de qué master/snapshot está publicado actualmente en cada pool (pestaña "Imagen / Pool" en la ficha de VM).</p>
            </div>
            {isLoadingMasters ? (
              <div className="py-16 text-center text-xs text-slate-400 animate-pulse">Cruzando pools contra masters...</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300 border-collapse">
                  <thead className="bg-slate-900/90 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                    <tr>
                      <th className="py-3 px-4">Master VM</th>
                      <th className="py-3 px-4">Origen</th>
                      <th className="py-3 px-4">Estado</th>
                      <th className="py-3 px-4">Pools que la usan</th>
                      <th className="py-3 px-4">VMs Impactadas</th>
                      <th className="py-3 px-4">Storage Usado</th>
                      <th className="py-3 px-4">Última Publicación</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {masters.length === 0 ? (
                      <tr><td colSpan={7} className="py-12 text-center text-xs text-slate-500">Sin masters detectadas.</td></tr>
                    ) : (
                      masters.map((m) => (
                        <tr key={m.nombre} className="hover:bg-slate-800/40 transition-colors">
                          <td className="py-3 px-4 font-mono font-bold text-slate-100 whitespace-nowrap">{m.nombre}</td>
                          <td className="py-3 px-4 uppercase text-slate-400">{(m.origenes || []).join(', ') || '—'}</td>
                          <td className="py-3 px-4 whitespace-nowrap">
                            <Badge variant={m.en_uso ? 'success' : 'danger'}>{m.en_uso ? 'En uso' : 'En desuso'}</Badge>
                          </td>
                          <td className="py-3 px-4">
                            {m.pools.length === 0 ? (
                              <span className="text-slate-600">—</span>
                            ) : (
                              <div className="flex flex-wrap gap-1">
                                {m.pools.map((p) => <Badge key={p.id} variant="neutral">{p.nombre}</Badge>)}
                              </div>
                            )}
                          </td>
                          <td className="py-3 px-4 font-mono text-slate-200">{m.total_vms}</td>
                          <td className="py-3 px-4 font-mono text-slate-200">{m.disco_usado_gb} GB</td>
                          <td className="py-3 px-4 font-mono text-slate-400 whitespace-nowrap">{m.ultima_publicacion || '—'}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      ) : (
      <>
      {/* KPI Cards Bar */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <Card className="p-4 bg-slate-900/60 border-slate-800 flex items-center space-x-3">
          <div className="p-3 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Total Pools</div>
            <div className="text-xl font-extrabold text-slate-100 mt-0.5">{totalPools}</div>
          </div>
        </Card>

        <Card className="p-4 bg-slate-900/60 border-slate-800 flex items-center space-x-3">
          <div className="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
            <UserCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Autorizaciones Locales</div>
            <div className="text-xl font-extrabold text-slate-100 mt-0.5">{totalAutorizacionesLocales}</div>
          </div>
        </Card>

        <Card className="p-4 bg-slate-900/60 border-slate-800 flex items-center space-x-3">
          <div className="p-3 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
            <Globe className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Autorizaciones Globales</div>
            <div className="text-xl font-extrabold text-slate-100 mt-0.5">{totalAutorizacionesGlobales}</div>
          </div>
        </Card>

        <Card className="p-4 bg-slate-900/60 border-slate-800 flex items-center space-x-3">
          <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <Monitor className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">VDIs en Pools</div>
            <div className="text-xl font-extrabold text-slate-100 mt-0.5">{totalVmsEnPools}</div>
          </div>
        </Card>

        <Card className="p-4 bg-slate-900/60 border-slate-800 flex items-center space-x-3">
          <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">VMs en Error</div>
            <div className="text-xl font-extrabold text-slate-100 mt-0.5">{totalErrores}</div>
          </div>
        </Card>
      </div>

      {/* Segmentación global: Masters / Plantillas / VDI en Pool / Estáticas */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Card className="p-3 bg-purple-500/5 border-purple-500/20 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] text-purple-300 font-semibold"><Crown className="w-4 h-4" /> Masters</span>
          <span className="font-mono font-bold text-base text-purple-300">{seg.masters}</span>
        </Card>
        <Card className="p-3 bg-indigo-500/5 border-indigo-500/20 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] text-indigo-300 font-semibold"><Copy className="w-4 h-4" /> Plantillas</span>
          <span className="font-mono font-bold text-base text-indigo-300">{seg.plantillas}</span>
        </Card>
        <Card className="p-3 bg-emerald-500/5 border-emerald-500/20 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] text-emerald-300 font-semibold"><MonitorSmartphone className="w-4 h-4" /> VDI Pool</span>
          <span className="font-mono font-bold text-base text-emerald-300">{seg.vdi_pool}</span>
        </Card>
        <Card className="p-3 bg-slate-700/10 border-slate-600/30 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] text-slate-300 font-semibold"><Box className="w-4 h-4" /> Estáticas</span>
          <span className="font-mono font-bold text-base text-slate-300">{seg.estaticas}</span>
        </Card>
      </div>

      {/* Toolbar & Filters */}
      <Card className="p-4 bg-slate-900/80 border-slate-800 flex flex-col md:flex-row items-center gap-3">
        <div className="relative flex-1 w-full">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar pool por nombre, display name, usuario o grupo autorizado..."
            className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-4 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          <select
            value={origenFilter}
            onChange={(e) => setOrigenFilter(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
          >
            <option value="">Todos los Orígenes</option>
            <option value="dt">Desktop (dt)</option>
            <option value="su">Servers (su)</option>
            <option value="core">Core (core)</option>
            <option value="mz">DMZ (mz)</option>
          </select>

          <select
            value={tipoFilter}
            onChange={(e) => setTipoFilter(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
          >
            <option value="">Todos los Tipos</option>
            <option value="automated">Automated</option>
            <option value="manual">Manual</option>
            <option value="rds">RDS Farm</option>
          </select>

          <select
            value={assignmentFilter}
            onChange={(e) => setAssignmentFilter(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
          >
            <option value="">Asignación</option>
            <option value="dedicated">Dedicada</option>
            <option value="floating">Flotante</option>
          </select>

          <select
            value={enabledFilter}
            onChange={(e) => setEnabledFilter(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
          >
            <option value="">Habilitada/Deshabilitada</option>
            <option value="true">Solo Habilitadas</option>
            <option value="false">Solo Deshabilitadas</option>
          </select>
        </div>
      </Card>

      {/* Pools Grid */}
      {isLoading ? (
        <div className="py-20 text-center text-xs text-slate-400 animate-pulse">
          Cargando catálogo de Pools de Horizon y Autorizaciones...
        </div>
      ) : poolsFiltradas.length === 0 ? (
        <div className="py-20 text-center text-xs text-slate-500 bg-slate-900/40 rounded-2xl border border-slate-800">
          No se encontraron Pools de Horizon con los filtros especificados.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {poolsFiltradas.map((pool) => (
            <Card
              key={pool.id}
              className="p-5 bg-slate-900/80 border-slate-800 hover:border-cyan-500/50 transition-all flex flex-col justify-between group shadow-lg"
            >
              <div className="space-y-3">
                {/* Card Header */}
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-0.5">
                    <div className="flex items-center space-x-2">
                      <span className="text-[10px] font-extrabold uppercase tracking-wider text-cyan-400 font-mono">
                        [{pool.origen}]
                      </span>
                      <h3 className="text-sm font-bold text-slate-100 group-hover:text-cyan-300 transition-colors font-mono">
                        {pool.nombre}
                      </h3>
                    </div>
                    {pool.display_name && pool.display_name !== pool.nombre && (
                      <p className="text-xs text-slate-400">{pool.display_name}</p>
                    )}
                  </div>

                  <div className="flex items-center space-x-1 shrink-0">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      pool.enabled ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                    }`}>
                      {pool.enabled ? 'Habilitada' : 'Deshabilitada'}
                    </span>
                  </div>
                </div>

                {/* Badges Bar */}
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                    {pool.tipo}
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                    {pool.user_assignment}
                  </span>
                </div>

                {/* VM Counters Grid */}
                <div className="grid grid-cols-5 gap-2 py-2 px-3 bg-slate-950/60 rounded-xl border border-slate-800/80 text-center text-xs">
                  <div>
                    <div className="text-[9px] font-bold text-slate-500 uppercase">Total</div>
                    <div className="font-extrabold text-slate-200 mt-0.5">{pool.metricas?.total_vms || 0}</div>
                  </div>
                  <div>
                    <div className="text-[9px] font-bold text-emerald-500 uppercase">Conectad.</div>
                    <div className="font-extrabold text-emerald-400 mt-0.5">{pool.metricas?.conectadas || 0}</div>
                  </div>
                  <div>
                    <div className="text-[9px] font-bold text-cyan-500 uppercase">Disponib.</div>
                    <div className="font-extrabold text-cyan-400 mt-0.5">{pool.metricas?.disponibles || 0}</div>
                  </div>
                  <div>
                    <div className="text-[9px] font-bold text-amber-500 uppercase">Desconect.</div>
                    <div className="font-extrabold text-amber-400 mt-0.5">{pool.metricas?.desconectadas || 0}</div>
                  </div>
                  <div>
                    <div className="text-[9px] font-bold text-rose-500 uppercase">Error</div>
                    <div className="font-extrabold text-rose-400 mt-0.5">{pool.metricas?.errores || 0}</div>
                  </div>
                </div>

                {/* Segmentación de la pool */}
                <div className="flex items-center justify-between text-[10px] text-slate-500 font-mono px-1">
                  <span className="flex items-center gap-0.5" title="Masters"><Crown className="w-2.5 h-2.5" />{pool.metricas?.masters || 0}</span>
                  <span className="flex items-center gap-0.5" title="Plantillas"><Copy className="w-2.5 h-2.5" />{pool.metricas?.plantillas || 0}</span>
                  <span className="flex items-center gap-0.5" title="VDI Pool"><MonitorSmartphone className="w-2.5 h-2.5" />{pool.metricas?.vdi_pool || 0}</span>
                  <span className="flex items-center gap-0.5" title="Estáticas"><Box className="w-2.5 h-2.5" />{pool.metricas?.estaticas || 0}</span>
                </div>

                {/* Imagen actual (master VM + snapshot) -- derivada de eventos Image Publish de Horizon */}
                {pool.master_vm_actual && (
                  <div className="px-2.5 py-1.5 bg-purple-500/10 border border-purple-500/20 rounded-lg text-[11px] flex items-center gap-1.5" title={pool.snapshot_actual}>
                    <Crown className="w-3 h-3 text-purple-400 shrink-0" />
                    <span className="text-purple-300 font-mono font-bold truncate">{pool.master_vm_actual}</span>
                    {pool.snapshot_actual && (
                      <span className="text-purple-400/70 font-mono truncate">{acortarSnapshot(pool.snapshot_actual)}</span>
                    )}
                  </div>
                )}

                {/* Entitlements Summary */}
                <div className="pt-1 flex items-center justify-between text-xs text-slate-400">
                  <div className="flex items-center space-x-3">
                    <span className="flex items-center gap-1 text-[11px]">
                      <UserCheck className="w-3.5 h-3.5 text-indigo-400" />
                      Locales: <strong className="text-slate-200">{pool.autorizaciones_locales?.length || 0}</strong>
                    </span>
                    <span className="flex items-center gap-1 text-[11px]">
                      <Globe className="w-3.5 h-3.5 text-purple-400" />
                      Globales: <strong className="text-slate-200">{pool.autorizaciones_globales?.length || 0}</strong>
                    </span>
                  </div>
                </div>
              </div>

              {/* Card Footer Button */}
              <div className="pt-4 border-t border-slate-800/80 mt-4 flex items-center justify-between">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setSelectedPool(pool);
                    setActiveModalTab('autorizaciones');
                  }}
                  className="w-full text-xs hover:bg-cyan-500/10 hover:text-cyan-300 hover:border-cyan-500/30 transition-colors"
                >
                  <Shield className="w-3.5 h-3.5 mr-1.5 text-cyan-400" />
                  <span>Ver Autorizaciones ({pool.total_autorizaciones}) & VMs</span>
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
      </>
      )}

      {/* Pool Detail Modal */}
      {selectedPool && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="p-4 px-6 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
              <div className="flex items-center space-x-3">
                <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
                  <Layers className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <h2 className="text-base font-bold text-slate-100 font-mono">{selectedPool.nombre}</h2>
                    <span className="text-xs font-mono font-bold text-cyan-400 uppercase">[{selectedPool.origen}]</span>
                  </div>
                  <p className="text-xs text-slate-400">
                    {selectedPool.display_name} • {selectedPool.tipo} ({selectedPool.user_assignment})
                  </p>
                </div>
              </div>

              <button
                onClick={() => setSelectedPool(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Tabs Header */}
            <div className="px-6 pt-3 border-b border-slate-800 bg-slate-900/50 flex space-x-3">
              <button
                onClick={() => setActiveModalTab('autorizaciones')}
                className={`pb-2.5 text-xs font-bold transition-colors border-b-2 flex items-center space-x-1.5 ${
                  activeModalTab === 'autorizaciones'
                    ? 'border-cyan-500 text-cyan-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Shield className="w-4 h-4" />
                <span>Autorizaciones Locales & Globales ({selectedPool.total_autorizaciones})</span>
              </button>

              <button
                onClick={() => setActiveModalTab('vms')}
                className={`pb-2.5 text-xs font-bold transition-colors border-b-2 flex items-center space-x-1.5 ${
                  activeModalTab === 'vms'
                    ? 'border-cyan-500 text-cyan-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Monitor className="w-4 h-4" />
                <span>VMs en esta Pool ({selectedPool.metricas?.total_vms || 0})</span>
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-5">
              {/* TAB 1: Autorizaciones */}
              {activeModalTab === 'autorizaciones' && (
                <div className="space-y-4">
                  <div className="p-3 bg-slate-950/60 rounded-xl border border-slate-800 text-xs text-slate-300">
                    Usuarios y Grupos de Active Directory con acceso asignado directamente en esta Pool o via Cloud Pod Federation.
                  </div>

                  {selectedPool.total_autorizaciones === 0 ? (
                    <div className="py-12 text-center text-xs text-slate-500">
                      No hay autorizaciones locales ni globales registradas para esta Pool.
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {/* Locales */}
                      {selectedPool.autorizaciones_locales?.length > 0 && (
                        <div className="space-y-2">
                          <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-wider flex items-center gap-1.5">
                            <UserCheck className="w-4 h-4" />
                            Autorizaciones Locales Horizon ({selectedPool.autorizaciones_locales.length})
                          </h4>
                          <div className="overflow-x-auto rounded-xl border border-slate-800">
                            <table className="w-full text-left text-xs text-slate-300">
                              <thead className="bg-slate-950 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                                <tr>
                                  <th className="py-2.5 px-3">Usuario / Grupo AD</th>
                                  <th className="py-2.5 px-3">Tipo Entidad</th>
                                  <th className="py-2.5 px-3">Ámbito</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-800/60">
                                {selectedPool.autorizaciones_locales.map((ent) => (
                                  <tr key={ent.id} className="hover:bg-slate-800/40">
                                    <td className="py-2.5 px-3 font-semibold text-slate-100 font-mono">
                                      {ent.usuario_o_grupo}
                                    </td>
                                    <td className="py-2.5 px-3">
                                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                        ent.es_grupo ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' : 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                                      }`}>
                                        {ent.es_grupo ? '👥 GRUPO AD' : '👤 USUARIO'}
                                      </span>
                                    </td>
                                    <td className="py-2.5 px-3">
                                      <Badge variant="indigo">LOCAL POOL</Badge>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      {/* Globales */}
                      {selectedPool.autorizaciones_globales?.length > 0 && (
                        <div className="space-y-2">
                          <h4 className="text-xs font-bold text-purple-400 uppercase tracking-wider flex items-center gap-1.5">
                            <Globe className="w-4 h-4" />
                            Autorizaciones Globales (Cloud / Pod Federation) ({selectedPool.autorizaciones_globales.length})
                          </h4>
                          <div className="overflow-x-auto rounded-xl border border-slate-800">
                            <table className="w-full text-left text-xs text-slate-300">
                              <thead className="bg-slate-950 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                                <tr>
                                  <th className="py-2.5 px-3">Usuario / Grupo AD</th>
                                  <th className="py-2.5 px-3">Tipo Entidad</th>
                                  <th className="py-2.5 px-3">Ámbito</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-800/60">
                                {selectedPool.autorizaciones_globales.map((ent) => (
                                  <tr key={ent.id} className="hover:bg-slate-800/40">
                                    <td className="py-2.5 px-3 font-semibold text-slate-100 font-mono">
                                      {ent.usuario_o_grupo}
                                    </td>
                                    <td className="py-2.5 px-3">
                                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                        ent.es_grupo ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' : 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                                      }`}>
                                        {ent.es_grupo ? '👥 GRUPO AD' : '👤 USUARIO'}
                                      </span>
                                    </td>
                                    <td className="py-2.5 px-3">
                                      <Badge variant="purple">GLOBAL POD</Badge>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 2: VMs de la Pool */}
              {activeModalTab === 'vms' && (
                <div className="space-y-3">
                  {isLoadingVmsPool ? (
                    <div className="py-12 text-center text-xs text-slate-400 animate-pulse">
                      Obteniendo lista de máquinas virtuales asociadas...
                    </div>
                  ) : vmsPool.length === 0 ? (
                    <div className="py-12 text-center text-xs text-slate-500">
                      No hay máquinas virtuales asignadas a esta Pool en el inventario actual.
                    </div>
                  ) : (
                    <div className="overflow-x-auto rounded-xl border border-slate-800">
                      <table className="w-full text-left text-xs text-slate-300">
                        <thead className="bg-slate-950 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                          <tr>
                            <th className="py-2.5 px-3">Nombre VM</th>
                            <th className="py-2.5 px-3">Usuario Asignado</th>
                            <th className="py-2.5 px-3">Estado Horizon</th>
                            <th className="py-2.5 px-3">Dirección IP</th>
                            <th className="py-2.5 px-3">Host ESXi</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/60">
                          {vmsPool.map((vm) => (
                            <tr key={vm.id} className="hover:bg-slate-800/40 font-mono">
                              <td className="py-2.5 px-3 font-semibold text-slate-100">{vm.nombre}</td>
                              <td className="py-2.5 px-3 text-slate-300 font-sans">{vm.usuario_asignado || '—'}</td>
                              <td className="py-2.5 px-3">
                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                  vm.estado_horizon === 'CONNECTED' ? 'bg-emerald-500/20 text-emerald-300' :
                                  vm.estado_horizon === 'AVAILABLE' ? 'bg-cyan-500/20 text-cyan-300' :
                                  'bg-slate-800 text-slate-400'
                                }`}>
                                  {vm.estado_horizon || '—'}
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-slate-400">{vm.ip || '—'}</td>
                              <td className="py-2.5 px-3 text-slate-400">{vm.vcenter_host || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
