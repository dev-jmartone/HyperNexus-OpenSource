import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Filter,
  Plus,
  Trash2,
  Bookmark,
  Save,
  X,
  SlidersHorizontal,
  Check,
  RotateCcw,
  Sparkles,
  Layers
} from 'lucide-react';
import { Badge } from './Badge';
import { Button } from './Button';
import api from '../../services/api';

// Campos "enum" cuyo valor viene de Horizon/vCenter en vez de ser una clasificación propia
// curada (persistencia/categoria_estatica sí son propias, dominio fijo conocido, quedan
// hardcodeadas abajo) -- para estos, las opciones del picker se completan en vivo desde
// /api/filtros/valores_distintos en vez de una lista a mano. Bug real encontrado 2026-09-04
// (auditoría de filtros pedida por el usuario): la lista a mano de 'estado_vcenter' ofrecía
// 'PoweredOn'/'PoweredOff'/'Suspended', la DB guarda 'POWERED_ON'/'POWERED_OFF' -- el filtro
// daba 0 resultados siempre, en silencio. 'estado_horizon' solo ofrecía 4 de 8 valores reales.
// 'tipo_provisionamiento' ofrecía TEMPLATE, nunca poblado hoy. Con esto, si el valor real
// cambia (nuevo estado que Horizon empieza a reportar, etc.) el picker se actualiza solo.
const CAMPOS_ENUM_DINAMICOS = [
  'tipo', 'origen', 'estado_horizon', 'estado_vcenter', 'persistencia',
  // Vocabulario fijo que reporta Horizon/vCenter directo (antes solo búsqueda de texto
  // libre, pese a tener un puñado bien acotado de valores reales posibles).
  'estado_horizon_agente', 'tools_status', 'connection_state',
  // Campo virtual que unifica tipo_provisionamiento + categoria_estatica en un solo filtro
  // (2026-09-04, 4ta vuelta: el usuario pidió explícitamente UN SOLO filtro para todos los
  // tags de segmentación -- antes había 3 campos superpuestos (Segmentación/Tipo
  // Provisionamiento/Subcategoría Estática), confuso y percibido como "roto". tipo_
  // provisionamiento y categoria_estatica siguen existiendo como columnas/lógica en el
  // backend (los usan otras cosas: KPIs, el badge, sort de la tabla), pero ya no son
  // seleccionables como filtro aparte -- 'segmentacion' es el único punto de entrada.
  'segmentacion',
];

// Etiqueta amigable por valor real -- si un valor nuevo aparece y no está acá, se muestra
// el valor crudo tal cual (nunca se oculta una opción real por falta de traducción).
const ENUM_LABELS = {
  tipo: { VDI: 'VDI', VM: 'VM Exclusiva vCenter' },
  origen: { dt: 'DT', su: 'SU', core: 'CORE', mz: 'MZ' },
  estado_horizon: {
    CONNECTED: 'CONNECTED (Conectado)',
    AVAILABLE: 'AVAILABLE (Disponible)',
    DISCONNECTED: 'DISCONNECTED (Desconectado)',
    ALREADY_USED: 'ALREADY_USED (Ya utilizada)',
    ERROR: 'ERROR',
    MAINTENANCE: 'MAINTENANCE (Mantenimiento)',
    DELETING: 'DELETING (Eliminándose)',
    PROVISIONING_ERROR: 'PROVISIONING_ERROR (Error de aprovisionamiento)',
    'N/A (vCenter)': 'N/A (sin sesión Horizon, solo vCenter)',
  },
  estado_vcenter: {
    POWERED_ON: 'POWERED_ON (Encendido)',
    POWERED_OFF: 'POWERED_OFF (Apagado)',
    SUSPENDED: 'SUSPENDED (Suspendido)',
  },
  // Mismas 8 etiquetas EXACTAS que getSegmentacionBadge() pinta en la columna de la tabla
  // (InventarioPage.jsx) -- que el valor elegido en el filtro se vea igual que el badge
  // es el punto de este campo.
  segmentacion: {
    master: 'MASTER',
    template: 'PLANTILLA',
    vdi_pool: 'VDI POOL',
    estatica: 'ESTÁTICA',
    infra: 'INFRA INTERNA',
    rpa: 'RPA',
    copia: 'COPIA (VIEJA)',
    huerfana: 'VDI HUÉRFANA',
  },
  // persistencia y estado_horizon_agente/tools_status/connection_state no necesitan mapa:
  // el backend ya devuelve el string final para mostrar (o, en connection_state/tools_status,
  // el valor crudo de vCenter es suficientemente legible tal cual).
};

