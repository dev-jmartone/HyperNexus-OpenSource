import React from 'react';
import { X, Server, AppWindow, Layers, ChevronRight, Download } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { exportRecursosExcel } from '../../utils/excelExport';
import { slugify } from '../../utils/csvExport';

function estadoRdsVariant(estado) {
  const e = (estado || '').toUpperCase();
  if (e === 'AVAILABLE') return 'success';
  if (e === 'ERROR' || e === 'UNREACHABLE') return 'danger';
  if (e === 'MAINTENANCE') return 'warning';
  return 'neutral';
}

/** Modal de detalle de una Farm: RDS Servers, apps publicadas (con drill-down a
 * GranjaAppModal) y el Pool RDS enlazado, si tiene. Mismo shape de datos que la vieja
 * GranjaPage.jsx (apps vienen enriquecidas desde /granja/aplicaciones, no desde
 * farm.aplicaciones -- ese array no trae total_autorizaciones). */
export function GranjaFarmModal({ farm, apps, poolAuthRows, onClose, onOpenApp, onViewPoolAuth }) {
  if (!farm) return null;

  const handleExport = () => {
    const recursos = apps.map((app) => ({
      nombre: app.display_name, tipoRecurso: 'Aplicación', farm: farm.display_name,
      entries: [...(app.autorizaciones_locales || []), ...(app.autorizaciones_globales || [])],
    }));
    if (farm.pool_enlazado && (poolAuthRows || []).length > 0) {
      recursos.push({ nombre: farm.pool_enlazado.nombre, tipoRecurso: 'Pool RDS', farm: farm.display_name, entries: poolAuthRows });
    }
    exportRecursosExcel({
      filenameBase: `autorizaciones_${slugify(farm.display_name)}`,
      titulo: `Farm ${farm.display_name} — Autorizaciones`,
      recursos,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-3xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        <div className="p-4 px-6 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
              <Layers className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-bold text-slate-100 truncate">{farm.display_name}</h2>
              <p className="text-xs text-slate-500 font-mono">{farm.nombre} · {farm.origen} · {farm.tipo}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors shrink-0">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          <div>
            <h4 className="text-xs font-bold text-slate-400 uppercase mb-2">RDS Servers ({farm.rds_servers.length})</h4>
            {farm.rds_servers.length === 0 ? (
              <p className="text-xs text-slate-500">Sin RDS Servers detectados para esta granja.</p>
            ) : (
              <div className="rounded-xl border border-slate-800 overflow-hidden divide-y divide-slate-800/60">
                {farm.rds_servers.map((rs) => (
                  <div key={rs.id} className="flex items-center justify-between px-4 py-2.5 text-xs bg-slate-900/60 hover:bg-slate-800/40 transition-colors">
                    <span className="text-slate-200 font-mono font-semibold">{rs.nombre}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-500">{rs.sesiones_activas} sesión(es)</span>
                      <Badge variant={estadoRdsVariant(rs.estado)}>{rs.estado || '—'}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <h4 className="text-xs font-bold text-slate-400 uppercase mb-2">Aplicaciones publicadas ({apps.length})</h4>
            {apps.length === 0 ? (
              <p className="text-xs text-slate-500">Sin aplicaciones publicadas en esta granja.</p>
            ) : (
              <div className="space-y-1.5">
                {apps.map((app) => (
                  <button
                    key={app.id}
                    onClick={() => onOpenApp(app.id)}
                    className="w-full flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg bg-slate-800/30 hover:bg-slate-800/60 transition-colors text-left"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <AppWindow className="w-4 h-4 text-indigo-400 shrink-0" />
                      <div className="min-w-0">
                        <div className="text-xs font-semibold text-slate-200">{app.display_name}</div>
                        <div className="text-[10px] text-slate-500 font-mono truncate max-w-[280px]">{app.path_ejecutable}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge variant="info">{app.total_autorizaciones} autorizado(s)</Badge>
                      <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {farm.pool_enlazado && (
            <div>
              <h4 className="text-xs font-bold text-slate-400 uppercase mb-2">Pool RDS enlazado (autorizaciones heredadas)</h4>
              <button
                onClick={onViewPoolAuth}
                className="w-full flex items-center justify-between px-4 py-3 rounded-xl bg-indigo-500/5 border border-indigo-500/20 hover:border-indigo-500/40 transition-colors text-left"
              >
                <div className="flex items-center gap-2.5">
                  <Server className="w-4 h-4 text-indigo-300" />
                  <div>
                    <div className="text-xs font-semibold text-slate-200">{farm.pool_enlazado.nombre}</div>
                    <div className="text-[11px] text-slate-500">{farm.pool_enlazado.display_name}</div>
                  </div>
                </div>
                <Badge variant="info">{(poolAuthRows || []).length} heredadas</Badge>
              </button>
            </div>
          )}
        </div>

        <div className="p-3 px-6 bg-slate-950/50 border-t border-slate-800 flex justify-end gap-2">
          <Button variant="secondary" size="sm" icon={Download} onClick={handleExport}>Exportar Excel de esta Farm</Button>
          <Button variant="secondary" size="sm" onClick={onClose}>Cerrar</Button>
        </div>
      </div>
    </div>
  );
}
