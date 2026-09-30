import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import {
  Zap,
  Search,
  Filter,
  Server,
  Sparkles,
  LogIn,
  LogOut,
  Trash2,
  Clock,
  User,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Package,
  Ghost,
  Users,
  GitMerge
} from 'lucide-react';

// confianza "alta" = verificamos afirmativamente que está decomisionada/inactiva.
// confianza "baja" = no está en nuestras tablas locales, pero eso no prueba que no
// exista en AD real (el Directorio local se arma de gente que usó una VDI, no es un
// sync completo de AD -- App Volumes también gestiona PCs físicas). No depurar "baja"
// sin confirmar contra AD/inventario real primero.
const MOTIVO_LABELS = {
  vm_decomisionada: { label: 'VM decomisionada (verificado)', confianza: 'alta' },
  usuario_inactivo: { label: 'Usuario inactivo/fuera de AD (verificado)', confianza: 'alta' },
  vm_no_encontrada: { label: 'VM sin rastro en inventario (no confirmado)', confianza: 'baja' },
  usuario_no_encontrado: { label: 'Usuario sin rastro en Directorio (no confirmado)', confianza: 'baja' },
};

export function ActividadPage() {
  const [activeTab, setActiveTab] = useState('eventos'); // 'eventos' | 'appvolumes_huerfanas'

  const [search, setSearch] = useState('');
  const [tipoFiltro, setTipoFiltro] = useState('');
  const [servidorFiltro, setServidorFiltro] = useState('');
  const [verTodo, setVerTodo] = useState(false);

  const { data: novedadesData, isLoading, refetch } = useQuery({
    queryKey: ['actividad_novedades', verTodo],
    queryFn: () => api.get(verTodo ? '/novedades?todo=1' : '/novedades'),
    refetchInterval: 15000,
  });

  const { data: servidoresData } = useQuery({
    queryKey: ['servidores_list'],
    queryFn: () => api.get('/servidores'),
  });

  const [huerfanasSearch, setHuerfanasSearch] = useState('');
  const [huerfanasMotivo, setHuerfanasMotivo] = useState('');

  const { data: huerfanasData, isLoading: isLoadingHuerfanas, refetch: refetchHuerfanas } = useQuery({
    queryKey: ['appvolumes_huerfanas'],
    queryFn: () => api.get('/appvolumes/huerfanas'),
    enabled: activeTab === 'appvolumes_huerfanas',
  });

  const { data: duplicadosData, isLoading: isLoadingDuplicados, refetch: refetchDuplicados } = useQuery({
    queryKey: ['directorio_duplicados'],
    queryFn: () => api.get('/directorio/duplicados'),
    enabled: activeTab === 'directorio_duplicados',
  });

  const [fusionandoPairId, setFusionandoPairId] = useState(null);
  const [fusionResultado, setFusionResultado] = useState(null);

  const handleFusionar = async (canonicoId, absorbidoId, pairId) => {
    setFusionandoPairId(pairId);
    setFusionResultado(null);
    try {
      const res = await api.post('/directorio/duplicados/fusionar', {
        canonico_id: canonicoId,
        absorbido_id: absorbidoId,
      });
      setFusionResultado({ ok: true, mensaje: res.mensaje || 'Fusión realizada con éxito.' });
      refetchDuplicados();
    } catch (e) {
      setFusionResultado({ ok: false, mensaje: e.response?.data?.error || 'Error al fusionar usuarios.' });
    } finally {
      setFusionandoPairId(null);
    }
  };

  const [isVerificandoAd, setIsVerificandoAd] = useState(false);
  const [verificarAdResultado, setVerificarAdResultado] = useState(null);

  const handleVerificarAd = async () => {
    setIsVerificandoAd(true);
    setVerificarAdResultado(null);
    try {
      const res = await api.post('/appvolumes/huerfanas/verificar_ad');
      setVerificarAdResultado(res);
      refetchHuerfanas();
    } catch (e) {
      setVerificarAdResultado({ ok: false, mensaje: e.response?.data?.error || 'Error al verificar contra AD' });
    } finally {
      setIsVerificandoAd(false);
    }
  };

  const eventos = novedadesData?.todos || novedadesData?.eventos_recientes || [];
  const servidores = servidoresData?.servidores || [];

  const eventosFiltrados = eventos.filter((ev) => {
    if (tipoFiltro && ev.tipo !== tipoFiltro) return false;
    if (servidorFiltro && ev.servidor !== servidorFiltro) return false;
    if (search) {
      const q = search.toLowerCase();
      const text = [ev.nombre_vm, ev.servidor, ev.usuario, ev.detalle, ev.origen, ev.pool].join(' ').toLowerCase();
      if (!text.includes(q)) return false;
    }
    return true;
  });

  const huerfanas = huerfanasData?.asignaciones || [];
  const huerfanasFiltradas = huerfanas.filter((h) => {
    if (huerfanasMotivo && h.motivo !== huerfanasMotivo) return false;
    if (huerfanasSearch) {
      const q = huerfanasSearch.toLowerCase();
      const text = [h.entity_name, h.aplicacion_nombre, h.paquete_nombre, ...(h.servidores || [])].join(' ').toLowerCase();
      if (!text.includes(q)) return false;
    }
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2 tracking-tight">
            <Zap className="w-6 h-6 text-indigo-400" />
            <span>Actividad y Novedades por Servidor</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Seguimiento de VMs nuevas, inicios de sesión, desinstalaciones y clasificación por servidor.
          </p>
        </div>
        <button
          onClick={() => activeTab === 'eventos' ? refetch() : activeTab === 'appvolumes_huerfanas' ? refetchHuerfanas() : refetchDuplicados()}
          className="px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-800 hover:bg-slate-800 text-xs font-semibold text-slate-200 transition-colors flex items-center space-x-2 self-start sm:self-auto shadow-sm"
        >
          <RefreshCw className="w-4 h-4 text-indigo-400" />
          <span>Actualizar</span>
        </button>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-2">
        <button
          onClick={() => setActiveTab('eventos')}
          className={`px-3.5 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 ${
            activeTab === 'eventos'
              ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Zap className="w-4 h-4" />
          <span>Feed de Eventos</span>
        </button>
        <button
          onClick={() => setActiveTab('appvolumes_huerfanas')}
          className={`px-3.5 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 ${
            activeTab === 'appvolumes_huerfanas'
              ? 'bg-amber-600 text-white shadow-md shadow-amber-600/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Ghost className="w-4 h-4" />
          <span>App Volumes Huérfanas {huerfanasData?.total ? `(${huerfanasData.total})` : ''}</span>
        </button>
        <button
          onClick={() => setActiveTab('directorio_duplicados')}
          className={`px-3.5 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 ${
            activeTab === 'directorio_duplicados'
              ? 'bg-purple-600 text-white shadow-md shadow-purple-600/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Users className="w-4 h-4" />
          <span>Duplicados Directorio {duplicadosData?.total ? `(${duplicadosData.total})` : ''}</span>
        </button>
      </div>

      {activeTab === 'appvolumes_huerfanas' ? (
        <div className="space-y-6">
          <div className="p-3.5 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-xs flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>
              Asignaciones de App Volumes que siguen activas en el App Volumes Manager pero apuntan a una VM o usuario
              que ya no existe (o está inactivo) en este inventario. Esta app no las borra del lado de App Volumes —
              es una lista para depurar manualmente en el Admin UI real y liberar recursos.
              <strong className="text-amber-200"> Ojo con "no confirmado":</strong> solo significa que no está en
              nuestras tablas locales, no que no exista en AD real — verificá antes de borrar.
            </span>
          </div>

          {/* Verificar contra AD real */}
          <Card className="p-4">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
              <div className="text-xs text-slate-400">
                AD real puede tener el logon name y el sAMAccountName (pre-Windows 2000) como strings distintos —
                un usuario "sin rastro en Directorio" puede existir de verdad bajo otro nombre. Esto consulta AD
                directamente y actualiza el Directorio si aparece.
              </div>
              <Button variant="secondary" size="sm" icon={RefreshCw} disabled={isVerificandoAd} onClick={handleVerificarAd} className="whitespace-nowrap">
                {isVerificandoAd ? 'Consultando AD...' : 'Verificar usuarios contra AD'}
              </Button>
            </div>
            {verificarAdResultado && (
              <div className={`mt-3 p-2.5 rounded-lg text-xs ${verificarAdResultado.ok !== false ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-300 border border-rose-500/20'}`}>
                {verificarAdResultado.ok === false
                  ? verificarAdResultado.mensaje
                  : verificarAdResultado.mensaje || `Consultados ${verificarAdResultado.verificados}, encontrados en AD real: ${verificarAdResultado.encontrados}. Se actualizó el Directorio.`}
              </div>
            )}
          </Card>

          {/* Resumen por motivo */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Object.entries(MOTIVO_LABELS).map(([key, info]) => (
              <Card
                key={key}
                className={`p-4 border-l-4 ${info.confianza === 'alta' ? 'border-rose-500' : 'border-amber-500'}`}
              >
                <div className="text-2xl font-black text-slate-100">{huerfanasData?.resumen?.[key] || 0}</div>
                <div className="text-[11px] text-slate-400 mt-1">{info.label}</div>
              </Card>
            ))}
          </div>

          {/* Filter bar */}
          <Card className="p-4">
            <div className="flex flex-col md:flex-row items-center justify-between gap-3">
              <div className="relative flex-1 w-full">
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={huerfanasSearch}
                  onChange={(e) => setHuerfanasSearch(e.target.value)}
                  placeholder="Buscar por VM/usuario, aplicación, servidor..."
                  className="w-full pl-9 pr-4 py-2 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors"
                />
              </div>
              <select
                value={huerfanasMotivo}
                onChange={(e) => setHuerfanasMotivo(e.target.value)}
                className="px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 w-full md:w-auto"
              >
                <option value="">Todos los motivos</option>
                {Object.entries(MOTIVO_LABELS).map(([key, info]) => (
                  <option key={key} value={key}>{info.label}</option>
                ))}
              </select>
            </div>
          </Card>

          {/* Tabla */}
          <Card>
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <h2 className="text-sm font-bold text-slate-200">Asignaciones Huérfanas</h2>
              <span className="text-xs text-slate-400 font-mono">{huerfanasFiltradas.length} encontradas</span>
            </div>

            {isLoadingHuerfanas ? (
              <div className="py-16 text-center text-xs text-slate-400 animate-pulse">Cruzando asignaciones contra inventario...</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300 border-collapse">
                  <thead className="bg-slate-900/90 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                    <tr>
                      <th className="py-3 px-4">Aplicación / Paquete</th>
                      <th className="py-3 px-4">Tipo</th>
                      <th className="py-3 px-4">Entidad (VM/Usuario)</th>
                      <th className="py-3 px-4">Servidor App Volumes</th>
                      <th className="py-3 px-4">Motivo</th>
                      <th className="py-3 px-4">Última Actualización</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {huerfanasFiltradas.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="py-12 text-center text-xs text-slate-500">
                          {huerfanas.length === 0 ? 'Sin asignaciones huérfanas detectadas — todo limpio.' : 'Ningún registro coincide con el filtro.'}
                        </td>
                      </tr>
                    ) : (
                      huerfanasFiltradas.map((h) => (
                        <tr key={h.id} className="hover:bg-slate-800/40 transition-colors">
                          <td className="py-3 px-4">
                            <div className="font-bold text-slate-100 flex items-center gap-1.5">
                              <Package className="w-3.5 h-3.5 text-emerald-400" />
                              {h.aplicacion_nombre || h.paquete_nombre || '—'}
                            </div>
                          </td>
                          <td className="py-3 px-4">
                            <Badge variant="neutral">{h.entity_type}</Badge>
                          </td>
                          <td className="py-3 px-4 font-mono font-semibold text-slate-100 whitespace-nowrap">{h.entity_name}</td>
                          <td className="py-3 px-4 whitespace-nowrap">
                            <div className="flex items-center gap-1.5">
                              {(h.servidores || []).length === 0 ? (
                                <span className="text-slate-600">—</span>
                              ) : (
                                h.servidores.map((srv) => (
                                  <Badge key={srv} variant="success">{srv}</Badge>
                                ))
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-4 whitespace-nowrap">
                            <Badge variant={h.confianza === 'alta' ? 'danger' : 'warning'}>{h.motivo_label}</Badge>
                          </td>
                          <td className="py-3 px-4 font-mono text-slate-400 whitespace-nowrap">{h.updated_at || '—'}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      ) : activeTab === 'directorio_duplicados' ? (
        <div className="space-y-6">
          <div className="p-3.5 bg-purple-500/10 border border-purple-500/20 rounded-xl text-purple-300 text-xs flex items-start gap-2">
            <Users className="w-4 h-4 mt-0.5 shrink-0 text-purple-400" />
            <span>
              Detecta pares de filas en <strong className="text-purple-200">DirectorioUsuario</strong> que representan a la misma persona real bajo distintas cuentas o formatos de username (confirmados en vivo contra Active Directory por sAMAccountName y Email).
              Al fusionar, los vínculos a máquinas (VMs) de la fila absorbida se re-apuntan a la fila canónica, se completan los datos faltantes y se elimina la fila redundante.
            </span>
          </div>

          {fusionResultado && (
            <div className={`p-3 rounded-xl text-xs flex items-center justify-between ${fusionResultado.ok ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-300 border border-rose-500/20'}`}>
              <span>{fusionResultado.mensaje}</span>
              <button onClick={() => setFusionResultado(null)} className="text-xs opacity-70 hover:opacity-100 ml-2">✕</button>
            </div>
          )}

          <Card>
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <h2 className="text-sm font-bold text-slate-200 flex items-center gap-2">
                <Users className="w-4 h-4 text-purple-400" />
                <span>Duplicados Confirmados por Active Directory</span>
              </h2>
              <span className="text-xs text-slate-400 font-mono">
                {(duplicadosData?.duplicados || []).length} pares confirmados
              </span>
            </div>

            {isLoadingDuplicados ? (
              <div className="py-16 text-center text-xs text-slate-400 animate-pulse flex flex-col items-center justify-center gap-2">
                <RefreshCw className="w-5 h-5 text-purple-400 animate-spin" />
                <span>Filtrando candidatos y verificando contra Active Directory en vivo...</span>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300 border-collapse">
                  <thead className="bg-slate-900/90 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                    <tr>
                      <th className="py-3 px-4">Persona Real / AD</th>
                      <th className="py-3 px-4">Fila Canónica (Conservar)</th>
                      <th className="py-3 px-4">Fila Absorbida (Eliminar)</th>
                      <th className="py-3 px-4">Resumen Fusión</th>
                      <th className="py-3 px-4 text-right">Acción</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {(duplicadosData?.duplicados || []).length === 0 ? (
                      <tr>
                        <td colSpan={5} className="py-12 text-center text-xs text-slate-500">
                          Sin usuarios duplicados confirmados — el directorio está limpio.
                        </td>
                      </tr>
                    ) : (
                      (duplicadosData?.duplicados || []).map((dup) => (
                        <tr key={dup.pair_id} className="hover:bg-slate-800/40 transition-colors">
                          <td className="py-3 px-4">
                            <div className="font-bold text-slate-100">{dup.nombre_persona || '—'}</div>
                            <div className="text-[11px] text-purple-300 font-mono mt-0.5">{dup.ad_email}</div>
                            <div className="text-[10px] text-slate-500 font-mono">SAM: {dup.ad_sam_account_name}</div>
                          </td>
                          <td className="py-3 px-4">
                            <div className="font-mono font-bold text-emerald-400">{dup.canonico.username}</div>
                            <div className="text-[10px] text-slate-400">ID: {dup.canonico.id} • {dup.canonico.vms_count} VMs</div>
                            {dup.canonico.sam_account_name && (
                              <div className="text-[10px] text-slate-500 font-mono">SAM: {dup.canonico.sam_account_name}</div>
                            )}
                          </td>
                          <td className="py-3 px-4">
                            <div className="font-mono font-semibold text-rose-400 line-through opacity-80">{dup.absorbido.username}</div>
                            <div className="text-[10px] text-slate-400">ID: {dup.absorbido.id} • {dup.absorbido.vms_count} VMs</div>
                          </td>
                          <td className="py-3 px-4">
                            <Badge variant="neutral">
                              {dup.resumen}
                            </Badge>
                          </td>
                          <td className="py-3 px-4 text-right">
                            <Button
                              variant="primary"
                              size="sm"
                              disabled={fusionandoPairId === dup.pair_id}
                              onClick={() => handleFusionar(dup.canonico.id, dup.absorbido.id, dup.pair_id)}
                              className="bg-purple-600 hover:bg-purple-500"
                            >
                              {fusionandoPairId === dup.pair_id ? 'Fusionando...' : 'Fusionar'}
                            </Button>
                          </td>
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
      {/* Resumen por Servidores Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {servidores.map((srv) => (
          <Card key={srv.id} className="p-4 border-l-4 border-indigo-500">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="font-bold text-sm text-slate-100">{srv.nombre}</h3>
                <span className="text-[11px] text-slate-400 font-mono uppercase">{srv.origen} • {srv.host}</span>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                {srv.tipo}
              </span>
            </div>
            <div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
              <span className="text-slate-400">VMs en servidor:</span>
              <span className="font-mono font-bold text-slate-200">{srv.total_vms || 0}</span>
            </div>
          </Card>
        ))}
      </div>

      {/* Control & Filter bar */}
      <Card className="p-4">
        <div className="flex flex-col md:flex-row items-center justify-between gap-3">
          <div className="relative flex-1 w-full">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar evento por VM, usuario, servidor, pool..."
              className="w-full pl-9 pr-4 py-2 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>

          <div className="flex items-center gap-2.5 w-full md:w-auto">
            <select
              value={tipoFiltro}
              onChange={(e) => setTipoFiltro(e.target.value)}
              className="px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-indigo-500"
            >
              <option value="">Todos los eventos</option>
              <option value="creacion">🆕 VMs Nuevas / Creadas</option>
              <option value="migracion">🔄 VMs Migradas de Servidor</option>
              <option value="cambio_usuario">👤 Reasignaciones de Usuario</option>
              <option value="cambio_pool">🏊 Cambios / Autorizaciones de Pool</option>
              <option value="cambio_so">💻 Cambios de Sistema Operativo</option>
              <option value="estado_vcenter">⚡ Cambios Energía vCenter</option>
              <option value="cambio_host">⚙️ Cambios Host / Infra</option>
              <option value="snapshot">📸 Actualizaciones Snapshot</option>
              <option value="login">🟢 Inicios de Sesión (Logins)</option>
              <option value="logout">🟡 Cierres de Sesión (Logouts)</option>
              <option value="eliminacion">🔴 VMs Eliminadas / Inactivas</option>
              <option value="alerta_tools">🛑 Alertas VMware Tools</option>
              <option value="alerta_agente">🛑 Alertas Horizon Agent</option>
              <option value="alerta_error">🛑 VM en Error</option>
              <option value="alerta_mantenimiento">🔧 VM en Mantenimiento</option>
              <option value="alerta_disco">💾 Disco Crítico (&gt;90%)</option>
              <option value="alerta_datastore_critico">💾 Datastore Crítico (&gt;90%)</option>
              <option value="alerta_host_desconectado">🖥️ Host ESXi Desconectado</option>
              <option value="alerta_pool_provisioning_error">🛑 Pool con Error de Provisioning</option>
              <option value="alerta_pool_eliminado">🔴 Pool Eliminada</option>
              <option value="seguridad">🔒 Seguridad (bloqueos/login fallido)</option>
              <option value="auditoria">📋 Auditoría Horizon (quién hizo qué)</option>
            </select>

            <select
              value={servidorFiltro}
              onChange={(e) => setServidorFiltro(e.target.value)}
              className="px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-indigo-500"
            >
              <option value="">Todos los Servidores</option>
              {servidores.map((s) => (
                <option key={s.id} value={s.nombre}>{s.nombre}</option>
              ))}
            </select>

            <button
              type="button"
              onClick={() => setVerTodo(!verTodo)}
              title="Incluir cambios rutinarios de infraestructura (ip/dns/host/datastores/...), normalmente ocultos por ruido"
              className={`px-3 py-2 rounded-xl border text-xs font-semibold transition-colors whitespace-nowrap ${
                verTodo
                  ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300'
                  : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {verTodo ? '✓ Viendo todo (con ruido infra)' : 'Ver todo (incl. ruido infra)'}
            </button>
          </div>
        </div>
      </Card>

      {/* Feed Table */}
      <Card>
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h2 className="text-sm font-bold text-slate-200">Feed de Actividad Detallada</h2>
          <span className="text-xs text-slate-400 font-mono">{eventosFiltrados.length} eventos encontrados</span>
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-xs text-slate-400 animate-pulse">Cargando feed de eventos...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300 border-collapse">
              <thead className="bg-slate-900/90 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Fecha / Hora</th>
                  <th className="py-3 px-4">Evento</th>
                  <th className="py-3 px-4">Servidor / Origen</th>
                  <th className="py-3 px-4">Nombre VM</th>
                  <th className="py-3 px-4">Usuario Logueado / Asignado</th>
                  <th className="py-3 px-4">Primera Aparición</th>
                  <th className="py-3 px-4">Clasificación</th>
                  <th className="py-3 px-4">Detalles</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {eventosFiltrados.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-12 text-center text-xs text-slate-500">
                      No se encontraron eventos coincidentes.
                    </td>
                  </tr>
                ) : (
                  eventosFiltrados.map((ev, idx) => (
                    <tr key={idx} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-3 px-4 font-mono text-slate-400 whitespace-nowrap">{ev.fecha}</td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                          {
                            emerald: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30',
                            amber: 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
                            blue: 'bg-blue-500/20 text-blue-300 border border-blue-500/30',
                            purple: 'bg-purple-500/20 text-purple-300 border border-purple-500/30',
                            cyan: 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30',
                            teal: 'bg-teal-500/20 text-teal-300 border border-teal-500/30',
                            sky: 'bg-sky-500/20 text-sky-300 border border-sky-500/30',
                            indigo: 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30',
                            rose: 'bg-rose-500/20 text-rose-300 border border-rose-500/30',
                          }[ev.color] || 'bg-slate-700/30 text-slate-300 border border-slate-600/40'
                        }`}>
                          {ev.badge}
                        </span>
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        <div className="font-bold text-slate-200">{ev.servidor || '—'}</div>
                        <div className="text-[10px] text-slate-500 font-mono uppercase">{ev.origen}</div>
                      </td>
                      <td className="py-3 px-4 font-mono font-semibold text-slate-100 whitespace-nowrap">{ev.nombre_vm}</td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        {ev.usuario && ev.usuario !== '—' ? (
                          <span className="font-medium text-slate-200 flex items-center gap-1">
                            <User className="w-3.5 h-3.5 text-indigo-400" />
                            {ev.usuario}
                          </span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-400 whitespace-nowrap">{ev.primera_deteccion || '—'}</td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        {ev.tipo === 'migracion' ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                            🔄 Migrada de Servidor
                          </span>
                        ) : ev.tipo === 'cambio_host' ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-sky-500/20 text-sky-300 border border-sky-500/30">
                            ⚙️ Cambio vCenter/Host
                          </span>
                        ) : ev.tipo === 'creacion' ? (
                          ev.es_nueva_real ? (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                              🆕 Creada Reciente
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                              ℹ️ Existente Previa
                            </span>
                          )
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-slate-300 text-xs">{ev.detalle}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      </>
      )}
    </div>
  );
}