function buildOptionsFromValues(field, valores) {
  if (!valores || valores.length === 0) return undefined;
  const labels = ENUM_LABELS[field] || {};
  return valores.map((v) => ({ value: v, label: labels[v] || v }));
}

// Column classification: Enum vs Text vs Numeric
export const COLUMN_DEFINITIONS = {
  tipo: { label: 'Tipo', type: 'enum' },
  // Campo virtual único para todos los tags de segmentación (MASTER/PLANTILLA/VDI POOL/
  // ESTÁTICA/RPA/COPIA (VIEJA)/VDI HUÉRFANA/INFRA INTERNA) -- un solo filtro a propósito,
  // no dos (2026-09-04, 4ta vuelta). tipo_provisionamiento y categoria_estatica ya no son
  // seleccionables acá; siguen existiendo como columnas/lógica interna (badge, KPIs, sort).
  segmentacion: { label: 'Segmentación', type: 'enum' },
  origen: { label: 'Origen (Pod/DC)', type: 'enum' },
  estado_horizon: { label: 'Estado Horizon', type: 'enum' },
  estado_vcenter: { label: 'Estado vCenter', type: 'enum' },
  maintenance_mode: {
    label: 'Modo Mantenimiento',
    type: 'enum',
    options: [
      { value: 'true', label: 'En Mantenimiento' },
      { value: 'false', label: 'Normal' }
    ]
  },
  in_error_state: {
    label: 'Estado Error',
    type: 'enum',
    options: [
      { value: 'true', label: 'En Error' },
      { value: 'false', label: 'Sin Error' }
    ]
  },
  persistencia: { label: 'Persistencia', type: 'enum' },
  nombre: { label: 'Nombre VM', type: 'text', placeholder: 'Ej: VDI-DOC-001...' },
  responsable: { label: 'Responsable', type: 'text', placeholder: 'Ej: Juan Pérez, jperez...' },
  usuario_asignado: { label: 'Usuario Asignado', type: 'text', placeholder: 'Ej: jdoe, admin...' },
  pool: { label: 'Pool Horizon', type: 'text', placeholder: 'Ej: Engineering-Win11...' },
  master_vm_actual: { label: 'Master VM', type: 'text', placeholder: 'Ej: MASTER-WIN11-V9...' },
  snapshot_actual: { label: 'Snapshot', type: 'text', placeholder: 'Ej: V9_QUALYS+TEAMS...' },
  empresa: { label: 'Empresa', type: 'text', placeholder: 'Ej: Core, DevOps...' },
  ip: { label: 'Dirección IP', type: 'text', placeholder: 'Ej: 10.100...' },
  client_ip: { label: 'IP Cliente Horizon (último acceso)', type: 'text', placeholder: 'Ej: 192.168...' },
  client_name: { label: 'Equipo Cliente Horizon', type: 'text', placeholder: 'Ej: DESKTOP-...' },
  gateway_name: { label: 'Gateway/UAG (último acceso)', type: 'text', placeholder: 'Ej: gw-uag01...' },
  gateway_ip: { label: 'IP Gateway/UAG', type: 'text', placeholder: 'Ej: 10.16.10...' },
  dns: { label: 'Nombre DNS', type: 'text', placeholder: 'Ej: corp.local...' },
  vcenter_host: { label: 'vCenter Host', type: 'text', placeholder: 'Ej: esxi-01...' },
  folder: { label: 'Folder vCenter', type: 'text', placeholder: 'Ej: /Datacenter/VDI...' },
  resource_pool: { label: 'Resource Pool', type: 'text', placeholder: 'Ej: Resources...' },
  datastores: { label: 'Datastores', type: 'text', placeholder: 'Ej: vsanDatastore...' },
  so: { label: 'Sistema Operativo', type: 'text', placeholder: 'Ej: Windows 11...' },
  annotation: { label: 'Anotación', type: 'text', placeholder: 'Ej: Servidor Web...' },
  cpu: { label: 'Cores CPU', type: 'number', placeholder: 'Ej: 4' },
  ram_gb: { label: 'RAM (GB)', type: 'number', placeholder: 'Ej: 16' },
  disk_gb: { label: 'Disco (GB)', type: 'number', placeholder: 'Ej: 100' },
  cpu_usage_mhz: { label: 'CPU en uso (MHz)', type: 'number', placeholder: 'Ej: 500' },
  memory_usage_mb: { label: 'RAM en uso (MB)', type: 'number', placeholder: 'Ej: 4096' },
  // Estos 6 eran columnas visibles/ocultables en la tabla (ALL_COLUMNS de
  // InventarioPage.jsx) pero nunca estuvieron en el picker de filtros -- gap
  // preexistente encontrado al auditar por el pedido de "agregaste todo?" 2026-09-02.
  estado_horizon_agente: { label: 'Estado Agente Horizon', type: 'enum' },
  tools_status: { label: 'VMware Tools', type: 'enum' },
  // estado: campo manual (el admin lo tipea libre al editar la VM, ver placeholder), no un
  // vocabulario que reporte Horizon/vCenter -- distinto de los de arriba, queda texto libre
  // igual que annotation/responsable.
  estado: { label: 'Estado Operacional (manual)', type: 'text', placeholder: 'Ej: Esperando contacto, Eliminar...' },
  fecha_ultimo_ingreso: { label: 'Fecha Último Ingreso', type: 'text', placeholder: 'Ej: 2026-08...' },
  hardware_version: { label: 'HW Version', type: 'text', placeholder: 'Ej: vmx-19...' },
  connection_state: { label: 'Estado Conexión (vCenter)', type: 'enum' }
};

