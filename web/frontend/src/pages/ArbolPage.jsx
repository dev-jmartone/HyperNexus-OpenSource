import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { VmDetailPanel } from '../components/panels/VmDetailPanel';
import {
  FolderTree,
  Folder,
  Monitor,
  RefreshCw,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  CheckCircle2,
  Info,
  Server,
  Power,
  Search,
  X,
} from 'lucide-react';

const ORDEN_ORIGENES = ['dt', 'mz', 'su', 'core'];
const ORIGIN_LABEL = { dt: 'DT', mz: 'MZ', su: 'SU', core: 'CORE' };

function tipoBadge(tp) {
  switch (tp) {
    case 'MASTER':
      return <Badge variant="purple" className="text-[10px] px-1.5 py-0">MASTER</Badge>;
    case 'TEMPLATE':
      return <Badge variant="info" className="text-[10px] px-1.5 py-0">PLANTILLA</Badge>;
    case 'VDI_POOL':
      return <Badge variant="success" className="text-[10px] px-1.5 py-0">VDI</Badge>;
    case 'VM_ESTATICA':
      return <Badge variant="neutral" className="text-[10px] px-1.5 py-0">ESTÁTICA</Badge>;
    default:
      return null;
  }
}

// Resalta la porción de `text` que matchea `term` (buscador inteligente) sin ocultar ni
// filtrar nada más -- pedido explícito 2026-09-08 ("que te ayude a ir a la máquina sin
// ocultar el resto"). Un solo resaltado por nombre alcanza (nombres de VM son cortos).
function highlightMatch(text, term) {
  if (!term) return text;
  const idx = text.toLowerCase().indexOf(term);
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-amber-400/30 text-amber-200 rounded-sm">{text.slice(idx, idx + term.length)}</mark>
      {text.slice(idx + term.length)}
    </>
  );
}

// Fila de VM -- selecciona en el panel derecho (mismo panel, nunca navega afuera del
// Árbol: pedido 2026-09-04 "no quiero que se mueva hacia inventario-vdi").
function VmRow({ vm, selectedId, onSelect, searchTerm }) {
  const toolsUp = (vm.tools_status || '').toUpperCase();
  const toolsOk = toolsUp === 'RUNNING';
  const toolsKnown = Boolean(toolsUp);
  // Agregado 2026-09-07 -- antes solo se veía el estado de VMware Tools, nada indicaba
  // si la VM estaba realmente Powered On/Off en vCenter.
  const powerState = (vm.estado_vcenter || '').toUpperCase();
  const poweredOn = powerState.includes('ON');
  const powerKnown = Boolean(powerState);
  const active = vm.id === selectedId;
  return (
    <button
      id={`arbol-vm-${vm.id}`}
      onClick={() => onSelect(vm.id)}
      className={`w-full flex items-center gap-2.5 py-1.5 pl-7 pr-2 rounded-lg text-left transition-colors group ${
        active ? 'bg-indigo-500/15 ring-1 ring-inset ring-indigo-500/40' : 'hover:bg-slate-800/70'
      }`}
      title="Ver ficha técnica"
    >
      <Monitor className={`w-3.5 h-3.5 flex-none transition-colors ${active ? 'text-indigo-400' : 'text-slate-600 group-hover:text-indigo-400'}`} />
      <span className={`font-mono text-[12.5px] truncate transition-colors ${active ? 'text-indigo-300' : 'text-slate-300 group-hover:text-indigo-300'}`}>
        {highlightMatch(vm.nombre, searchTerm)}
      </span>
      <span className="flex-1" />
      {powerKnown && (
        <Power
          className={`w-3 h-3 flex-none ${poweredOn ? 'text-emerald-400' : 'text-slate-600'}`}
          title={`Estado vCenter: ${vm.estado_vcenter}`}
        />
      )}
      {toolsKnown && (
        <span
          className={`w-1.5 h-1.5 rounded-full flex-none ${toolsOk ? 'bg-emerald-500' : 'bg-rose-500'}`}
          title={`VMware Tools: ${vm.tools_status}`}
        />
      )}
      {tipoBadge(vm.tipo_provisionamiento)}
    </button>
  );
}

