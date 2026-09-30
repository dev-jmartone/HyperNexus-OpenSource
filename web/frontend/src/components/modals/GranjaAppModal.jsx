import React, { useState, useMemo } from 'react';
import { X, AppWindow, UserCheck, Globe, ArrowLeft, Search, Download, ShieldCheck, ShieldAlert } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { slugify } from '../../utils/csvExport';
import { exportRecursosExcel } from '../../utils/excelExport';

function AuthRow({ auth }) {
  return (
    <div className="flex items-center justify-between text-xs bg-slate-950/60 rounded-lg px-3 py-2">
      <span className="text-slate-200">{auth.usuario_o_grupo}</span>
      {auth.es_grupo ? (
        <Badge variant="neutral">Grupo AD</Badge>
      ) : auth.directorio ? (
        auth.directorio.activo_ad ? (
          <Badge variant="success"><ShieldCheck className="w-3 h-3 mr-1 inline" />{auth.directorio.nombre_completo}</Badge>
        ) : (
          <Badge variant="danger"><ShieldAlert className="w-3 h-3 mr-1 inline" />Inactivo en AD</Badge>
        )
      ) : (
        <Badge variant="warning">No encontrado en Directorio</Badge>
      )}
    </div>
  );
}

/** Modal de detalle de autorizaciones de una Aplicación publicada (Locales/Globales).
 * fromFarmName presente = se abrió desde GranjaFarmModal -> muestra breadcrumb "volver". */
export function GranjaAppModal({ app, fromFarmName, onBack, onClose }) {
  const [search, setSearch] = useState('');

  const locales = useMemo(() => {
    const lista = app.autorizaciones_locales || [];
    if (!search) return lista;
    const q = search.toLowerCase();
    return lista.filter((a) => (a.usuario_o_grupo || '').toLowerCase().includes(q));
  }, [app, search]);

  const globales = useMemo(() => {
    const lista = app.autorizaciones_globales || [];
    if (!search) return lista;
    const q = search.toLowerCase();
    return lista.filter((a) => (a.usuario_o_grupo || '').toLowerCase().includes(q));
  }, [app, search]);

  if (!app) return null;

  const handleExport = () => {
    exportRecursosExcel({
      filenameBase: `autorizaciones_${slugify(app.display_name)}`,
      titulo: `${app.display_name} — Autorizaciones`,
      recursos: [{
        nombre: app.display_name, tipoRecurso: 'Aplicación', farm: app.farm_nombre || fromFarmName || '',
        entries: [...(app.autorizaciones_locales || []), ...(app.autorizaciones_globales || [])],
      }],
    });
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        <div className="p-4 px-6 border-b border-slate-800 bg-slate-950/50">
          {fromFarmName && (
            <button onClick={onBack} className="flex items-center gap-1 text-[11px] font-semibold text-indigo-400 hover:text-indigo-300 mb-2.5">
              <ArrowLeft className="w-3 h-3" /> {fromFarmName}
            </button>
          )}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <div className="p-2 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 shrink-0">
                <AppWindow className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-bold text-slate-100 truncate">{app.display_name}</h2>
                <p className="text-[11px] text-slate-500 font-mono truncate max-w-[380px]">{app.path_ejecutable}</p>
              </div>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors shrink-0">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="p-3 px-6 border-b border-slate-800/80">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filtrar usuarios o grupos de esta app..."
              className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          <div className="space-y-2">
            <div className="text-[10px] font-bold text-slate-500 uppercase flex items-center gap-1">
              <UserCheck className="w-3 h-3" /> Locales ({(app.autorizaciones_locales || []).length})
            </div>
            <div className="space-y-1">
              {locales.map((a, idx) => <AuthRow key={`l-${idx}`} auth={a} />)}
              {locales.length === 0 && <p className="text-xs text-slate-500 italic px-1">Sin autorizaciones locales para este filtro.</p>}
            </div>
          </div>
          <div className="space-y-2">
            <div className="text-[10px] font-bold text-slate-500 uppercase flex items-center gap-1">
              <Globe className="w-3 h-3" /> Globales ({(app.autorizaciones_globales || []).length})
            </div>
            <div className="space-y-1">
              {globales.map((a, idx) => <AuthRow key={`g-${idx}`} auth={a} />)}
              {globales.length === 0 && <p className="text-xs text-slate-500 italic px-1">Sin autorizaciones globales para este filtro.</p>}
            </div>
          </div>
        </div>

        <div className="p-3 px-6 bg-slate-950/50 border-t border-slate-800 flex justify-end gap-2">
          <Button variant="secondary" size="sm" icon={Download} onClick={handleExport}>Exportar Excel</Button>
          <Button variant="secondary" size="sm" onClick={onClose}>Cerrar</Button>
        </div>
      </div>
    </div>
  );
}