export function SmartFilterToolbar({
  allColumns,
  activeRules,
  onRulesChange,
  savedPresets,
  onSavePreset,
  onDeletePreset,
  onApplyPreset,
  visibleColumns,
  onRestoreColumns,
  onToggleColumn,
  servidores
}) {
  const [isAddingRule, setIsAddingRule] = useState(false);
  const [selectedFieldToAdd, setSelectedFieldToAdd] = useState('tipo');
  const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
  const [presetNameInput, setPresetNameInput] = useState('');
  const [isColumnsOpen, setIsColumnsOpen] = useState(false);

  // Valores reales distintos hoy en la DB para los campos de CAMPOS_ENUM_DINAMICOS -- ver
  // comentario junto a esa constante. Cache corta (el backend ya cachea 120s) más
  // staleTime propio: esto cambia solo con una extracción nueva, no hace falta refetch
  // agresivo mientras el usuario arma filtros.
  const { data: valoresDistintos } = useQuery({
    queryKey: ['filtros_valores_distintos'],
    queryFn: () => api.get('/filtros/valores_distintos'),
    staleTime: 60_000,
  });

  // Enhanced definitions with servers + valores reales de Horizon/vCenter
  const smartDefinitions = useMemo(() => {
    const defs = { ...COLUMN_DEFINITIONS };
    for (const campo of CAMPOS_ENUM_DINAMICOS) {
      if (!defs[campo]) continue;
      defs[campo] = {
        ...defs[campo],
        options: buildOptionsFromValues(campo, valoresDistintos?.[campo]),
      };
    }
    if (servidores && servidores.length > 0) {
      defs.servidor_id = {
        label: 'Servidor',
        type: 'enum',
        options: servidores.map((s) => ({ value: s.id.toString(), label: s.nombre }))
      };
    }
    return defs;
  }, [servidores, valoresDistintos]);

  const addRuleForField = (fieldKey) => {
    // Antes bloqueaba una 2da regla del mismo campo -- el backend igual las mandaba
    // todas con AND, así que "tipo_provisionamiento = VDI_POOL Y = MASTER" no podía dar
    // resultado nunca. Ahora el backend combina valores del mismo campo con OR (ver
    // maquinas_api en web/routes/api.py), así que agregar una 2da regla del mismo campo
    // es válido y útil (ej. "RPA o VDI Huérfana").
    const def = smartDefinitions[fieldKey] || { type: 'text' };
    const defaultValue = def.type === 'enum' && def.options ? def.options[0].value : '';

    onRulesChange([
      ...activeRules,
      { id: Date.now().toString() + Math.random(), field: fieldKey, value: defaultValue }
    ]);
    setIsAddingRule(false);
  };

  const updateRuleValue = (id, val) => {
    onRulesChange(activeRules.map((r) => (r.id === id ? { ...r, value: val } : r)));
  };

  const removeRule = (id) => {
    onRulesChange(activeRules.filter((r) => r.id !== id));
  };

  const handleSaveViewSubmit = (e) => {
    e.preventDefault();
    if (!presetNameInput.trim()) return;
    onSavePreset({
      id: Date.now().toString(),
      name: presetNameInput.trim(),
      rules: activeRules,
      visibleColumns: visibleColumns
    });
    setPresetNameInput('');
    setIsSaveModalOpen(false);
  };

  return (
    <div className="relative z-40 space-y-3 bg-slate-900/80 p-3.5 rounded-2xl border border-slate-800 shadow-lg backdrop-blur-md">
      {/* 1. Fast Add Facet Shortcuts & Action Buttons */}
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        {/* Fast Shortcut Badges */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] uppercase font-bold text-slate-400 mr-1 flex items-center">
            <Sparkles className="w-3.5 h-3.5 mr-1 text-cyan-400" /> Filtros Rápidos:
          </span>

          {[
            { key: 'tipo', label: '+ Tipo' },
            { key: 'segmentacion', label: '+ Segmentación' },
            { key: 'origen', label: '+ Origen' },
            { key: 'estado_horizon', label: '+ Est. Horizon' },
            { key: 'estado_vcenter', label: '+ Est. vCenter' },
            { key: 'pool', label: '+ Pool' },
            { key: 'empresa', label: '+ Empresa' },
            { key: 'usuario_asignado', label: '+ Usuario' },
            { key: 'servidor_id', label: '+ Servidor' },
          ].map((sc) => {
            const isActive = activeRules.some((r) => r.field === sc.key);
            return (
              <button
                key={sc.key}
                type="button"
                onClick={() => addRuleForField(sc.key)}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center space-x-1 ${
                  isActive
                    ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/50 shadow-xs'
                    : 'bg-slate-950/80 hover:bg-indigo-600/20 text-slate-300 hover:text-indigo-200 border border-slate-800'
                }`}
              >
                <span>{sc.label}</span>
                {isActive && <Check className="w-3 h-3 text-indigo-400 ml-1" />}
              </button>
            );
          })}
        </div>

        {/* Action Controls */}
        <div className="flex items-center space-x-2">
          {/* Add custom column rule selector */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setIsAddingRule(!isAddingRule)}
              className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold flex items-center space-x-1.5 transition-all shadow-md shadow-indigo-600/20 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Más Filtros</span>
            </button>

            {isAddingRule && (
              <div className="absolute right-0 mt-2 w-64 bg-slate-950 border border-slate-700/80 rounded-xl shadow-2xl z-[999] p-2 text-xs space-y-1 max-h-64 overflow-y-auto">
                <div className="text-[10px] uppercase font-bold text-slate-500 px-2 py-1">Seleccionar Columna</div>
                {Object.entries(smartDefinitions).map(([key, def]) => (
                  <button
                    key={key}
                    onClick={() => addRuleForField(key)}
                    className="w-full text-left px-2.5 py-1.5 hover:bg-slate-800 text-slate-200 rounded-lg transition-colors flex items-center justify-between cursor-pointer"
                  >
                    <span>{def.label}</span>
                    <span className="text-[9px] font-mono text-slate-500 uppercase">{def.type}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Selector de columnas visibles */}
          {allColumns && onToggleColumn && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setIsColumnsOpen(!isColumnsOpen)}
                className="px-3 py-1.5 bg-slate-950 hover:bg-slate-800 text-cyan-300 border border-cyan-500/40 rounded-xl text-xs font-semibold flex items-center space-x-1.5 transition-all cursor-pointer"
                title="Elegir qué columnas mostrar en la tabla"
              >
                <SlidersHorizontal className="w-3.5 h-3.5 text-cyan-400" />
                <span>Columnas ({visibleColumns?.length || 0}/{allColumns.length})</span>
              </button>

              {isColumnsOpen && (
                <div className="absolute right-0 mt-2 w-64 bg-slate-950 border border-slate-700/80 rounded-xl shadow-2xl z-[999] p-2 text-xs space-y-0.5 max-h-80 overflow-y-auto">
                  <div className="flex items-center justify-between px-2 py-1 sticky top-0 bg-slate-950">
                    <span className="text-[10px] uppercase font-bold text-slate-500">Columnas visibles</span>
                    <button
                      type="button"
                      onClick={() => setIsColumnsOpen(false)}
                      className="text-slate-500 hover:text-slate-200"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  {allColumns.map((col) => {
                    const checked = visibleColumns?.includes(col.key);
                    return (
                      <label
                        key={col.key}
                        className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-slate-800 text-slate-200 rounded-lg transition-colors cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => onToggleColumn(col.key)}
                          className="accent-cyan-500 w-3.5 h-3.5 cursor-pointer"
                        />
                        <span className={checked ? '' : 'text-slate-500'}>{col.label}</span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Save current view (filters + visible columns) */}
          <button
            type="button"
            onClick={() => setIsSaveModalOpen(true)}
            className="px-3 py-1.5 bg-slate-950 hover:bg-slate-800 text-amber-300 border border-amber-500/40 rounded-xl text-xs font-semibold flex items-center space-x-1.5 transition-all cursor-pointer"
            title="Guardar vista actual con filtros y columnas activas"
          >
            <Save className="w-3.5 h-3.5 text-amber-400" />
            <span>Guardar Vista</span>
          </button>

          {activeRules.length > 0 && (
            <button
              type="button"
              onClick={() => onRulesChange([])}
              className="p-1.5 bg-slate-950 hover:bg-red-500/20 text-red-400 border border-red-500/30 rounded-xl text-xs font-semibold transition-all cursor-pointer"
              title="Limpiar todos los filtros"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* 2. Active Filter Cards Row (Direct Values, No "Es igual a" / "Contiene") */}
      {activeRules.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-800/80">
          <span className="text-[10px] uppercase font-bold text-indigo-400 mr-1">Filtros Activos:</span>

          {activeRules.map((rule) => {
            const def = smartDefinitions[rule.field] || { label: rule.field, type: 'text' };
            return (
              <div
                key={rule.id}
                className="flex items-center space-x-2 bg-slate-950 border border-indigo-500/40 px-2.5 py-1 rounded-xl text-xs shadow-xs"
              >
                <span className="font-bold text-slate-300">{def.label}:</span>

                {/* Render Control depending on type */}
                {def.type === 'enum' ? (
                  <select
                    value={rule.value}
                    onChange={(e) => updateRuleValue(rule.id, e.target.value)}
                    className="bg-slate-900 text-indigo-300 font-bold border border-slate-800 rounded-lg px-2 py-0.5 text-xs focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    {def.options?.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={def.type === 'number' ? 'number' : 'text'}
                    value={rule.value}
                    onChange={(e) => updateRuleValue(rule.id, e.target.value)}
                    placeholder={def.placeholder || 'Escriba para filtrar...'}
                    className="bg-slate-900 text-indigo-300 font-semibold border border-slate-800 rounded-lg px-2 py-0.5 text-xs focus:outline-none focus:border-indigo-500 min-w-[140px]"
                  />
                )}

                <button
                  type="button"
                  onClick={() => removeRule(rule.id)}
                  className="text-slate-500 hover:text-red-400 p-0.5 transition-colors cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* 3. Saved Views Carousel / Pills */}
      {savedPresets && savedPresets.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-800/60">
          <span className="text-[10px] uppercase font-bold text-amber-400 mr-1 flex items-center">
            <Bookmark className="w-3 h-3 mr-1" /> Vistas Guardadas:
          </span>

          {savedPresets.map((preset) => (
            <div
              key={preset.id}
              onClick={() => onApplyPreset(preset)}
              className="group inline-flex items-center space-x-1.5 px-2.5 py-1 bg-slate-950 hover:bg-slate-800 text-slate-200 hover:text-white border border-slate-800 hover:border-indigo-500/50 rounded-xl text-xs cursor-pointer transition-all shadow-xs"
            >
              <span className="font-semibold text-slate-200">{preset.name}</span>
              <span className="text-[9px] text-indigo-300 bg-indigo-500/20 px-1.5 py-0.2 rounded font-mono border border-indigo-500/30">
                {preset.rules?.length || 0} filtro(s)
              </span>
              {preset.visibleColumns && (
                <span className="text-[9px] text-cyan-300 bg-cyan-500/20 px-1.5 py-0.2 rounded font-mono border border-cyan-500/30">
                  {preset.visibleColumns.length} cols
                </span>
              )}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeletePreset(preset.id);
                }}
                className="text-slate-500 hover:text-red-400 p-0.5 rounded transition-colors ml-1"
                title="Eliminar vista guardada"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Modal for Saving Current View */}
      {isSaveModalOpen && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-5 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2">
                <Bookmark className="w-5 h-5 text-amber-400" />
                <h3 className="font-bold text-slate-100 text-sm">Guardar Vista Personalizada</h3>
              </div>
              <button onClick={() => setIsSaveModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSaveViewSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block font-semibold text-slate-300 mb-1">Nombre de la Vista</label>
                <input
                  type="text"
                  value={presetNameInput}
                  onChange={(e) => setPresetNameInput(e.target.value)}
                  placeholder="Ej: VDIs Libres en DT, Servidores en Mantenimiento..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  autoFocus
                />
              </div>

              <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 space-y-1.5">
                <div className="text-[10px] uppercase font-bold text-slate-400">Contenido que se guardará:</div>
                <div className="text-slate-300 font-medium">✓ {activeRules.length} regla(s) de filtro configuradas</div>
                <div className="text-slate-300 font-medium">✓ {visibleColumns.length} columna(s) visibles actuales</div>
              </div>

              <div className="flex items-center justify-end space-x-2 pt-2">
                <Button variant="secondary" size="sm" type="button" onClick={() => setIsSaveModalOpen(false)}>
                  Cancelar
                </Button>
                <Button variant="primary" size="sm" type="submit" icon={Save}>
                  Guardar Vista
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
