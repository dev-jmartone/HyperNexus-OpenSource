import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Sprout, Server, AppWindow, Users, Search, ChevronRight, Download } from 'lucide-react';
import { GranjaFarmModal } from '../components/modals/GranjaFarmModal';
import { GranjaAppModal } from '../components/modals/GranjaAppModal';
import { estadoDirectorioLabel } from '../utils/directorioEstado';
import { exportRecursosExcel } from '../utils/excelExport';

const KPI_STYLES = {
  emerald: { bg: 'bg-emerald-500/10 border-emerald-500/20 hover:border-emerald-500/50', color: 'text-emerald-400' },
  indigo: { bg: 'bg-indigo-500/10 border-indigo-500/20 hover:border-indigo-500/50', color: 'text-indigo-400' },
  sky: { bg: 'bg-sky-500/10 border-sky-500/20 hover:border-sky-500/50', color: 'text-sky-400' },
  amber: { bg: 'bg-amber-500/10 border-amber-500/20 hover:border-amber-500/50', color: 'text-amber-400' },
};

function KpiTile({ label, value, sub, icon: Icon, tone, onClick }) {
  const s = KPI_STYLES[tone];
  return (
    <div
      onClick={onClick}
      className={`p-4 rounded-xl border ${s.bg} flex flex-col justify-between transition-all hover:scale-[1.02] cursor-pointer group`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-400 group-hover:text-slate-200 transition-colors">{label}</span>
        <Icon className={`w-5 h-5 ${s.color}`} />
      </div>
      <div className="mt-3">
        <div className="text-2xl font-bold text-slate-100 tracking-tight tabular-nums">{value}</div>
        <div className="flex items-center justify-between mt-1">
          <p className="text-[11px] text-slate-400">{sub}</p>
          <span className={`text-[10px] font-medium ${s.color} group-hover:underline`}>Ver →</span>
        </div>
      </div>
    </div>
  );
}

/** Agrupa filas planas (ya filtradas o no) de vuelta en "recursos" para el export a
 * Excel -- cada fila guarda el auth crudo (row.raw, shape AplicacionEntitlement o
 * PoolEntitlement + directorio) así no hay que reconstruir nada, solo reagrupar. */
function agruparEnRecursos(rows) {
  const map = new Map();
  rows.forEach((row) => {
    const key = `${row.recursoType}-${row.farmId}-${row.recurso}`;
    if (!map.has(key)) {
      map.set(key, { nombre: row.recurso, tipoRecurso: row.recursoType === 'pool' ? 'Pool RDS' : 'Aplicación', farm: row.farm, entries: [] });
    }
    map.get(key).entries.push(row.raw);
  });
  return Array.from(map.values());
}

export function GranjaPage() {
  const [tab, setTab] = useState('farms');
  const [search, setSearch] = useState('');
  const [authFilters, setAuthFilters] = useState({ farmId: 'all', tipoEnt: 'all' });
  const [modal, setModal] = useState(null); // {type:'farm', farmId} | {type:'app', appId, fromFarmId} | null

  const { data, isLoading } = useQuery({
    queryKey: ['granja_farms'],
    queryFn: () => api.get('/granja/farms'),
  });
  const { data: appsData } = useQuery({
    queryKey: ['granja_aplicaciones'],
    queryFn: () => api.get('/granja/aplicaciones'),
  });

  const farms = data?.items || [];
  const aplicaciones = appsData?.items || [];

  const appsByFarmId = useMemo(() => {
    const map = {};
    for (const a of aplicaciones) {
      const key = a.farm_id || 'sin_farm';
      if (!map[key]) map[key] = [];
      map[key].push(a);
    }
    return map;
  }, [aplicaciones]);

  const farmById = useMemo(() => Object.fromEntries(farms.map((f) => [f.id, f])), [farms]);
  const appById = useMemo(() => Object.fromEntries(aplicaciones.map((a) => [a.id, a])), [aplicaciones]);

  // Filas planas de autorizaciones (app-level + Pool RDS heredadas por farm), para el
  // tab "Autorizaciones" -- reemplaza el acordeón anidado por app individual.
  const flatAuthRows = useMemo(() => {
    const rows = [];
    aplicaciones.forEach((app) => {
      (app.autorizaciones_locales || []).forEach((a, idx) => rows.push({
        id: `app-${app.id}-l-${idx}`, recurso: app.display_name, recursoType: 'app', appId: app.id,
        farmId: app.farm_id, farm: app.farm_nombre, usuario: a.usuario_o_grupo, tipo: 'Local', estado: estadoDirectorioLabel(a), raw: a,
      }));
      (app.autorizaciones_globales || []).forEach((a, idx) => rows.push({
        id: `app-${app.id}-g-${idx}`, recurso: app.display_name, recursoType: 'app', appId: app.id,
        farmId: app.farm_id, farm: app.farm_nombre, usuario: a.usuario_o_grupo, tipo: 'Global', estado: estadoDirectorioLabel(a), raw: a,
      }));
    });
    farms.forEach((farm) => {
      (farm.autorizados || []).filter((au) => (au.origen_recurso || '').startsWith('Pool RDS')).forEach((a, idx) => rows.push({
        id: `pool-${farm.id}-${idx}`, recurso: a.origen_recurso.replace(/^Pool RDS:\s*/, ''), recursoType: 'pool', farmId: farm.id,
        farm: farm.display_name, usuario: a.usuario_o_grupo, tipo: a.tipo_entitlement, estado: estadoDirectorioLabel(a), raw: a,
      }));
    });
    return rows;
  }, [aplicaciones, farms]);

  const farmsFiltradas = farms.filter((f) => {
    if (!search) return true;
    const q = search.toLowerCase();
    const matchFarm = (f.nombre || '').toLowerCase().includes(q) || (f.display_name || '').toLowerCase().includes(q);
    const matchApp = (appsByFarmId[f.id] || []).some((a) => (a.nombre || '').toLowerCase().includes(q) || (a.display_name || '').toLowerCase().includes(q));
    return matchFarm || matchApp;
  });

  const authRowsFiltradas = flatAuthRows.filter((r) => {
    if (authFilters.farmId !== 'all' && r.farmId !== authFilters.farmId) return false;
    if (authFilters.tipoEnt !== 'all' && r.tipo !== authFilters.tipoEnt) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!(r.recurso.toLowerCase().includes(q) || r.usuario.toLowerCase().includes(q) || (r.farm || '').toLowerCase().includes(q))) return false;
    }
    return true;
  });

  const totalApps = aplicaciones.length;
  const totalRdsServers = farms.reduce((acc, f) => acc + (f.rds_servers?.length || 0), 0);
  const totalAutorizados = farms.reduce((acc, f) => acc + (f.autorizados?.length || 0), 0);

  const openFarm = (farmId) => setModal({ type: 'farm', farmId });
  const openApp = (appId, fromFarmId = null) => setModal({ type: 'app', appId, fromFarmId });
  const closeModal = () => setModal(null);

  const filterPillClass = (active) =>
    `border px-3 py-1 rounded-full text-[11.5px] font-semibold transition-colors ${active ? 'bg-indigo-500/15 border-indigo-500/40 text-indigo-300' : 'border-slate-800 text-slate-400 hover:text-slate-200'}`;

  const exportGlobal = () => exportRecursosExcel({
    filenameBase: 'autorizaciones_granja_completo',
    titulo: 'Granja RDS & Aplicaciones — Autorizaciones (completo)',
    recursos: agruparEnRecursos(flatAuthRows),
  });
  const exportFiltrado = () => exportRecursosExcel({
    filenameBase: 'autorizaciones_granja_filtradas',
    titulo: 'Granja RDS & Aplicaciones — Autorizaciones (filtradas)',
    subtitulo: `Filtros: Farm=${authFilters.farmId === 'all' ? 'Todas' : farmById[authFilters.farmId]?.display_name}, Tipo=${authFilters.tipoEnt === 'all' ? 'Todas' : authFilters.tipoEnt}${search ? `, Búsqueda="${search}"` : ''}`,
    recursos: agruparEnRecursos(authRowsFiltradas),
  });

  const modalFarm = modal?.type === 'farm' ? farmById[modal.farmId] : null;
  const modalApp = modal?.type === 'app' ? appById[modal.appId] : null;
  const modalAppFromFarm = modal?.type === 'app' && modal.fromFarmId ? farmById[modal.fromFarmId] : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Sprout className="w-5 h-5 text-emerald-400" /> Granja RDS & Aplicaciones
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Farms, aplicaciones publicadas, RDS Servers y autorizados por recurso — Horizon DT/MZ.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar granja, app o usuario..."
              className="bg-slate-900 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-200 w-72"
            />
          </div>
          <button
            onClick={exportGlobal}
            className="inline-flex items-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors"
          >
            <Download className="w-3.5 h-3.5" /> Exportar Excel
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiTile label="Farms" value={farms.length} sub="Granjas RDS activas" icon={Sprout} tone="emerald" onClick={() => setTab('farms')} />
        <KpiTile label="Aplicaciones" value={totalApps} sub="Publicadas en total" icon={AppWindow} tone="indigo" onClick={() => setTab('farms')} />
        <KpiTile label="RDS Servers" value={totalRdsServers} sub="En todas las farms" icon={Server} tone="sky" onClick={() => setTab('farms')} />
        <KpiTile label="Autorizados" value={totalAutorizados} sub="Usuarios y grupos únicos" icon={Users} tone="amber" onClick={() => setTab('auth')} />
      </div>

      <div className="inline-flex p-1 bg-slate-900 border border-slate-800 rounded-xl gap-0.5">
        <button
          onClick={() => setTab('farms')}
          className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${tab === 'farms' ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}
        >
          Farms
        </button>
        <button
          onClick={() => setTab('auth')}
          className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${tab === 'auth' ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}
        >
          Autorizaciones ({flatAuthRows.length})
        </button>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-slate-400 animate-pulse text-sm">Cargando granjas...</div>
      ) : tab === 'farms' ? (
        farmsFiltradas.length === 0 ? (
          <div className="py-12 text-center text-slate-500 text-sm">Ninguna granja coincide con la búsqueda.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {farmsFiltradas.map((farm) => {
              const apps = appsByFarmId[farm.id] || [];
              return (
                <div
                  key={farm.id}
                  onClick={() => openFarm(farm.id)}
                  className="glass-panel rounded-xl p-5 border border-slate-800/80 hover:border-slate-700 hover:shadow-xl transition-all cursor-pointer"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
                        <Sprout className="w-4 h-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-bold text-slate-100 truncate">{farm.display_name}</div>
                        <div className="text-[11px] text-slate-500 font-mono">{farm.nombre} · {farm.origen}</div>
                      </div>
                    </div>
                    {farm.enabled ? (
                      <span className="shrink-0 text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">HABILITADA</span>
                    ) : (
                      <span className="shrink-0 text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20">DESHABILITADA</span>
                    )}
                  </div>

                  <div className="flex items-center gap-4 mt-4 pt-3.5 border-t border-slate-800 text-xs text-slate-400">
                    <span className="flex items-center gap-1.5"><AppWindow className="w-3.5 h-3.5 text-indigo-400" /> <b className="text-slate-200">{apps.length}</b> apps</span>
                    <span className="flex items-center gap-1.5"><Server className="w-3.5 h-3.5 text-sky-400" /> <b className="text-slate-200">{farm.rds_servers.length}</b> RDS</span>
                    <span className="flex items-center gap-1.5"><Users className="w-3.5 h-3.5 text-amber-400" /> <b className="text-slate-200">{farm.autorizados.length}</b> autorizados</span>
                  </div>

                  {farm.pool_enlazado && (
                    <div className="mt-3 inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                      Pool RDS: {farm.pool_enlazado.nombre}
                    </div>
                  )}

                  <div className="mt-4 flex items-center justify-end gap-1 text-xs font-semibold text-indigo-400">
                    Ver detalle <ChevronRight className="w-3.5 h-3.5" />
                  </div>
                </div>
              );
            })}
          </div>
        )
      ) : (
        <div className="space-y-3">
          <div className="glass-panel rounded-xl border border-slate-800/80 p-4 flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[11px] font-bold text-slate-500 uppercase mr-1">Farm</span>
              <button onClick={() => setAuthFilters((p) => ({ ...p, farmId: 'all' }))} className={filterPillClass(authFilters.farmId === 'all')}>Todas</button>
              {farms.map((f) => (
                <button key={f.id} onClick={() => setAuthFilters((p) => ({ ...p, farmId: f.id }))} className={filterPillClass(authFilters.farmId === f.id)}>{f.display_name}</button>
              ))}
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-bold text-slate-500 uppercase mr-1">Tipo</span>
              <button onClick={() => setAuthFilters((p) => ({ ...p, tipoEnt: 'all' }))} className={filterPillClass(authFilters.tipoEnt === 'all')}>Todas</button>
              <button onClick={() => setAuthFilters((p) => ({ ...p, tipoEnt: 'Local' }))} className={filterPillClass(authFilters.tipoEnt === 'Local')}>Local</button>
              <button onClick={() => setAuthFilters((p) => ({ ...p, tipoEnt: 'Global' }))} className={filterPillClass(authFilters.tipoEnt === 'Global')}>Global</button>
            </div>
            <div className="flex items-center gap-3 ml-auto">
              <span className="text-[11.5px] text-slate-500">Mostrando <b className="text-slate-200 tabular-nums">{authRowsFiltradas.length}</b> de {flatAuthRows.length}</span>
              <button onClick={exportFiltrado} className="inline-flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 rounded-lg px-3 py-1.5 text-[11.5px] font-semibold transition-colors">
                <Download className="w-3 h-3" /> Exportar
              </button>
            </div>
          </div>

          {authRowsFiltradas.length === 0 ? (
            <div className="py-16 text-center text-slate-500 text-sm glass-panel rounded-xl border border-slate-800/80">Ninguna autorización coincide con los filtros elegidos.</div>
          ) : (
            <div className="glass-panel rounded-xl border border-slate-800/80 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300 border-collapse">
                  <thead className="bg-slate-950/60 uppercase text-[10px] text-slate-500 font-bold border-b border-slate-800">
                    <tr>
                      <th className="py-2.5 px-4">Recurso</th>
                      <th className="py-2.5 px-4">Farm</th>
                      <th className="py-2.5 px-4">Usuario / Grupo</th>
                      <th className="py-2.5 px-4">Tipo</th>
                      <th className="py-2.5 px-4">Directorio</th>
                      <th className="py-2.5 px-4"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {authRowsFiltradas.slice(0, 300).map((row) => (
                      <tr key={row.id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="py-2 px-4 font-semibold text-slate-100 whitespace-nowrap">
                          <span className="flex items-center gap-1.5">
                            {row.recursoType === 'pool' ? <Server className="w-3.5 h-3.5 text-indigo-300" /> : <AppWindow className="w-3.5 h-3.5 text-indigo-400" />}
                            {row.recurso}
                          </span>
                        </td>
                        <td className="py-2 px-4 text-slate-400 whitespace-nowrap">{row.farm}</td>
                        <td className="py-2 px-4 text-slate-200 whitespace-nowrap">{row.usuario}</td>
                        <td className="py-2 px-4 whitespace-nowrap">
                          <span className={`text-[10.5px] font-bold px-2 py-0.5 rounded-full border ${row.tipo === 'Global' ? 'bg-purple-500/10 text-purple-400 border-purple-500/20' : 'bg-slate-800 text-slate-300 border-slate-700'}`}>{row.tipo}</span>
                        </td>
                        <td className="py-2 px-4 text-slate-400 whitespace-nowrap">{row.estado}</td>
                        <td className="py-2 px-4 text-right whitespace-nowrap">
                          <button
                            onClick={() => (row.recursoType === 'app' ? openApp(row.appId) : openFarm(row.farmId))}
                            className="text-indigo-400 hover:text-indigo-300 text-[11px] font-semibold"
                          >
                            Ver
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {authRowsFiltradas.length > 300 && (
                <div className="py-2.5 text-center text-[11px] text-slate-500 border-t border-slate-800/60">
                  Mostrando las primeras 300 de {authRowsFiltradas.length} — afiná la búsqueda o los filtros para ver el resto.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {modalFarm && (
        <GranjaFarmModal
          farm={modalFarm}
          apps={appsByFarmId[modalFarm.id] || []}
          poolAuthRows={(modalFarm.autorizados || []).filter((au) => (au.origen_recurso || '').startsWith('Pool RDS'))}
          onClose={closeModal}
          onOpenApp={(appId) => openApp(appId, modalFarm.id)}
          onViewPoolAuth={() => {
            setAuthFilters({ farmId: modalFarm.id, tipoEnt: 'all' });
            setTab('auth');
            closeModal();
          }}
        />
      )}

      {modalApp && (
        <GranjaAppModal
          app={modalApp}
          fromFarmName={modalAppFromFarm?.display_name || null}
          onBack={() => setModal({ type: 'farm', farmId: modalAppFromFarm.id })}
          onClose={closeModal}
        />
      )}
    </div>
  );
}
