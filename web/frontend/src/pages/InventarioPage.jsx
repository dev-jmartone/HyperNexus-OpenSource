import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ExtraerModal } from '../components/modals/ExtraerModal';
import { VmEventsModal, VmEventsView } from '../components/modals/VmEventsModal';
import { VmTimelineView } from '../components/modals/VmTimelineView';
import { VcSessionModal } from '../components/modals/VcSessionModal';
import { SmartFilterToolbar } from '../components/ui/SmartFilterToolbar';
import { toastExito, toastError } from '../utils/alerts';
import { 
  Monitor, 
  Search, 
  ChevronLeft, 
  ChevronRight, 
  Filter, 
  Eye, 
  RefreshCw,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Zap,
  Save,
  CheckCircle,
  X,
  Edit3,
  Copy,
  User,
  Globe,
  FileText,
  History,
  Clock,
  Download,
  Users,
  Activity,
  ExternalLink,
  MessageSquare,
  Plus,
  Trash2,
  Bookmark,
  SlidersHorizontal,
  Package,
  HardDrive
} from 'lucide-react';
import { getTeamsChatUrl, getVmCenterUrl } from '../utils/navigation';
import { acortarSnapshot, formatFechaIngreso } from '../utils/format';

const ALL_COLUMNS = [
  { key: 'tipo', label: 'Tipo' },
  { key: 'tipo_provisionamiento', label: 'Segmentación' },
  { key: 'persistencia', label: 'Persistencia' },
  { key: 'origen', label: 'Origen' },
  { key: 'nombre', label: 'Nombre VM' },
  { key: 'pool', label: 'Pool Horizon' },
  { key: 'empresa', label: 'Empresa' },
  { key: 'usuario_asignado', label: 'Usuario Asignado' },
  { key: 'responsable', label: 'Responsable' },
  { key: 'estado_horizon', label: 'Estado Horizon' },
  { key: 'estado_horizon_agente', label: 'Estado Agente Horizon' },
  { key: 'estado_vcenter', label: 'Estado vCenter' },
  { key: 'tools_status', label: 'VMware Tools' },
  { key: 'estado', label: 'Estado Operacional' },
  { key: 'fecha_ultimo_ingreso', label: 'Fecha Último Ingreso' },
  { key: 'cpu', label: 'CPU' },
  { key: 'ram_gb', label: 'RAM' },
  { key: 'disk_gb', label: 'Disco' },
  { key: 'master_vm_actual', label: 'Master VM' },
  { key: 'snapshot_actual', label: 'Snapshot' },
  { key: 'so', label: 'SO vCenter' },
  { key: 'ip', label: 'IP' },
  { key: 'client_ip', label: 'IP Cliente Horizon' },
  { key: 'client_name', label: 'Equipo Cliente Horizon' },
  { key: 'gateway_name', label: 'Gateway/UAG' },
  { key: 'gateway_ip', label: 'IP Gateway/UAG' },
  { key: 'dns', label: 'DNS' },
  { key: 'vcenter_host', label: 'vCenter Host' },
  { key: 'folder', label: 'Folder' },
  { key: 'resource_pool', label: 'Resource Pool' },
  { key: 'datastores', label: 'Datastores' },
  { key: 'hardware_version', label: 'HW Version' },
  { key: 'connection_state', label: 'Estado Conexión' },
  { key: 'cpu_usage_mhz', label: 'CPU (MHz)' },
  { key: 'memory_usage_mb', label: 'RAM Usada (MB)' },
  { key: 'maintenance_mode', label: 'Modo Mantenimiento' },
  { key: 'in_error_state', label: 'Estado Error' },
  { key: 'annotation', label: 'Anotación' },
];

