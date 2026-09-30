import React from 'react';
import { useDashboardStore } from '../../store/useDashboardStore';
import { Button } from '../ui/Button';
import { X, Check, RotateCcw, Eye, EyeOff, LayoutGrid } from 'lucide-react';

export function DashboardCustomizer() {
  const {
    widgets,
    isCustomizing,
    setCustomizing,
    toggleWidgetVisibility,
    resetLayout,
  } = useDashboardStore();

  if (!isCustomizing) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/70 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-md bg-slate-900 border-l border-slate-800 shadow-2xl flex flex-col h-full">

        {/* Header */}
        <div className="p-5 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
              <LayoutGrid className="w-5 h-5 text-indigo-400" />
              Personalizar Dashboard
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Mostrá u ocultá widgets acá. Para mover o redimensionar, arrastrá el widget
              por su título o su esquina inferior derecha directamente en el panel.
            </p>
          </div>
          <button
            onClick={() => setCustomizing(false)}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content list */}
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
            Widgets ({widgets.filter(w => w.visible).length}/{widgets.length} visibles)
          </div>

          {widgets.map((w) => (
            <div
              key={w.id}
              className={`p-3.5 rounded-xl border transition-all ${
                w.visible
                  ? 'bg-slate-800/70 border-slate-700 text-slate-100'
                  : 'bg-slate-950/40 border-slate-800/60 text-slate-500 opacity-60'
              }`}
            >
              {/* Row 1: visibility toggle + title */}
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center space-x-3">
                  <button
                    onClick={() => toggleWidgetVisibility(w.id)}
                    className={`p-1.5 rounded-lg border transition-colors ${
                      w.visible
                        ? 'bg-indigo-600/20 border-indigo-500/40 text-indigo-400 hover:bg-indigo-600/30'
                        : 'bg-slate-800 border-slate-700 text-slate-500 hover:border-slate-600'
                    }`}
                    title={w.visible ? 'Ocultar widget' : 'Mostrar widget'}
                  >
                    {w.visible ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                  </button>
                  <div>
                    <div className="text-sm font-medium leading-tight">{w.title}</div>
                    <div className="text-[11px] text-slate-400 capitalize mt-0.5">
                      {w.category}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Footer actions */}
        <div className="p-5 border-t border-slate-800 bg-slate-900/60 flex items-center justify-between space-x-3">
          <Button variant="ghost" size="sm" icon={RotateCcw} onClick={resetLayout}>
            Restablecer Layout
          </Button>
          <Button variant="primary" size="sm" icon={Check} onClick={() => setCustomizing(false)}>
            Listo
          </Button>
        </div>
      </div>
    </div>
  );
}