// `open` controlado por React (isOpen), no por defaultOpen -- antes `open={defaultOpen}`
// reseteaba la carpeta a su estado inicial en cada re-render (ej. al seleccionar una VM
// en cualquier parte del árbol), cerrando de golpe lo que el usuario tenía abierto. Ahora
// el estado de apertura vive en ArbolPage (ver useNodeExpansion) y sobrevive cualquier
// re-render ajeno -- bug real, corregido 2026-09-07.
function Branch({ nodeKey, label, total, children, defaultOpen = false, isNodeOpen, onToggle }) {
  const open = isNodeOpen(nodeKey, defaultOpen);
  return (
    <details
      className="group"
      open={open}
      onToggle={(e) => {
        const isOpenNow = e.currentTarget.open;
        if (isOpenNow !== open) onToggle(nodeKey, defaultOpen, isOpenNow);
      }}
    >
      <summary className="flex items-center gap-2 py-2 px-2 rounded-lg cursor-pointer hover:bg-slate-800/70 list-none marker:content-none [&::-webkit-details-marker]:hidden select-none transition-colors">
        <ChevronRight className="w-3.5 h-3.5 text-slate-500 transition-transform duration-150 group-open:rotate-90 flex-none" />
        <Folder className="w-4 h-4 text-indigo-400 flex-none" />
        <span className="text-sm font-medium text-slate-200 truncate">{label}</span>
        <span className="flex-1" />
        <span className="text-[11px] text-slate-500 font-mono tabular-nums">{total}</span>
      </summary>
      <div className="ml-[7px] pl-3 border-l border-dashed border-slate-800 mt-0.5 mb-1 space-y-0.5">
        {children}
      </div>
    </details>
  );
}

function countNode(node) {
  let n = node.vms.length;
  for (const child of Object.values(node.children || {})) n += countNode(child);
  return n;
}

// Índice plano de {vm, ancestorKeys} para el buscador -- ancestorKeys son los mismos
// `nodeKey` que usa Branch/isNodeOpen, así el buscador puede forzar abiertas justo las
// carpetas que contienen una coincidencia, sin ocultar ni tocar el resto del árbol.
function indexRealTree(node, path, acc) {
  for (const vm of node.vms) {
    acc.push({ vm, ancestorKeys: path.map((_, i) => `real:${path.slice(0, i + 1).join('/')}`) });
  }
  for (const [name, child] of Object.entries(node.children || {})) {
    indexRealTree(child, [...path, name], acc);
  }
}

function indexProxyTree(proxy, acc) {
  if (proxy['Masters']) {
    for (const vm of proxy['Masters'].vms) acc.push({ vm, ancestorKeys: ['proxy:Masters'] });
  }
  if (proxy['Templates']) {
    for (const vm of proxy['Templates'].vms) acc.push({ vm, ancestorKeys: ['proxy:Templates'] });
  }
  if (proxy['VDI Pools']) {
    for (const [poolName, pd] of Object.entries(proxy['VDI Pools'].pools)) {
      for (const vm of pd.vms) acc.push({ vm, ancestorKeys: ['proxy:VDI Pools', `proxy:VDI Pools:${poolName}`] });
    }
  }
  if (proxy['VM Estáticas']) {
    for (const [cat, cd] of Object.entries(proxy['VM Estáticas'].categorias)) {
      for (const vm of cd.vms) acc.push({ vm, ancestorKeys: ['proxy:VM Estáticas', `proxy:VM Estáticas:${cat}`] });
    }
  }
  if (proxy['Sin clasificar']) {
    for (const vm of proxy['Sin clasificar'].vms) acc.push({ vm, ancestorKeys: ['proxy:Sin clasificar'] });
  }
}

function buildTreeIndex(nodo) {
  const acc = [];
  if (nodo?.real) indexRealTree(nodo.real, [], acc);
  if (nodo?.proxy) indexProxyTree(nodo.proxy, acc);
  return acc;
}

// Carpetas reales de vCenter (camino A) -- ruta capturada por SOAP, profundidad arbitraria.
function RealTreeNode({ node, name, path, selectedId, onSelect, depth, isNodeOpen, onToggle, searchTerm }) {
  const childNames = Object.keys(node.children || {});
  const nodeKey = `real:${path.join('/')}`;
  return (
    <Branch nodeKey={nodeKey} label={name} total={countNode(node)} defaultOpen={depth === 0} isNodeOpen={isNodeOpen} onToggle={onToggle}>
      {node.vms.map((vm) => <VmRow key={vm.id} vm={vm} selectedId={selectedId} onSelect={onSelect} searchTerm={searchTerm} />)}
      {childNames.map((cn) => (
        <RealTreeNode key={cn} node={node.children[cn]} name={cn} path={[...path, cn]} selectedId={selectedId} onSelect={onSelect} depth={depth + 1} isNodeOpen={isNodeOpen} onToggle={onToggle} searchTerm={searchTerm} />
      ))}
    </Branch>
  );
}