export function InventarioPage({ globalSearch }) {
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  
  // Legacy exact filters
  const [tipo, setTipo] = useState('');
  const [origen, setOrigen] = useState('');
  const [empresa, setEmpresa] = useState('');
  const [pool, setPool] = useState('');
  const [estadoHorizon, setEstadoHorizon] = useState('');
  const [estadoVCenter, setEstadoVCenter] = useState('');
  const [servidorId, setServidorId] = useState('');

  // Custom Dynamic Multi-Condition Filters
  const [customFilters, setCustomFilters] = useState([]);
  
  // Saved Filter Presets from SQLite DB
  const { data: presetsData, refetch: refetchPresets } = useQuery({
    queryKey: ['filter_presets'],
    queryFn: () => api.get('/filtros/presets'),
  });

  const savedPresets = useMemo(() => {
    return presetsData?.presets || [
      {
        id: 'vdis-desconectadas',
        name: 'VDIs Desconectadas',
        rules: [
          { id: '1', field: 'tipo', operator: 'equals', value: 'VDI' },
          { id: '2', field: 'estado_horizon', operator: 'equals', value: 'DISCONNECTED' }
        ]
      },
      {
        id: 'vms-con-error',
        name: 'VMs en Error / Problem',
        rules: [
          { id: '1', field: 'estado_horizon', operator: 'contains', value: 'ERROR' }
        ]
      }
    ];
  }, [presetsData]);

  const [presetNameInput, setPresetNameInput] = useState('');
  const [isSavePresetModalOpen, setIsSavePresetModalOpen] = useState(false);

  const addCustomFilter = () => {
    setCustomFilters((prev) => [
      ...prev,
      { id: Date.now().toString(), field: 'nombre', operator: 'contains', value: '' }
    ]);
  };

  const removeCustomFilter = (id) => {
    setCustomFilters((prev) => prev.filter((f) => f.id !== id));
  };

  const updateCustomFilter = (id, key, val) => {
    setCustomFilters((prev) =>
      prev.map((f) => (f.id === id ? { ...f, [key]: val } : f))
    );
  };

  const handleSavePresetObj = async (presetObj) => {
    const next = [...savedPresets, presetObj];
    try {
      await api.post('/filtros/presets', { presets: next });
      refetchPresets();
    } catch (e) {}
  };

  const applyPreset = (preset) => {
    setCustomFilters(preset.rules || []);
    if (preset.visibleColumns && Array.isArray(preset.visibleColumns)) {
      // Calculate hidden columns from visible list
      const visibleSet = new Set(preset.visibleColumns);
      const hidden = ALL_COLUMNS.filter((c) => !visibleSet.has(c.key)).map((c) => c.key);
      setHiddenColumns(hidden);
      try {
        localStorage.setItem('inventario_vdi_hidden_columns', JSON.stringify(hidden));
      } catch (e) {}
    }
    setPage(1);
  };

  const deletePreset = async (presetId) => {
    const next = savedPresets.filter((p) => p.id !== presetId);
    try {
      await api.post('/filtros/presets', { presets: next });
      refetchPresets();
    } catch (e) {}
  };

  // Modal "Guardar Vista" (línea ~1765): llamaba a saveCurrentPreset, una función que
  // nunca existió en este archivo -- ReferenceError latente en cuanto alguien clickeara
  // el botón. La lógica real de guardado ya existía (handleSavePresetObj, usada por
  // SmartFilterToolbar); esto arma el mismo objeto de preset a partir del input del modal
  // (código muerto, corregido 2026-09-07).
  const saveCurrentPreset = async () => {
    const name = presetNameInput.trim();
    if (!name) return;
    await handleSavePresetObj({
      id: Date.now().toString(),
      name,
      rules: customFilters,
      visibleColumns: ALL_COLUMNS.filter((c) => isColVisible(c.key)).map((c) => c.key),
    });
    setPresetNameInput('');
    setIsSavePresetModalOpen(false);
  };

  // Column visibility state. Fuente de verdad: DB por usuario (/inventario/columnas) --
  // localStorage queda como caché instantánea para el primer render (antes de que
  // responda el fetch) y como fallback si el usuario no tiene nada guardado todavía.
  const [hiddenColumns, setHiddenColumns] = useState(() => {
    try {
      const saved = localStorage.getItem('inventario_vdi_hidden_columns');
      return saved ? JSON.parse(saved) : [];
    } catch (e) {
      return [];
    }
  });
  const columnasCargadasDeDb = useRef(false);

  const { data: columnasData } = useQuery({
    queryKey: ['inventario_columnas'],
    queryFn: () => api.get('/inventario/columnas'),
  });

  useEffect(() => {
    // Solo aplicar una vez al cargar -- no queremos que un refetch en segundo plano
    // pise los toggles que el usuario está haciendo en la sesión actual.
    if (columnasCargadasDeDb.current) return;
    if (columnasData?.columnas && Array.isArray(columnasData.columnas)) {
      const visibleSet = new Set(columnasData.columnas);
      const hidden = ALL_COLUMNS.filter((c) => !visibleSet.has(c.key)).map((c) => c.key);
      setHiddenColumns(hidden);
      columnasCargadasDeDb.current = true;
    } else if (columnasData) {
      // Respuesta ya llegó pero el usuario no tiene nada guardado -- se queda con
      // localStorage/default, pero marcamos igual para no reprocesar en cada refetch.
      columnasCargadasDeDb.current = true;
    }
  }, [columnasData]);

  const toggleColumnVisibility = (colKey) => {
    setHiddenColumns((prev) => {
      const next = prev.includes(colKey) ? prev.filter((c) => c !== colKey) : [...prev, colKey];
      try {
        localStorage.setItem('inventario_vdi_hidden_columns', JSON.stringify(next));
      } catch (e) {}
      const nextVisible = ALL_COLUMNS.filter((c) => !next.includes(c.key)).map((c) => c.key);
      api.post('/inventario/columnas', { columnas: nextVisible }).catch(() => {});
      return next;
    });
  };

  const isColVisible = (colKey) => !hiddenColumns.includes(colKey);

  const [selectedVm, setSelectedVm] = useState(null);
  const [selectedEventsVm, setSelectedEventsVm] = useState(null);
  const [activeModalTab, setActiveModalTab] = useState('ficha'); // 'ficha' | 'rotacion' | 'deltas'
  const [trazabilidadData, setTrazabilidadData] = useState(null);
  const [isTrazabilidadLoading, setIsTrazabilidadLoading] = useState(false);

  const [editNotas, setEditNotas] = useState('');
  const [editEstado, setEditEstado] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isVcModalOpen, setIsVcModalOpen] = useState(false);

  // Responsable manual (MaquinaUsuarioDir tipo=principal) -- distinto de usuario_asignado
  // (dinamico, viene de sesion Horizon). Pensado para VM_ESTATICA, donde no hay sesion
  // Horizon que diga quien esta usando el equipo.
  const [showResponsablePicker, setShowResponsablePicker] = useState(false);
  const [responsableSearch, setResponsableSearch] = useState('');
  const [responsableResults, setResponsableResults] = useState([]);
  const [isResponsableSearching, setIsResponsableSearching] = useState(false);
  const [isAssigningResponsable, setIsAssigningResponsable] = useState(false);

  const { data: vcStatus, refetch: refetchVcStatus } = useQuery({
    queryKey: ['vc_status'],
    queryFn: () => api.get('/auth/vc_status'),
    refetchInterval: 30000,
  });

  const [isExtraerOpen, setIsExtraerOpen] = useState(false);
  const [isExportingExcel, setIsExportingExcel] = useState(false);

  // Right-Click Context Menu state
  const [contextMenu, setContextMenu] = useState(null);
  const contextMenuRef = useRef(null);

  // Client sorting
  const [sortCol, setSortCol] = useState('nombre');
  const [sortDir, setSortDir] = useState('asc');

  // Fetch servers list for legacy filter
  const { data: servidores } = useQuery({
    queryKey: ['servidores'],
    queryFn: () => api.get('/servidores'),
  });

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['maquinas', page, perPage, tipo, empresa, origen, pool, estadoHorizon, estadoVCenter, servidorId, globalSearch, JSON.stringify(customFilters)],
    queryFn: () => api.get('/maquinas', {
      params: {
        page,
        per_page: perPage,
        tipo: tipo || undefined,
        empresa: empresa || undefined,
        origen: origen || undefined,
        pool: pool || undefined,
        estado_horizon: estadoHorizon || undefined,
        estado_vcenter: estadoVCenter || undefined,
        servidor_id: servidorId || undefined,
        q: globalSearch || undefined,
        custom_filters: customFilters.length > 0 ? JSON.stringify(customFilters) : undefined,
      }
    }),
    keepPreviousData: true,
  });


  // Close context menu on click outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target)) {
        setContextMenu(null);
      }
    };
    window.addEventListener('click', handleClickOutside);
    return () => window.removeEventListener('click', handleClickOutside);
  }, []);

  const handleClearFilters = () => {
    setTipo('');
    setOrigen('');
    setEmpresa('');
    setPool('');
    setEstadoHorizon('');
    setServidorId('');
    setCustomFilters([]);
    setPage(1);
  };

  const handleOpenDetail = async (vm) => {
    setSelectedVm(vm);
    setActiveModalTab('ficha');
    setEditNotas(vm.annotation || '');
    setEditEstado(vm.estado || '');
    setSaveSuccess(false);
    setContextMenu(null);
    setShowResponsablePicker(false);
    setResponsableSearch('');
    setResponsableResults([]);

    // Fetch traceability & rotation logs
    setIsTrazabilidadLoading(true);
    try {
      const res = await api.get(`/maquinas/${vm.id}/trazabilidad`);
      setTrazabilidadData(res);
      setIsTrazabilidadLoading(false);
    } catch (e) {
      setIsTrazabilidadLoading(false);
    }
  };

  const handleContextMenu = (e, vm) => {
    e.preventDefault();
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      vm,
    });
  };

  const handleCopyText = (text) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setContextMenu(null);
  };

  const handleSaveVmDetail = async () => {
    if (!selectedVm) return;

    // Si la anotación cambió y la VM tiene contraparte real en vCenter (external_id),
    // hace falta sesión activa -- si no, ni intentamos: abrimos el modal de credenciales
    // en vez de guardar algo que quedaría solo local sin que el usuario se entere.
    const notasCambiaron = editNotas !== (selectedVm.annotation || '');
    if (notasCambiaron && selectedVm.external_id && !vcStatus?.has_credentials) {
      setIsVcModalOpen(true);
      return;
    }

    try {
      setIsSaving(true);
      const res = await api.post(`/maquinas/${selectedVm.id}/editar`, {
        annotation: editNotas,
        estado: editEstado,
      });
      setIsSaving(false);
      setSaveSuccess(true);
      refetch();
      setTimeout(() => setSaveSuccess(false), 2500);
      if (res?.notas_sync_vcenter === 'error') {
        toastError('Anotación guardada localmente, pero no se pudo sincronizar con vCenter.');
      } else if (res?.notas_sync_vcenter === 'skipped_sin_vinculo') {
        toastError('Anotación guardada localmente. Esta VM todavía no tiene vínculo con vCenter (external_id) — corré una extracción para poder sincronizarla.');
      }
    } catch (e) {
      setIsSaving(false);
      if (e?.response?.data?.requiere_sesion_vcenter) {
        setIsVcModalOpen(true);
      } else {
        toastError(e?.response?.data?.error || 'Error al guardar cambios');
      }
    }
  };

  // Debounce de búsqueda de usuario del directorio para asignar como Responsable.
  useEffect(() => {
    if (!showResponsablePicker || !responsableSearch.trim()) {
      setResponsableResults([]);
      return;
    }
    setIsResponsableSearching(true);
    const timer = setTimeout(async () => {
      try {
        const res = await api.get('/directorio/usuarios', { params: { q: responsableSearch.trim() } });
        setResponsableResults(Array.isArray(res) ? res.slice(0, 10) : []);
      } catch (e) {
        setResponsableResults([]);
      } finally {
        setIsResponsableSearching(false);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [responsableSearch, showResponsablePicker]);

  const handleAssignResponsable = async (usuario) => {
    if (!selectedVm) return;
    try {
      setIsAssigningResponsable(true);
      if (selectedVm.responsable_vinculo_id) {
        await api.post(`/directorio/desvincular/${selectedVm.responsable_vinculo_id}`);
      }
      await api.post('/directorio/vincular', {
        maquina_id: selectedVm.id,
        directorio_usuario_id: usuario.id,
        tipo: 'principal',
      });
      setSelectedVm({
        ...selectedVm,
        responsable: usuario.nombre_completo || usuario.username,
        responsable_username: usuario.username,
        responsable_email: usuario.email,
      });
      setShowResponsablePicker(false);
      setResponsableSearch('');
      setResponsableResults([]);
      refetch();
      toastExito(`Responsable asignado: ${usuario.nombre_completo || usuario.username}`);
    } catch (e) {
      toastError(e?.response?.data?.error || 'Error al asignar responsable');
    } finally {
      setIsAssigningResponsable(false);
    }
  };

  const handleRemoveResponsable = async () => {
    if (!selectedVm?.responsable_vinculo_id) return;
    try {
      setIsAssigningResponsable(true);
      await api.post(`/directorio/desvincular/${selectedVm.responsable_vinculo_id}`);
      setSelectedVm({ ...selectedVm, responsable: '', responsable_vinculo_id: null, responsable_username: '', responsable_email: '' });
      refetch();
    } catch (e) {
      toastError('Error al quitar responsable');
    } finally {
      setIsAssigningResponsable(false);
    }
  };

  const handleExportExcel = async () => {
    try {
      setIsExportingExcel(true);
      const res = await api.post('/reportes/generar', {
        tipo, origen, servidor_id: servidorId
      });
      setIsExportingExcel(false);
      if (res.download_url) {
        const link = document.createElement('a');
        link.href = res.download_url;
        link.setAttribute('download', res.filename || 'reporte.xlsx');
        document.body.appendChild(link);
        link.click();
        link.remove();
      }
    } catch (e) {
      setIsExportingExcel(false);
      toastError('Error al generar Excel: ' + (e?.response?.data?.error || e.message));
    }
  };

  const handleSort = (colKey) => {
    if (sortCol === colKey) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(colKey);
      setSortDir('asc');
    }
  };

  const filteredAndSortedItems = useMemo(() => {
    if (!data?.items) return [];
    // El filtrado real (pool/estado/servidor/custom_filters, incluido el campo virtual
    // 'segmentacion') ya lo hace el backend en /api/maquinas -- acá solo se ordena.
    // Bug real encontrado 2026-09-04 (5ta vuelta de la auditoría de filtros): había un
    // SEGUNDO filtro acá, del lado del cliente, que volvía a re-filtrar `data.items` ya
    // filtrados por el backend. No conocía los campos virtuales nuevos (segmentacion no
    // viene como key en el dict de la fila) ni los booleanos/enums agregados después --
    // filtraba por sustring sobre '' y tiraba TODAS las filas, aunque el backend ya
    // hubiera traído las correctas. Doble filtrado = doble lugar para desincronizarse,
    // igual que categoria_estatica/tipo_provisionamiento antes de unificarse.
    const items = [...data.items];

    return items.sort((a, b) => {
      let valA = a[sortCol] ?? '';
      let valB = b[sortCol] ?? '';
      if (typeof valA === 'string') valA = valA.toLowerCase();
      if (typeof valB === 'string') valB = valB.toLowerCase();

      if (valA < valB) return sortDir === 'asc' ? -1 : 1;
      if (valA > valB) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [data?.items, sortCol, sortDir]);

  const getStatusBadge = (status, user) => {
    const s = (status || '').toUpperCase();
    if (s.includes('N/A') || s.includes('VCENTER')) {
      return (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800/80 text-slate-400 border border-slate-700/80 whitespace-nowrap">
          vCenter
        </span>
      );
    }
    if (s === 'CONNECTED') return <Badge variant="success">CONNECTED</Badge>;
    if (s === 'DISCONNECTED') return <Badge variant="warning">DISCONNECTED</Badge>;
    if (s === 'AVAILABLE' && !user) {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 whitespace-nowrap">
          <span>AVAILABLE</span>
          <span className="text-[9px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold">HUÉRFANA</span>
        </span>
      );
    }
    if (s === 'AVAILABLE') return <Badge variant="info">AVAILABLE</Badge>;
    if (s.includes('ERROR') || s.includes('UNREACHABLE') || s.includes('PROBLEM')) {
      return <Badge variant="danger">{s}</Badge>;
    }
    return <Badge variant="neutral">{s || '—'}</Badge>;
  };

  const getSegmentacionBadge = (tp, categoriaEstatica) => {
    if (tp === 'VM_ESTATICA' && categoriaEstatica === 'Infraestructura Interna') {
      return <Badge variant="neutral" className="whitespace-nowrap" title="Agente/artefacto interno de vSphere u Horizon (vCLS, VM intermedia de Instant Clone) -- no es inventario de usuario/negocio">INFRA INTERNA</Badge>;
    }
    if (tp === 'VM_ESTATICA' && categoriaEstatica === 'RPA') {
      return <Badge variant="info">RPA</Badge>;
    }
    if (tp === 'VM_ESTATICA' && categoriaEstatica === 'Copia (no activa)') {
      return <Badge variant="warning" className="whitespace-nowrap">COPIA (VIEJA)</Badge>;
    }
    if (tp === 'VM_ESTATICA' && categoriaEstatica === 'VDI Huérfana (sin pool Horizon)') {
      return <Badge variant="danger" className="whitespace-nowrap" title="Nombre de VDI pero Horizon no tiene ningún registro con ese nombre -- resto de vCenter de una pool vieja">VDI HUÉRFANA</Badge>;
    }
    switch (tp) {
      case 'MASTER':
        return <Badge variant="purple">MASTER</Badge>;
      case 'TEMPLATE':
        return <Badge variant="info">PLANTILLA</Badge>;
      case 'VDI_POOL':
        return <Badge variant="success">VDI POOL</Badge>;
      case 'VM_ESTATICA':
        return <Badge variant="neutral">ESTÁTICA</Badge>;
      default:
        return <span className="text-slate-600">—</span>;
    }
  };

  const getPersistenciaBadge = (p) => {
    switch (p) {
      case 'Persistente':
        return <Badge variant="success">PERSISTENTE</Badge>;
      case 'No Persistente':
        return <Badge variant="warning">NO PERSISTENTE</Badge>;
      case 'N/A (Estática)':
        return <Badge variant="neutral">N/A</Badge>;
      default:
        return <span className="text-slate-600">—</span>;
    }
  };

  const renderSortIcon = (colKey) => {
    if (sortCol !== colKey) return <ArrowUpDown className="w-3 h-3 inline ml-1 text-slate-600" />;
    return sortDir === 'asc' 
      ? <ArrowUp className="w-3 h-3 inline ml-1 text-indigo-400" />
      : <ArrowDown className="w-3 h-3 inline ml-1 text-indigo-400" />;
  };

  return (
    <div className="space-y-6">
      {/* Smart Faceted Filter & Views Toolbar */}
      <SmartFilterToolbar
        allColumns={ALL_COLUMNS}
        activeRules={customFilters}
        onRulesChange={(rules) => { setCustomFilters(rules); setPage(1); }}
        savedPresets={savedPresets}
        onSavePreset={handleSavePresetObj}
        onDeletePreset={deletePreset}
        onApplyPreset={applyPreset}
        visibleColumns={ALL_COLUMNS.filter((c) => isColVisible(c.key)).map((c) => c.key)}
        onRestoreColumns={(cols) => {
          const visibleSet = new Set(cols);
          const hidden = ALL_COLUMNS.filter((c) => !visibleSet.has(c.key)).map((c) => c.key);
          setHiddenColumns(hidden);
        }}
        onToggleColumn={toggleColumnVisibility}
        servidores={servidores}
      />



      {/* Main Table with row click and right-click context menu */}
      <Card className="relative z-10">
        {isLoading ? (
          <div className="py-24 text-center text-slate-400 animate-pulse">Cargando inventario completo...</div>
        ) : (
          <div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300 border-collapse">
                <thead className="bg-slate-900/90 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800 select-none">
                  <tr>
                    {isColVisible('tipo') && (
                      <th onClick={() => handleSort('tipo')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Tipo {renderSortIcon('tipo')}
                      </th>
                    )}
                    {isColVisible('tipo_provisionamiento') && (
                      <th onClick={() => handleSort('tipo_provisionamiento')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Segmentación {renderSortIcon('tipo_provisionamiento')}
                      </th>
                    )}
                    {isColVisible('persistencia') && (
                      <th onClick={() => handleSort('persistencia')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Persistencia {renderSortIcon('persistencia')}
                      </th>
                    )}
                    {isColVisible('origen') && (
                      <th onClick={() => handleSort('origen')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Origen {renderSortIcon('origen')}
                      </th>
                    )}
                    {isColVisible('nombre') && (
                      <th onClick={() => handleSort('nombre')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Nombre VM {renderSortIcon('nombre')}
                      </th>
                    )}
                    {isColVisible('pool') && (
                      <th onClick={() => handleSort('pool')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Pool Horizon {renderSortIcon('pool')}
                      </th>
                    )}
                    {isColVisible('empresa') && (
                      <th onClick={() => handleSort('empresa')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Empresa {renderSortIcon('empresa')}
                      </th>
                    )}
                    {isColVisible('usuario_asignado') && (
                      <th onClick={() => handleSort('usuario_asignado')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Usuario Asignado {renderSortIcon('usuario_asignado')}
                      </th>
                    )}
                    {isColVisible('responsable') && (
                      <th onClick={() => handleSort('responsable')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Responsable {renderSortIcon('responsable')}
                      </th>
                    )}
                    {isColVisible('estado_horizon') && (
                      <th onClick={() => handleSort('estado_horizon')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Estado Horizon {renderSortIcon('estado_horizon')}
                      </th>
                    )}
                    {isColVisible('estado_horizon_agente') && (
                      <th onClick={() => handleSort('estado_horizon_agente')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Estado Agente Horizon {renderSortIcon('estado_horizon_agente')}
                      </th>
                    )}
                    {isColVisible('estado_vcenter') && (
                      <th onClick={() => handleSort('estado_vcenter')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Estado vCenter {renderSortIcon('estado_vcenter')}
                      </th>
                    )}
                    {isColVisible('tools_status') && (
                      <th onClick={() => handleSort('tools_status')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        VMware Tools {renderSortIcon('tools_status')}
                      </th>
                    )}
                    {isColVisible('estado') && (
                      <th onClick={() => handleSort('estado')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Estado Operacional {renderSortIcon('estado')}
                      </th>
                    )}
                    {isColVisible('fecha_ultimo_ingreso') && (
                      <th onClick={() => handleSort('fecha_ultimo_ingreso')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Fecha Último Ingreso {renderSortIcon('fecha_ultimo_ingreso')}
                      </th>
                    )}
                    {isColVisible('cpu') && (
                      <th onClick={() => handleSort('cpu')} className="py-3 px-3 cursor-pointer hover:text-indigo-400 text-center">
                        CPU {renderSortIcon('cpu')}
                      </th>
                    )}
                    {isColVisible('ram_gb') && (
                      <th onClick={() => handleSort('ram_gb')} className="py-3 px-3 cursor-pointer hover:text-indigo-400 text-center">
                        RAM (GB) {renderSortIcon('ram_gb')}
                      </th>
                    )}
                    {isColVisible('disk_gb') && (
                      <th onClick={() => handleSort('disk_gb')} className="py-3 px-3 cursor-pointer hover:text-indigo-400 text-center">
                        Disco (GB) {renderSortIcon('disk_gb')}
                      </th>
                    )}
                    {isColVisible('master_vm_actual') && (
                      <th className="py-3 px-3">Master VM</th>
                    )}
                    {isColVisible('snapshot_actual') && (
                      <th className="py-3 px-3">Snapshot</th>
                    )}
                    {isColVisible('so') && (
                      <th onClick={() => handleSort('so')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        SO vCenter {renderSortIcon('so')}
                      </th>
                    )}
                    {isColVisible('ip') && (
                      <th onClick={() => handleSort('ip')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        IP {renderSortIcon('ip')}
                      </th>
                    )}
                    {isColVisible('client_ip') && (
                      <th className="py-3 px-3" title="IP del cliente Horizon en la última sesión conocida">IP Cliente</th>
                    )}
                    {isColVisible('client_name') && (
                      <th className="py-3 px-3" title="Equipo cliente Horizon en la última sesión conocida">Equipo Cliente</th>
                    )}
                    {isColVisible('gateway_name') && (
                      <th className="py-3 px-3" title="Gateway/UAG que atendió la última sesión conocida">Gateway/UAG</th>
                    )}
                    {isColVisible('gateway_ip') && (
                      <th className="py-3 px-3" title="IP del Gateway/UAG en la última sesión conocida">IP Gateway</th>
                    )}
                    {isColVisible('dns') && (
                      <th onClick={() => handleSort('dns')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        DNS {renderSortIcon('dns')}
                      </th>
                    )}
                    {isColVisible('vcenter_host') && (
                      <th onClick={() => handleSort('vcenter_host')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        vCenter Host {renderSortIcon('vcenter_host')}
                      </th>
                    )}
                    {isColVisible('folder') && (
                      <th onClick={() => handleSort('folder')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Folder {renderSortIcon('folder')}
                      </th>
                    )}
                    {isColVisible('resource_pool') && (
                      <th onClick={() => handleSort('resource_pool')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Resource Pool {renderSortIcon('resource_pool')}
                      </th>
                    )}
                    {isColVisible('datastores') && (
                      <th onClick={() => handleSort('datastores')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Datastores {renderSortIcon('datastores')}
                      </th>
                    )}
                    {isColVisible('hardware_version') && (
                      <th onClick={() => handleSort('hardware_version')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        HW Version {renderSortIcon('hardware_version')}
                      </th>
                    )}
                    {isColVisible('connection_state') && (
                      <th onClick={() => handleSort('connection_state')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Conexión {renderSortIcon('connection_state')}
                      </th>
                    )}
                    {isColVisible('cpu_usage_mhz') && (
                      <th onClick={() => handleSort('cpu_usage_mhz')} className="py-3 px-3 cursor-pointer hover:text-indigo-400 text-center">
                        CPU MHz {renderSortIcon('cpu_usage_mhz')}
                      </th>
                    )}
                    {isColVisible('memory_usage_mb') && (
                      <th onClick={() => handleSort('memory_usage_mb')} className="py-3 px-3 cursor-pointer hover:text-indigo-400 text-center">
                        RAM MB {renderSortIcon('memory_usage_mb')}
                      </th>
                    )}
                    {isColVisible('maintenance_mode') && (
                      <th onClick={() => handleSort('maintenance_mode')} className="py-3 px-3 cursor-pointer hover:text-indigo-400 text-center">
                        Mantenimiento {renderSortIcon('maintenance_mode')}
                      </th>
                    )}
                    {isColVisible('in_error_state') && (
                      <th onClick={() => handleSort('in_error_state')} className="py-3 px-3 cursor-pointer hover:text-indigo-400 text-center">
                        Estado Error {renderSortIcon('in_error_state')}
                      </th>
                    )}
                    {isColVisible('annotation') && (
                      <th onClick={() => handleSort('annotation')} className="py-3 px-3 cursor-pointer hover:text-indigo-400">
                        Anotación {renderSortIcon('annotation')}
                      </th>
                    )}
                    <th className="py-3 px-3 text-center">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredAndSortedItems.length === 0 ? (
                    <tr>
                      <td colSpan={ALL_COLUMNS.filter((c) => isColVisible(c.key)).length + 1} className="py-8 text-center text-slate-500">No se encontraron registros con los filtros actuales.</td>
                    </tr>
                  ) : (
                    filteredAndSortedItems.map((m) => (
                      <tr 
                        key={m.id} 
                        onClick={() => handleOpenDetail(m)}
                        onContextMenu={(e) => handleContextMenu(e, m)}
                        className="hover:bg-slate-800/60 transition-colors cursor-pointer select-none"
                      >
                        {isColVisible('tipo') && (
                          <td className="py-2.5 px-3">
                            <Badge variant={m.tipo === 'VDI' ? 'info' : 'neutral'}>{m.tipo}</Badge>
                          </td>
                        )}
                        {isColVisible('tipo_provisionamiento') && (
                          <td className="py-2.5 px-3">
                            {getSegmentacionBadge(m.tipo_provisionamiento, m.categoria_estatica)}
                          </td>
                        )}
                        {isColVisible('persistencia') && (
                          <td className="py-2.5 px-3">
                            {getPersistenciaBadge(m.persistencia)}
                          </td>
                        )}
                        {isColVisible('origen') && (
                          <td className="py-2.5 px-3 font-mono font-medium text-indigo-400 uppercase">
                            {m.origen || '—'}
                          </td>
                        )}
                        {isColVisible('nombre') && (
                          <td className="py-2.5 px-3 font-mono font-semibold text-slate-100 whitespace-nowrap">
                            <a
                              href={getVmCenterUrl(m)}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="hover:text-indigo-400 hover:underline flex items-center group"
                              title="Abrir máquina en vCenter / Horizon Web UI"
                            >
                              <Monitor className="w-3.5 h-3.5 mr-1.5 text-indigo-400 shrink-0 group-hover:scale-110 transition-transform" />
                              <span>{m.nombre}</span>
                              <ExternalLink className="w-3 h-3 ml-1 text-slate-500 group-hover:text-indigo-400 inline" />
                            </a>
                          </td>
                        )}
                        {isColVisible('pool') && (
                          <td className="py-2.5 px-3 text-slate-300 whitespace-nowrap">{m.pool || '—'}</td>
                        )}
                        {isColVisible('empresa') && (
                          <td className="py-2.5 px-3 text-slate-300 whitespace-nowrap">{m.empresa || '—'}</td>
                        )}
                        {isColVisible('usuario_asignado') && (
                          <td className="py-2.5 px-3 font-medium text-slate-200 whitespace-nowrap">
                            {getTeamsChatUrl(m.usuario_asignado) ? (
                              <a
                                href={getTeamsChatUrl(m.usuario_asignado)}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="hover:text-indigo-400 hover:underline inline-flex items-center space-x-1 group"
                                title="Iniciar Chat en Microsoft Teams"
                              >
                                <span>{m.usuario_asignado}</span>
                                <span className="text-[10px] px-1 py-0.2 rounded bg-indigo-500/20 text-indigo-300 group-hover:bg-indigo-500 group-hover:text-white transition-colors">
                                  💬 Teams
                                </span>
                              </a>
                            ) : (
                              <span className="text-slate-500 italic">{m.usuario_asignado || 'Sin asignar'}</span>
                            )}
                          </td>
                        )}
                        {isColVisible('responsable') && (
                          <td className="py-2.5 px-3 text-slate-300 whitespace-nowrap">
                            {m.responsable ? (
                              getTeamsChatUrl({ username: m.responsable_username, email: m.responsable_email }) ? (
                                <a
                                  href={getTeamsChatUrl({ username: m.responsable_username, email: m.responsable_email })}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  className="hover:text-indigo-400 hover:underline inline-flex items-center space-x-1 group"
                                  title="Iniciar Chat en Microsoft Teams"
                                >
                                  <span>{m.responsable}</span>
                                  <span className="text-[10px] px-1 py-0.2 rounded bg-indigo-500/20 text-indigo-300 group-hover:bg-indigo-500 group-hover:text-white transition-colors">
                                    💬 Teams
                                  </span>
                                </a>
                              ) : (
                                <span>{m.responsable}</span>
                              )
                            ) : (
                              <span className="text-slate-500 italic">Sin responsable</span>
                            )}
                          </td>
                        )}
                        {isColVisible('estado_horizon') && (
                          <td className="py-2.5 px-3">{getStatusBadge(m.estado_horizon, m.usuario_asignado)}</td>
                        )}
                        {isColVisible('estado_horizon_agente') && (
                          <td className="py-2.5 px-3 text-slate-400 font-mono text-[11px] whitespace-nowrap">{m.estado_horizon_agente || '—'}</td>
                        )}
                        {isColVisible('estado_vcenter') && (
                          <td className="py-2.5 px-3 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${
                              (m.estado_vcenter || '').toLowerCase().includes('poweredon') ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' :
                              (m.estado_vcenter || '').toLowerCase().includes('poweredoff') ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' :
                              'bg-slate-800 text-slate-400 border border-slate-700'
                            }`}>
                              {m.estado_vcenter || '—'}
                            </span>
                          </td>
                        )}
                        {isColVisible('tools_status') && (
                          <td className="py-2.5 px-3 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${
                              (m.tools_status || '').toUpperCase() === 'RUNNING' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' :
                              m.tools_status ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' :
                              'bg-slate-800 text-slate-400 border border-slate-700'
                            }`}>
                              {m.tools_status || '—'}
                            </span>
                          </td>
                        )}
                        {isColVisible('estado') && (
                          <td className="py-2.5 px-3 text-slate-300 whitespace-nowrap">
                            {m.estado || <span className="text-slate-600">—</span>}
                          </td>
                        )}
                        {isColVisible('fecha_ultimo_ingreso') && (
                          <td className="py-2.5 px-3 text-slate-400 text-xs whitespace-nowrap">
                            {formatFechaIngreso(m.fecha_ultimo_ingreso) || <span className="text-slate-600">—</span>}
                          </td>
                        )}
                        
                        {isColVisible('cpu') && (
                          <td className="py-2.5 px-3 text-center font-mono font-bold text-slate-200">
                            {m.cpu ? `${m.cpu} vCPU` : '—'}
                          </td>
                        )}
                        {isColVisible('ram_gb') && (
                          <td className="py-2.5 px-3 text-center font-mono font-bold text-slate-200">
                            {m.ram_gb ? `${m.ram_gb} GB` : '—'}
                          </td>
                        )}
                        {isColVisible('disk_gb') && (
                          <td className="py-2.5 px-3 text-center font-mono font-bold text-slate-200">
                            {m.disk_gb ? `${m.disk_gb} GB` : '—'}
                          </td>
                        )}

                        {isColVisible('master_vm_actual') && (
                          <td className="py-2.5 px-3 font-mono text-slate-300 text-xs truncate max-w-[140px]" title={m.master_vm_actual}>
                            {m.master_vm_actual || <span className="text-slate-600">—</span>}
                          </td>
                        )}
                        {isColVisible('snapshot_actual') && (
                          <td className="py-2.5 px-3 font-mono text-slate-300 text-xs truncate max-w-[140px]" title={m.snapshot_actual}>
                            {m.snapshot_actual ? acortarSnapshot(m.snapshot_actual) : <span className="text-slate-600">—</span>}
                          </td>
                        )}
                        {isColVisible('so') && (
                          <td className="py-2.5 px-3 text-slate-400 truncate max-w-[120px]" title={m.so}>
                            {m.so || '—'}
                          </td>
                        )}
                        {isColVisible('ip') && (
                          <td className="py-2.5 px-3 font-mono text-slate-300 whitespace-nowrap">{m.ip || '—'}</td>
                        )}
                        {isColVisible('client_ip') && (
                          <td className="py-2.5 px-3 font-mono text-slate-400 text-xs whitespace-nowrap">{m.client_ip || '—'}</td>
                        )}
                        {isColVisible('client_name') && (
                          <td className="py-2.5 px-3 font-mono text-slate-400 text-xs whitespace-nowrap">{m.client_name || '—'}</td>
                        )}
                        {isColVisible('gateway_name') && (
                          <td className="py-2.5 px-3 font-mono text-slate-400 text-xs whitespace-nowrap">{m.gateway_name || '—'}</td>
                        )}
                        {isColVisible('gateway_ip') && (
                          <td className="py-2.5 px-3 font-mono text-slate-400 text-xs whitespace-nowrap">{m.gateway_ip || '—'}</td>
                        )}
                        {isColVisible('dns') && (
                          <td className="py-2.5 px-3 font-mono text-slate-400 truncate max-w-[120px]" title={m.dns}>
                            {m.dns || '—'}
                          </td>
                        )}
                        {isColVisible('vcenter_host') && (
                          <td className="py-2.5 px-3 text-slate-400 font-mono text-[11px] whitespace-nowrap">{m.vcenter_host || '—'}</td>
                        )}
                        {isColVisible('folder') && (
                          <td className="py-2.5 px-3 text-slate-300 text-xs whitespace-nowrap">{m.folder || '—'}</td>
                        )}
                        {isColVisible('resource_pool') && (
                          <td className="py-2.5 px-3 text-slate-300 text-xs whitespace-nowrap">{m.resource_pool || '—'}</td>
                        )}
                        {isColVisible('datastores') && (
                          <td className="py-2.5 px-3 text-slate-400 text-xs truncate max-w-[150px]" title={m.datastores}>{m.datastores || '—'}</td>
                        )}
                        {isColVisible('hardware_version') && (
                          <td className="py-2.5 px-3 text-slate-400 font-mono text-xs whitespace-nowrap">{m.hardware_version || '—'}</td>
                        )}
                        {isColVisible('connection_state') && (
                          <td className="py-2.5 px-3 text-slate-300 text-xs whitespace-nowrap">{m.connection_state || '—'}</td>
                        )}
                        {isColVisible('cpu_usage_mhz') && (
                          <td className="py-2.5 px-3 text-center font-mono text-slate-300">{m.cpu_usage_mhz ? `${m.cpu_usage_mhz} MHz` : '—'}</td>
                        )}
                        {isColVisible('memory_usage_mb') && (
                          <td className="py-2.5 px-3 text-center font-mono text-slate-300">{m.memory_usage_mb ? `${m.memory_usage_mb} MB` : '—'}</td>
                        )}
                        {isColVisible('maintenance_mode') && (
                          <td className="py-2.5 px-3 text-center">
                            {m.maintenance_mode ? (
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">MANT</span>
                            ) : (
                              <span className="text-slate-600 text-[11px]">NO</span>
                            )}
                          </td>
                        )}
                        {isColVisible('in_error_state') && (
                          <td className="py-2.5 px-3 text-center">
                            {m.in_error_state ? (
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">ERROR</span>
                            ) : (
                              <span className="text-slate-600 text-[11px]">OK</span>
                            )}
                          </td>
                        )}
                        {isColVisible('annotation') && (
                          <td className="py-2.5 px-3 text-slate-400 text-xs truncate max-w-[200px]" title={m.annotation}>{m.annotation || '—'}</td>
                        )}

                        <td className="py-2.5 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-center space-x-1">
                            <button
                              onClick={() => handleOpenDetail(m)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-400 hover:bg-slate-800 transition-colors"
                              title="Ver Ficha / Trazabilidad"
                            >
                              <Eye className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleOpenDetail(m)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-amber-400 hover:bg-slate-800 transition-colors"
                              title="Editar Anotación y Estado"
                            >
                              <Edit3 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
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

      {/* Floating Right-Click Context Menu */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          style={{ top: `${contextMenu.y}px`, left: `${contextMenu.x}px` }}
          className="fixed z-50 bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-1.5 w-60 text-xs text-slate-200 animate-fade-in divide-y divide-slate-800"
        >
          <div className="px-3 py-1.5 font-bold font-mono text-indigo-400 truncate border-b border-slate-800 flex items-center">
            <Monitor className="w-3.5 h-3.5 mr-1.5 shrink-0" />
            {contextMenu.vm.nombre}
          </div>

          <div className="py-1">
            <a
              href={getVmCenterUrl(contextMenu.vm)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setContextMenu(null)}
              className="w-full text-left px-3 py-1.5 hover:bg-slate-800 rounded-lg flex items-center space-x-2 text-indigo-300 font-semibold transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5 text-indigo-400" />
              <span>Abrir VM en vCenter / Horizon</span>
            </a>
            {getTeamsChatUrl(contextMenu.vm.usuario_asignado) && (
              <a
                href={getTeamsChatUrl(contextMenu.vm.usuario_asignado)}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setContextMenu(null)}
                className="w-full text-left px-3 py-1.5 hover:bg-slate-800 rounded-lg flex items-center space-x-2 text-indigo-300 font-semibold transition-colors"
              >
                <MessageSquare className="w-3.5 h-3.5 text-indigo-400" />
                <span>Chat Teams ({contextMenu.vm.usuario_asignado})</span>
              </a>
            )}
          </div>

          <div className="py-1">
            <button
              onClick={() => {
                setSelectedEventsVm(contextMenu.vm);
                setContextMenu(null);
              }}
              className="w-full text-left px-3 py-1.5 hover:bg-slate-800 rounded-lg flex items-center space-x-2 text-cyan-300 font-semibold transition-colors"
            >
              <Activity className="w-3.5 h-3.5 text-cyan-400" />
              <span>📋 Tareas / Eventos vCenter (Supervisar)</span>
            </button>
            <button
              onClick={() => handleOpenDetail(contextMenu.vm)}
              className="w-full text-left px-3 py-1.5 hover:bg-slate-800 rounded-lg flex items-center space-x-2 text-slate-200 transition-colors"
            >
              <Eye className="w-3.5 h-3.5 text-indigo-400" />
              <span>Ver Ficha Técnica & Trazabilidad</span>
            </button>
            <button
              onClick={() => handleOpenDetail(contextMenu.vm)}
              className="w-full text-left px-3 py-1.5 hover:bg-slate-800 rounded-lg flex items-center space-x-2 text-slate-200 transition-colors"
            >
              <Edit3 className="w-3.5 h-3.5 text-amber-400" />
              <span>Editar Anotación y Estado</span>
            </button>
          </div>

          <div className="py-1">
            <button
              onClick={() => handleCopyText(contextMenu.vm.nombre)}
              className="w-full text-left px-3 py-1.5 hover:bg-slate-800 rounded-lg flex items-center space-x-2 text-slate-300 transition-colors"
            >
              <Copy className="w-3.5 h-3.5 text-slate-400" />
              <span>Copiar Nombre VM</span>
            </button>
            {contextMenu.vm.ip && (
              <button
                onClick={() => handleCopyText(contextMenu.vm.ip)}
                className="w-full text-left px-3 py-1.5 hover:bg-slate-800 rounded-lg flex items-center space-x-2 text-slate-300 transition-colors"
              >
                <Globe className="w-3.5 h-3.5 text-slate-400" />
                <span>Copiar IP ({contextMenu.vm.ip})</span>
              </button>
            )}
            {contextMenu.vm.usuario_asignado && (
              <button
                onClick={() => handleCopyText(contextMenu.vm.usuario_asignado)}
                className="w-full text-left px-3 py-1.5 hover:bg-slate-800 rounded-lg flex items-center space-x-2 text-slate-300 transition-colors"
              >
                <User className="w-3.5 h-3.5 text-slate-400" />
                <span>Copiar Usuario</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* VM Full Detail & Traceability Modal with 3 Tabs */}
      {selectedVm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/85 backdrop-blur-md animate-fade-in">
          <div className="w-full max-w-3xl glass-panel p-6 rounded-2xl border border-slate-800 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-lg font-bold text-slate-100 flex items-center">
                  <Monitor className="w-5 h-5 mr-2 text-indigo-400" />
                  {selectedVm.nombre}
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">Ficha Técnica & Historial de Trazabilidad</p>
              </div>
              <button 
                onClick={() => setSelectedVm(null)}
                className="text-slate-400 hover:text-slate-200 text-xl font-bold p-1"
              >
                ×
              </button>
            </div>

            {/* Modal Navigation Tabs */}
            <div className="flex items-center space-x-2 border-b border-slate-800 pb-2">
              <button
                onClick={() => setActiveModalTab('ficha')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center space-x-1.5 ${
                  activeModalTab === 'ficha'
                    ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                }`}
              >
                <FileText className="w-3.5 h-3.5" />
                <span>Ficha Técnica & Edición</span>
              </button>

              <button
                onClick={() => setActiveModalTab('rotacion')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center space-x-1.5 ${
                  activeModalTab === 'rotacion'
                    ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                }`}
              >
                <History className="w-3.5 h-3.5" />
                <span>Trazabilidad de Usuarios ({trazabilidadData?.rotaciones?.length || 0})</span>
              </button>

              <button
                onClick={() => setActiveModalTab('deltas')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center space-x-1.5 ${
                  activeModalTab === 'deltas'
                    ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                }`}
              >
                <Activity className="w-3.5 h-3.5" />
                <span>Timeline & Cambios ({trazabilidadData?.cambios?.length || 0})</span>
              </button>

              <button
                onClick={() => setActiveModalTab('eventos')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center space-x-1.5 ${
                  activeModalTab === 'eventos'
                    ? 'bg-cyan-600 text-white shadow-md shadow-cyan-600/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                }`}
              >
                <Activity className="w-3.5 h-3.5 text-cyan-400" />
                <span>📋 Supervisar (Tareas & Eventos vCenter)</span>
              </button>

              <button
                onClick={() => setActiveModalTab('appvolumes')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center space-x-1.5 ${
                  activeModalTab === 'appvolumes'
                    ? 'bg-emerald-600 text-white shadow-md shadow-emerald-600/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                }`}
              >
                <Package className="w-3.5 h-3.5 text-emerald-400" />
                <span>App Volumes ({trazabilidadData?.appvolumes_apps?.length || 0})</span>
              </button>

              <button
                onClick={() => setActiveModalTab('imagen_pool')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center space-x-1.5 ${
                  activeModalTab === 'imagen_pool'
                    ? 'bg-purple-600 text-white shadow-md shadow-purple-600/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                }`}
              >
                <History className="w-3.5 h-3.5 text-purple-400" />
                <span>Imagen / Pool ({trazabilidadData?.eventos_horizon?.length || 0})</span>
              </button>
            </div>

            {/* TAB 1: Ficha Técnica & Edición */}
            {activeModalTab === 'ficha' && (
              <div className="space-y-4">
                {saveSuccess && (
                  <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-xs font-semibold flex items-center">
                    <CheckCircle className="w-4 h-4 mr-2" /> Cambios guardados con éxito en la base de datos!
                  </div>
                )}

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Tipo</div>
                    <div className="font-bold text-slate-200 mt-1">{selectedVm.tipo}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Origen / Código</div>
                    <div className="font-bold text-indigo-400 mt-1 uppercase">{selectedVm.origen || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Pool Horizon</div>
                    <div className="font-bold text-slate-200 mt-1">{selectedVm.pool || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Persistencia</div>
                    <div className="mt-1">{getPersistenciaBadge(selectedVm.persistencia)}</div>
                  </div>

                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Usuario Asignado</div>
                    <div className="font-bold text-slate-100 mt-1">{selectedVm.usuario_asignado || 'Sin asignar'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Empresa</div>
                    <div className="font-bold text-slate-200 mt-1">{selectedVm.empresa || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Estado Horizon</div>
                    <div className="font-bold text-slate-200 mt-1">{selectedVm.estado_horizon || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Estado Agente Horizon</div>
                    <div className="font-bold text-slate-200 mt-1">{selectedVm.estado_horizon_agente || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">VMware Tools</div>
                    <div className="font-bold text-slate-200 mt-1">{selectedVm.tools_status || '—'}</div>
                  </div>

                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">CPU</div>
                    <div className="font-mono font-bold text-slate-200 mt-1">
                      {selectedVm.cpu ? `${selectedVm.cpu} vCPU` : '—'}
                      {selectedVm.cpu_usage_mhz ? <span className="text-slate-500 font-normal"> ({selectedVm.cpu_usage_mhz} MHz)</span> : null}
                    </div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">RAM</div>
                    <div className="font-mono font-bold text-slate-200 mt-1">
                      {selectedVm.ram_gb ? `${selectedVm.ram_gb} GB` : '—'}
                      {selectedVm.memory_usage_mb ? <span className="text-slate-500 font-normal"> ({Math.round(selectedVm.memory_usage_mb / 1024)} GB en uso)</span> : null}
                    </div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Disco</div>
                    <div className="font-mono font-bold text-slate-200 mt-1">
                      {selectedVm.disk_used_gb != null ? `${selectedVm.disk_used_gb} GB` : '—'}
                      {selectedVm.disk_gb ? <span className="text-slate-500 font-normal"> / {selectedVm.disk_gb} GB</span> : null}
                    </div>
                  </div>

                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Dirección IP</div>
                    <div className="font-mono font-bold text-slate-200 mt-1">{selectedVm.ip || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Nombre DNS</div>
                    <div className="font-mono text-slate-300 mt-1 truncate" title={selectedVm.dns}>{selectedVm.dns || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800" title="Última sesión Horizon conocida -- no se borra al desconectar">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">IP Cliente Horizon</div>
                    <div className="font-mono font-bold text-slate-200 mt-1">{selectedVm.client_ip || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800" title="Última sesión Horizon conocida -- no se borra al desconectar">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Equipo Cliente Horizon</div>
                    <div className="font-mono text-slate-300 mt-1 truncate" title={selectedVm.client_name}>{selectedVm.client_name || '—'}</div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800" title="Gateway/UAG que atendió la última sesión conocida -- no se borra al desconectar">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">Gateway/UAG</div>
                    <div className="font-mono text-slate-300 mt-1 truncate" title={selectedVm.gateway_name}>
                      {selectedVm.gateway_name || '—'}{selectedVm.gateway_ip ? ` (${selectedVm.gateway_ip})` : ''}
                      {selectedVm.gateway_location ? <span className="text-slate-500"> · {selectedVm.gateway_location}</span> : ''}
                    </div>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div className="text-slate-500 uppercase text-[10px] font-semibold">vCenter Host</div>
                    <div className="font-mono text-slate-300 mt-1">{selectedVm.vcenter_host || '—'}</div>
                  </div>
                </div>

                {/* Manual Fields Editing */}
                <div className="space-y-3 pt-2 border-t border-slate-800">
                  <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-wider">Edición Manual de Campos</h4>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] font-semibold text-slate-400 mb-1">Estado Operacional Manual</label>
                      <input
                        type="text"
                        value={editEstado}
                        onChange={(e) => setEditEstado(e.target.value)}
                        placeholder="Ej: Esperando contacto, Eliminar, Ok..."
                        className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] font-semibold text-slate-400 mb-1">Anotación / Observaciones</label>
                      <input
                        type="text"
                        value={editNotas}
                        onChange={(e) => setEditNotas(e.target.value)}
                        placeholder="Detalles sobre el equipo o usuario..."
                        className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                      />
                    </div>
                  </div>
                </div>

                {/* Responsable manual -- separado de Usuario Asignado (dinamico/Horizon).
                    Persiste entre extracciones porque vive en MaquinaUsuarioDir, tabla que
                    la extraccion nunca toca. Pensado sobre todo para VM_ESTATICA. */}
                <div className="space-y-2 pt-2 border-t border-slate-800">
                  <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-wider">Responsable Asignado</h4>
                  <div className="flex items-center justify-between bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <div>
                      <div className="text-slate-500 uppercase text-[10px] font-semibold">Responsable manual</div>
                      <div className="font-bold text-slate-100 mt-1">
                        {selectedVm.responsable ? (
                          getTeamsChatUrl({ username: selectedVm.responsable_username, email: selectedVm.responsable_email }) ? (
                            <a
                              href={getTeamsChatUrl({ username: selectedVm.responsable_username, email: selectedVm.responsable_email })}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:text-indigo-400 hover:underline inline-flex items-center space-x-1 group"
                              title="Iniciar Chat en Microsoft Teams"
                            >
                              <span>{selectedVm.responsable}</span>
                              <span className="text-[10px] px-1 py-0.2 rounded bg-indigo-500/20 text-indigo-300 group-hover:bg-indigo-500 group-hover:text-white transition-colors">
                                💬 Teams
                              </span>
                            </a>
                          ) : (
                            <span>{selectedVm.responsable}</span>
                          )
                        ) : (
                          <span className="text-slate-500 italic font-normal">Sin responsable asignado</span>
                        )}
                      </div>
                      {selectedVm.responsable && (selectedVm.responsable_username || selectedVm.responsable_email) && (
                        <div className="text-slate-500 text-[10px] mt-0.5">
                          {selectedVm.responsable_username}{selectedVm.responsable_email ? ` · ${selectedVm.responsable_email}` : ''}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center space-x-2">
                      {selectedVm.responsable && (
                        <Button variant="secondary" size="sm" disabled={isAssigningResponsable} onClick={handleRemoveResponsable}>
                          Quitar
                        </Button>
                      )}
                      <Button variant="secondary" size="sm" onClick={() => setShowResponsablePicker((v) => !v)}>
                        {selectedVm.responsable ? 'Cambiar' : 'Asignar'}
                      </Button>
                    </div>
                  </div>

                  {showResponsablePicker && (
                    <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 space-y-2">
                      <input
                        type="text"
                        autoFocus
                        value={responsableSearch}
                        onChange={(e) => setResponsableSearch(e.target.value)}
                        placeholder="Buscar por nombre, usuario o email..."
                        className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                      />
                      {isResponsableSearching && (
                        <div className="text-[11px] text-slate-500">Buscando...</div>
                      )}
                      {!isResponsableSearching && responsableSearch.trim() && responsableResults.length === 0 && (
                        <div className="text-[11px] text-slate-500">Sin resultados en el directorio.</div>
                      )}
                      {responsableResults.length > 0 && (
                        <div className="max-h-40 overflow-y-auto divide-y divide-slate-800">
                          {responsableResults.map((u) => (
                            <button
                              key={u.id}
                              type="button"
                              disabled={isAssigningResponsable}
                              onClick={() => handleAssignResponsable(u)}
                              className="w-full text-left px-2 py-1.5 hover:bg-slate-800 rounded text-xs text-slate-200"
                            >
                              <div className="font-semibold">{u.nombre_completo || u.username}</div>
                              <div className="text-slate-500 text-[10px]">{u.username} {u.email ? `· ${u.email}` : ''}</div>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div className="pt-3 border-t border-slate-800 flex items-center justify-between">
                  <Button
                    variant="primary"
                    size="sm"
                    icon={Save}
                    disabled={isSaving}
                    onClick={handleSaveVmDetail}
                  >
                    {isSaving ? 'Guardando...' : 'Guardar Cambios'}
                  </Button>

                  <Button variant="secondary" size="sm" onClick={() => setSelectedVm(null)}>
                    Cerrar
                  </Button>
                </div>
              </div>
            )}

            {/* TAB 2 & TAB 3: Timeline Visual Cronológico & Deltas */}
            {(activeModalTab === 'rotacion' || activeModalTab === 'deltas') && (
              <div className="pt-1">
                <VmTimelineView
                  trazabilidadData={trazabilidadData}
                  isLoading={isTrazabilidadLoading}
                  vmName={selectedVm.nombre}
                />
              </div>
            )}

            {/* TAB 4: Supervisar (Tareas & Eventos vCenter) */}
            {activeModalTab === 'eventos' && (
              <div className="pt-1">
                <VmEventsView maquinaId={selectedVm.id} vmName={selectedVm.nombre} />
              </div>
            )}

            {/* TAB 5: App Volumes — apps asignadas + actividad reciente */}
            {activeModalTab === 'appvolumes' && (
              <div className="pt-1 space-y-4">
                {isTrazabilidadLoading ? (
                  <div className="py-8 text-center text-slate-400 animate-pulse text-xs">Cargando datos de App Volumes...</div>
                ) : (
                  <>
                    <div className="space-y-2">
                      <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center">
                        <Package className="w-4 h-4 mr-1.5" /> Aplicaciones Asignadas ({trazabilidadData?.appvolumes_apps?.length || 0})
                      </h4>
                      {(trazabilidadData?.appvolumes_apps?.length || 0) === 0 ? (
                        <div className="p-4 bg-slate-900/40 rounded-xl text-center text-slate-500 text-xs italic">
                          Sin asignaciones de App Volumes detectadas para esta VM o su usuario asignado.
                        </div>
                      ) : (
                        <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
                          {trazabilidadData.appvolumes_apps.map((a, idx) => (
                            <div key={idx} className="p-3 rounded-xl bg-slate-900/90 border border-slate-800/90 text-xs flex items-center justify-between">
                              <div className="flex items-center space-x-2 min-w-0">
                                <Package className="w-4 h-4 text-emerald-400 shrink-0" />
                                <div className="min-w-0">
                                  <div className="font-bold text-slate-100 truncate">{a.aplicacion_nombre || a.paquete_nombre || `App ${a.av_id}`}</div>
                                  {a.paquete_nombre && a.aplicacion_nombre && (
                                    <div className="text-[10px] text-slate-500 truncate">Paquete: {a.paquete_nombre}</div>
                                  )}
                                </div>
                              </div>
                              <div className="flex items-center space-x-2 shrink-0">
                                <Badge variant="neutral">{a.entity_type}: {a.entity_name}</Badge>
                                {a.delivery && <Badge variant="info">{a.delivery}</Badge>}
                                {(a.servidores || []).map((srv) => (
                                  <Badge key={srv} variant="success">{srv}</Badge>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="space-y-2 pt-3 border-t border-slate-800">
                      <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center">
                        <HardDrive className="w-4 h-4 mr-1.5" /> Writable Volumes ({trazabilidadData?.appvolumes_writables?.cantidad || 0})
                        {(trazabilidadData?.appvolumes_writables?.cantidad || 0) > 1 && (
                          <Badge variant="warning" className="ml-2">{trazabilidadData.appvolumes_writables.total_gb} GB acumulados</Badge>
                        )}
                      </h4>
                      {(trazabilidadData?.appvolumes_writables?.cantidad || 0) === 0 ? (
                        <div className="p-4 bg-slate-900/40 rounded-xl text-center text-slate-500 text-xs italic">
                          Sin Writable Volumes de App Volumes detectados para esta VM o su usuario asignado.
                        </div>
                      ) : (
                        <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
                          {(trazabilidadData.appvolumes_writables.cantidad > 1) && (
                            <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-300">
                              ⚠️ Más de un writable acumulado para esta VM/usuario -- candidato a revisar/limpiar en el Admin UI de App Volumes.
                            </div>
                          )}
                          {trazabilidadData.appvolumes_writables.items.map((w, idx) => (
                            <div key={idx} className="p-3 rounded-xl bg-slate-900/90 border border-slate-800/90 text-xs flex items-center justify-between">
                              <div className="flex items-center space-x-2 min-w-0">
                                <HardDrive className="w-4 h-4 text-emerald-400 shrink-0" />
                                <div className="min-w-0">
                                  <div className="font-bold text-slate-100 truncate">{w.owner_display_name || w.nombre}</div>
                                  <div className="text-[10px] text-slate-500 truncate">
                                    {w.entity_type}: {w.entity_name || '—'}{w.attached_to ? ` · montado en ${w.attached_to}` : ' · desmontado ahora'}
                                  </div>
                                </div>
                              </div>
                              <div className="flex items-center space-x-2 shrink-0">
                                <span className="font-mono text-slate-300">{w.size_gb ?? '—'} GB</span>
                                <Badge variant={w.estado === 'Attached' ? 'success' : 'neutral'}>{w.estado || '—'}</Badge>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="space-y-2 pt-3 border-t border-slate-800">
                      <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center">
                        <Activity className="w-4 h-4 mr-1.5" /> Actividad Reciente ({trazabilidadData?.appvolumes_actividad?.length || 0})
                      </h4>
                      {(trazabilidadData?.appvolumes_actividad?.length || 0) === 0 ? (
                        <div className="p-4 bg-slate-900/40 rounded-xl text-center text-slate-500 text-xs italic">
                          Sin eventos de attach/login de App Volumes registrados para esta VM.
                        </div>
                      ) : (
                        <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
                          {trazabilidadData.appvolumes_actividad.map((e, idx) => (
                            <div key={idx} className="p-3 rounded-xl bg-slate-900/90 border border-slate-800/90 text-xs flex items-center justify-between">
                              <div className="min-w-0">
                                <div className="font-mono text-slate-200 truncate">
                                  {e.source_name || '—'} <span className="text-slate-500">→</span> {e.target_name || '—'}
                                </div>
                                <div className="text-[10px] text-slate-500">{e.event_time || 'Sin fecha'}</div>
                              </div>
                              <div className="flex items-center space-x-2 shrink-0">
                                <Badge variant="neutral">{e.accion || '—'}</Badge>
                                <Badge variant={e.resultado === 'Success' ? 'success' : 'danger'}>{e.resultado || '—'}</Badge>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* TAB 6: Imagen / Pool -- master/snapshot actual + eventos Horizon (Image Publish/Unpublish) */}
            {activeModalTab === 'imagen_pool' && (
              <div className="pt-1 space-y-4">
                {isTrazabilidadLoading ? (
                  <div className="py-8 text-center text-slate-400 animate-pulse text-xs">Cargando...</div>
                ) : (
                  <>
                    <div className="space-y-2">
                      <h4 className="text-xs font-bold text-purple-400 uppercase tracking-wider flex items-center">
                        <Package className="w-4 h-4 mr-1.5" /> Imagen Actual del Pool
                      </h4>
                      {trazabilidadData?.pool_imagen?.master_vm_actual ? (
                        <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800/90 text-xs space-y-1.5">
                          <div className="flex items-center justify-between">
                            <span className="text-slate-400">Master VM:</span>
                            <span className="font-mono font-bold text-slate-100">{trazabilidadData.pool_imagen.master_vm_actual}</span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-slate-400">Snapshot:</span>
                            <span className="font-mono text-slate-200 text-right truncate max-w-[60%]" title={trazabilidadData.pool_imagen.snapshot_actual}>
                              {acortarSnapshot(trazabilidadData.pool_imagen.snapshot_actual)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-slate-400">Publicada:</span>
                            <span className="font-mono text-slate-300">{trazabilidadData.pool_imagen.imagen_actualizada_en || '—'}</span>
                          </div>
                        </div>
                      ) : (
                        <div className="p-4 bg-slate-900/40 rounded-xl text-center text-slate-500 text-xs italic">
                          Sin eventos de Image Publish registrados para este pool todavía.
                        </div>
                      )}
                    </div>

                    <div className="space-y-2 pt-3 border-t border-slate-800">
                      <h4 className="text-xs font-bold text-purple-400 uppercase tracking-wider flex items-center">
                        <History className="w-4 h-4 mr-1.5" /> Eventos Horizon (Pool + VM) ({trazabilidadData?.eventos_horizon?.length || 0})
                      </h4>
                      {(trazabilidadData?.eventos_horizon?.length || 0) === 0 ? (
                        <div className="p-4 bg-slate-900/40 rounded-xl text-center text-slate-500 text-xs italic">
                          Sin eventos de auditoría Horizon vinculados a esta VM o su pool.
                        </div>
                      ) : (
                        <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                          {trazabilidadData.eventos_horizon.map((e) => (
                            <div key={e.id} className="p-3 rounded-xl bg-slate-900/90 border border-slate-800/90 text-xs">
                              <div className="flex items-center justify-between mb-1">
                                <Badge variant="neutral">{e.entidad}</Badge>
                                <span className="text-[10px] text-slate-500 font-mono">{e.fecha}</span>
                              </div>
                              <div className="text-slate-300 break-words">{e.mensaje}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Extraction SSE Modal */}
      <ExtraerModal
        isOpen={isExtraerOpen}
        onClose={() => setIsExtraerOpen(false)}
        onCompleted={() => refetch()}
      />

      {/* Credenciales vCenter -- requerido para que el guardado de la anotación pueda sincronizar */}
      <VcSessionModal
        isOpen={isVcModalOpen}
        onClose={() => setIsVcModalOpen(false)}
        onSaved={() => {
          setIsVcModalOpen(false);
          refetchVcStatus();
        }}
      />

      {/* vCenter Supervisar (Tasks & Events) Modal */}
      <VmEventsModal
        isOpen={!!selectedEventsVm}
        onClose={() => setSelectedEventsVm(null)}
        maquinaId={selectedEventsVm?.id}
        vmName={selectedEventsVm?.nombre}
      />

      {/* Save Preset Modal */}
      {isSavePresetModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 w-full max-w-md space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-bold text-slate-100 flex items-center">
                <Bookmark className="w-4 h-4 text-amber-400 mr-2" /> Guardar Filtro Personalizado
              </h3>
              <button onClick={() => setIsSavePresetModalOpen(false)} className="text-slate-400 hover:text-white cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Nombre de la Vista o Filtro</label>
              <input
                type="text"
                value={presetNameInput}
                onChange={(e) => setPresetNameInput(e.target.value)}
                placeholder="Ej: VDIs en Error, VMs en VSAN-SU, etc."
                className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                autoFocus
              />
            </div>

            <div className="text-[11px] text-slate-400 bg-slate-950 p-2.5 rounded-lg border border-slate-800">
              Se guardarán {customFilters.length} regla(s) de filtro configuradas. Podrás aplicarla con un click.
            </div>

            <div className="flex justify-end space-x-2 pt-2">
              <Button variant="secondary" size="sm" onClick={() => setIsSavePresetModalOpen(false)}>
                Cancelar
              </Button>
              <Button variant="primary" size="sm" onClick={saveCurrentPreset} disabled={!presetNameInput.trim()}>
                Guardar Vista
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