function RealTree({ root, selectedId, onSelect, isNodeOpen, onToggle, searchTerm }) {
  const topNames = Object.keys(root.children || {});
  return (
    <div className="space-y-0.5">
      {root.vms.map((vm) => <VmRow key={vm.id} vm={vm} selectedId={selectedId} onSelect={onSelect} searchTerm={searchTerm} />)}
      {topNames.map((n) => (
        <RealTreeNode key={n} node={root.children[n]} name={n} path={[n]} selectedId={selectedId} onSelect={onSelect} depth={0} isNodeOpen={isNodeOpen} onToggle={onToggle} searchTerm={searchTerm} />
      ))}
    </div>
  );
}

// Agrupación equivalente (camino B, respaldo) -- pool Horizon real / categoría estática
// real, para las VMs cuya carpeta real todavía no se capturó. "Sin clasificar" cubre VMs
// con tipo_provisionamiento vacío/inesperado, que antes desaparecían del árbol sin aviso
// (bug real, corregido 2026-09-07 -- ver _cond_categoria_estatica en api.py).
function ProxyTree({ proxy, selectedId, onSelect, isNodeOpen, onToggle, searchTerm }) {
  const pools = proxy['VDI Pools'];
  const estaticas = proxy['VM Estáticas'];
  const sinClasificar = proxy['Sin clasificar'];
  return (
    <div className="space-y-0.5">
      {proxy['Masters'] && (
        <Branch nodeKey="proxy:Masters" label="Masters" total={proxy['Masters'].total} isNodeOpen={isNodeOpen} onToggle={onToggle}>
          {proxy['Masters'].vms.map((vm) => <VmRow key={vm.id} vm={vm} selectedId={selectedId} onSelect={onSelect} searchTerm={searchTerm} />)}
        </Branch>
      )}
      {proxy['Templates'] && (
        <Branch nodeKey="proxy:Templates" label="Templates" total={proxy['Templates'].total} isNodeOpen={isNodeOpen} onToggle={onToggle}>
          {proxy['Templates'].vms.map((vm) => <VmRow key={vm.id} vm={vm} selectedId={selectedId} onSelect={onSelect} searchTerm={searchTerm} />)}
        </Branch>
      )}
      {pools && (
        <Branch nodeKey="proxy:VDI Pools" label="VDI Pools" total={pools.total} defaultOpen isNodeOpen={isNodeOpen} onToggle={onToggle}>
          {Object.entries(pools.pools).map(([poolName, pd]) => (
            <Branch key={poolName} nodeKey={`proxy:VDI Pools:${poolName}`} label={poolName} total={pd.total} isNodeOpen={isNodeOpen} onToggle={onToggle}>
              {pd.vms.map((vm) => <VmRow key={vm.id} vm={vm} selectedId={selectedId} onSelect={onSelect} searchTerm={searchTerm} />)}
            </Branch>
          ))}
        </Branch>
      )}
      {estaticas && (
        <Branch nodeKey="proxy:VM Estáticas" label="VM Estáticas" total={estaticas.total} isNodeOpen={isNodeOpen} onToggle={onToggle}>
          {Object.entries(estaticas.categorias).map(([cat, cd]) => (
            <Branch key={cat} nodeKey={`proxy:VM Estáticas:${cat}`} label={cat} total={cd.total} isNodeOpen={isNodeOpen} onToggle={onToggle}>
              {cd.vms.map((vm) => <VmRow key={vm.id} vm={vm} selectedId={selectedId} onSelect={onSelect} searchTerm={searchTerm} />)}
            </Branch>
          ))}
        </Branch>
      )}
      {sinClasificar && (
        <Branch nodeKey="proxy:Sin clasificar" label="Sin clasificar" total={sinClasificar.total} isNodeOpen={isNodeOpen} onToggle={onToggle}>
          {sinClasificar.vms.map((vm) => <VmRow key={vm.id} vm={vm} selectedId={selectedId} onSelect={onSelect} searchTerm={searchTerm} />)}
        </Branch>
      )}
    </div>
  );
}

function EmptyDetail() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-8 py-16">
      <div className="p-3 rounded-2xl bg-slate-800/60 border border-slate-800 text-slate-600 mb-3">
        <Monitor className="w-6 h-6" />
      </div>
      <p className="text-sm font-medium text-slate-400">Elegí una VM del árbol</p>
      <p className="text-[12.5px] text-slate-600 mt-1 max-w-[26ch]">Su ficha técnica, recursos y trazabilidad aparecen acá, sin salir de esta vista.</p>
    </div>
  );
}

export function ArbolPage() {
  const [activeOrigen, setActiveOrigen] = useState(null);
  const [selectedVmId, setSelectedVmId] = useState(null);
  // Vista Carpetas (VMs & Templates, pedido 2026-09-04) vs Cómputo (Datacenter/Cluster/
  // Host, agregado 2026-09-07) -- misma jerarquía de árbol, distinta ruta real de origen
  // (Maquina.folder vs Maquina.ruta_computo, ver core/vcenter_soap.py).
  const [vista, setVista] = useState('carpetas');

  // Nodos cuyo estado de apertura fue tocado manualmente (difiere de su defaultOpen) --
  // separado de selectedVmId a propósito, así seleccionar una VM nunca fuerza un
  // re-render que reabra/cierre carpetas (ver Branch más arriba).
  const [toggledKeys, setToggledKeys] = useState(() => new Set());
  const isNodeOpen = useCallback(
    (key, defaultOpen) => (toggledKeys.has(key) ? !defaultOpen : defaultOpen),
    [toggledKeys]
  );
  const handleToggle = useCallback((key, defaultOpen, isOpenNow) => {
    setToggledKeys((prev) => {
      const next = new Set(prev);
      if (isOpenNow === defaultOpen) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['inventario_arbol', vista],
    queryFn: () => api.get('/inventario/arbol', { params: { vista } }),
  });

  const origenes = data?.origenes || {};
  const origenIds = [
    ...ORDEN_ORIGENES.filter((o) => origenes[o]),
    ...Object.keys(origenes).filter((o) => !ORDEN_ORIGENES.includes(o)),
  ];

  useEffect(() => {
    if (!activeOrigen && origenIds.length) setActiveOrigen(origenIds[0]);
  }, [origenIds.join(','), activeOrigen]);

  const nodo = activeOrigen ? origenes[activeOrigen] : null;
  const tieneProxy = nodo && Object.keys(nodo.proxy || {}).length > 0;
  const tieneReal = nodo && nodo.real;

  // Buscador inteligente -- pedido 2026-09-08: buscar mientras se escribe y saltar a la
  // VM SIN ocultar el resto del árbol. Resalta cada coincidencia in-place, fuerza
  // abiertas las carpetas que las contienen (sin tocar toggledKeys -- ver Branch más
  // arriba, así al borrar la búsqueda el árbol vuelve exacto a como estaba) y Enter/
  // Shift+Enter navegan entre coincidencias como un buscador de página.
  const [treeSearch, setTreeSearch] = useState('');
  const [matchCursor, setMatchCursor] = useState(-1);
  const [jumpSeq, setJumpSeq] = useState(0);
  const treeScrollRef = useRef(null);
  const term = treeSearch.trim().toLowerCase();

  const treeIndex = useMemo(() => buildTreeIndex(nodo), [nodo]);
  const matches = useMemo(
    () => (term ? treeIndex.filter((e) => e.vm.nombre.toLowerCase().includes(term)) : []),
    [treeIndex, term]
  );
  const forceOpenKeys = useMemo(() => {
    const s = new Set();
    matches.forEach((e) => e.ancestorKeys.forEach((k) => s.add(k)));
    return s;
  }, [matches]);
  const activeMatch = matchCursor >= 0 && matches.length ? matches[Math.min(matchCursor, matches.length - 1)] : null;

  // Si esta pestaña no tiene coincidencias, avisa en cuáles otras sí hay -- la VM
  // buscada puede estar en otro vCenter (DT/MZ/SU/CORE) sin que se note a simple vista.
  const otherTabHints = useMemo(() => {
    if (!term || matches.length > 0) return [];
    return origenIds
      .filter((o) => o !== activeOrigen)
      .map((o) => ({ o, count: buildTreeIndex(origenes[o]).filter((e) => e.vm.nombre.toLowerCase().includes(term)).length }))
      .filter((h) => h.count > 0);
  }, [term, matches.length, origenIds.join(','), origenes, activeOrigen]);

  useEffect(() => { setMatchCursor(-1); }, [term, activeOrigen]);

  useEffect(() => {
    if (!activeMatch) return;
    setSelectedVmId(activeMatch.vm.id);
    const el = treeScrollRef.current?.querySelector(`#arbol-vm-${activeMatch.vm.id}`);
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpSeq]);

  const jumpToMatch = useCallback((delta) => {
    if (!matches.length) return;
    setMatchCursor((prev) => {
      if (prev < 0) return delta >= 0 ? 0 : matches.length - 1;
      return (prev + delta + matches.length) % matches.length;
    });
    setJumpSeq((s) => s + 1);
  }, [matches.length]);

  const handleSearchKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      jumpToMatch(e.shiftKey ? -1 : 1);
    } else if (e.key === 'Escape') {
      setTreeSearch('');
    }
  };

  const isNodeOpenConSearch = useCallback(
    (key, defaultOpen) => (term && forceOpenKeys.has(key) ? true : isNodeOpen(key, defaultOpen)),
    [term, forceOpenKeys, isNodeOpen]
  );

  return (
    <div className="flex flex-col gap-4 lg:h-[calc(100vh-140px)] lg:min-h-[560px]">
      <div className="flex items-center gap-3 shrink-0">
        <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex-none">
          <FolderTree className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <h1 className="text-base font-bold text-slate-100">
            {vista === 'computo' ? 'Árbol de Cómputo por vCenter' : 'Árbol de Carpetas por vCenter'}
          </h1>
          <p className="text-[12.5px] text-slate-500 truncate">
            {vista === 'computo'
              ? 'Jerarquía real Datacenter / Cluster / Host por DT / MZ / SU / CORE — capturada por SOAP donde ya se extrajo.'
              : 'Organización real de vSphere Client por DT / MZ / SU / CORE — carpeta real capturada por SOAP donde ya se extrajo, agrupación por pool/categoría como respaldo.'}
          </p>
        </div>
        <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 rounded-lg p-0.5 ml-auto flex-none">
          <button
            onClick={() => setVista('carpetas')}
            className={`px-2.5 py-1.5 rounded-md text-[11.5px] font-semibold flex items-center gap-1.5 transition-colors ${
              vista === 'carpetas' ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-500 hover:text-slate-300'
            }`}
            title="Vista Carpetas (VMs & Templates)"
          >
            <FolderTree className="w-3.5 h-3.5" /> Carpetas
          </button>
          <button
            onClick={() => setVista('computo')}
            className={`px-2.5 py-1.5 rounded-md text-[11.5px] font-semibold flex items-center gap-1.5 transition-colors ${
              vista === 'computo' ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-500 hover:text-slate-300'
            }`}
            title="Vista Cómputo (Datacenter/Cluster/Host)"
          >
            <Server className="w-3.5 h-3.5" /> Cómputo
          </button>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors flex-none"
          title="Actualizar"
        >
          <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {isLoading ? (
        <Card>
          <div className="animate-pulse space-y-2">
            {[1, 2, 3, 4, 5].map((i) => <div key={i} className="h-9 bg-slate-800/50 rounded-lg" />)}
          </div>
        </Card>
      ) : (
        <div className="flex flex-col lg:flex-row gap-4 flex-1 min-h-0">
          {/* Panel izquierdo: árbol -- div propio, no <Card> (su p-5 fijo pisaría el
              padding manual de cada sección acá; ver panel derecho, mismo motivo) */}
          <div className="glass-panel rounded-xl shadow-xl transition-all duration-200 border border-slate-800/80 hover:border-slate-700/60 w-full lg:w-[400px] shrink-0 overflow-hidden flex flex-col lg:min-h-0">
            <div className="flex gap-1 px-3 pt-3 border-b border-slate-800/80 overflow-x-auto shrink-0">
              {origenIds.map((o) => (
                <button
                  key={o}
                  onClick={() => setActiveOrigen(o)}
                  className={`font-mono text-[12.5px] font-semibold px-3.5 py-2 rounded-t-lg flex items-center gap-2 whitespace-nowrap transition-colors border-b-2 -mb-px ${
                    activeOrigen === o
                      ? 'text-indigo-400 border-indigo-500 bg-indigo-500/5'
                      : 'text-slate-500 border-transparent hover:text-slate-300'
                  }`}
                >
                  {ORIGIN_LABEL[o] || o.toUpperCase()}
                  <span className="text-[10px] text-slate-600 bg-slate-800 rounded-full px-1.5 py-0.5 tabular-nums">
                    {origenes[o].total}
                  </span>
                </button>
              ))}
            </div>

            {nodo && (
              <>
                <div className="px-3 py-2 border-b border-slate-800/60 shrink-0">
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      type="text"
                      value={treeSearch}
                      onChange={(e) => setTreeSearch(e.target.value)}
                      onKeyDown={handleSearchKeyDown}
                      placeholder="Buscar VM por nombre... (Enter salta a la próxima)"
                      className="w-full bg-slate-900 border border-slate-800 rounded-lg pl-8 pr-[88px] py-1.5 text-[12.5px] text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-indigo-500"
                    />
                    {treeSearch && (
                      <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
                        <span className="text-[10px] text-slate-500 font-mono tabular-nums px-1 min-w-[32px] text-center">
                          {matches.length ? `${matchCursor >= 0 ? matchCursor + 1 : '–'}/${matches.length}` : '0'}
                        </span>
                        <button
                          onClick={() => jumpToMatch(-1)}
                          disabled={!matches.length}
                          className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-200 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
                          title="Coincidencia anterior (Shift+Enter)"
                        >
                          <ChevronUp className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => jumpToMatch(1)}
                          disabled={!matches.length}
                          className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-200 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
                          title="Siguiente coincidencia (Enter)"
                        >
                          <ChevronDown className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => setTreeSearch('')}
                          className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-200 transition-colors"
                          title="Limpiar (Esc)"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    )}
                  </div>
                  {term && matches.length === 0 && (
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      {otherTabHints.length > 0 ? (
                        <>
                          <span className="text-[11px] text-slate-600">Sin coincidencias acá, pero sí en:</span>
                          {otherTabHints.map(({ o, count }) => (
                            <button
                              key={o}
                              onClick={() => setActiveOrigen(o)}
                              className="text-[10.5px] font-semibold px-2 py-0.5 rounded-lg bg-amber-500/10 text-amber-300 border border-amber-500/25 hover:bg-amber-500/20 transition-colors"
                            >
                              {count} en {ORIGIN_LABEL[o] || o.toUpperCase()} →
                            </button>
                          ))}
                        </>
                      ) : (
                        <span className="text-[11px] text-slate-600">Sin coincidencias.</span>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-1.5 px-3 py-2 border-b border-slate-800/60 text-[11px] text-slate-500 shrink-0">
                  {tieneReal ? (
                    <>
                      <CheckCircle2 className="w-3 h-3 text-emerald-400 flex-none" />
                      <span><b className="text-slate-300 font-mono">{nodo.con_carpeta_real}</b>/{nodo.total} con {vista === 'computo' ? 'ruta de cómputo real' : 'carpeta real'}</span>
                    </>
                  ) : (
                    <>
                      <Info className="w-3 h-3 text-amber-400 flex-none" />
                      <span>{vista === 'computo' ? 'Topología de cómputo aún no capturada' : 'Carpeta real aún no capturada'} — agrupación por pool/categoría</span>
                    </>
                  )}
                </div>

                <div className="flex-1 overflow-y-auto p-2.5" ref={treeScrollRef}>
                  {tieneReal && (
                    <div className="mb-1">
                      <div className="text-[10.5px] font-semibold text-slate-600 uppercase tracking-wide px-2 mb-1">
                        {vista === 'computo' ? 'Datacenter / Cluster / Host' : 'Carpetas reales'}
                      </div>
                      <RealTree root={nodo.real} selectedId={selectedVmId} onSelect={setSelectedVmId} isNodeOpen={isNodeOpenConSearch} onToggle={handleToggle} searchTerm={term} />
                    </div>
                  )}
                  {tieneProxy && (
                    <div>
                      {tieneReal && (
                        <div className="text-[10.5px] font-semibold text-slate-600 uppercase tracking-wide px-2 mb-1 mt-3">
                          {vista === 'computo' ? 'Sin topología de cómputo capturada' : 'Sin carpeta capturada'}
                        </div>
                      )}
                      <ProxyTree proxy={nodo.proxy} selectedId={selectedVmId} onSelect={setSelectedVmId} isNodeOpen={isNodeOpenConSearch} onToggle={handleToggle} searchTerm={term} />
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Panel derecho: ficha de la VM seleccionada -- mismo lugar, nunca navega afuera */}
          <div className="glass-panel rounded-xl shadow-xl transition-all duration-200 border border-slate-800/80 hover:border-slate-700/60 flex-1 overflow-hidden flex flex-col lg:min-h-0">
            {selectedVmId ? (
              <VmDetailPanel vmId={selectedVmId} onClose={() => setSelectedVmId(null)} />
            ) : (
              <EmptyDetail />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
