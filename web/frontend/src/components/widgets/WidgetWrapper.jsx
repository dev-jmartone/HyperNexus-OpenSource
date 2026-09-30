import React from 'react';
import { GripVertical, EyeOff, RotateCw } from 'lucide-react';
import { useDashboardStore } from '../../store/useDashboardStore';

export function WidgetWrapper({ id, title, children, onRefresh, className = '', isDragging = false }) {
  const { toggleWidgetVisibility, isCustomizing } = useDashboardStore();

  return (
    <div 
      className={`glass-panel rounded-xl shadow-xl transition-all duration-200 border border-slate-800/90 flex flex-col h-full ${
        isDragging ? 'ring-2 ring-indigo-500/50 shadow-2xl scale-[1.01] bg-slate-900/90' : 'hover:border-slate-700/80'
      } ${className}`}
    >
      {/* widget-drag-handle: react-grid-layout usa este selector como manija de arrastre
          (ver DashboardGrid.jsx draggableHandle) -- toda la barra es agarrable, no hace
          falta un segundo header aparte encima (eso duplicaba el titulo, ver historial). */}
      <div className="widget-drag-handle flex items-center justify-between px-5 py-3.5 border-b border-slate-800/80 bg-slate-900/40 rounded-t-xl select-none cursor-grab active:cursor-grabbing">
        <div className="flex items-center space-x-2.5">
          <GripVertical className="w-4 h-4 text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-200 tracking-tight">{title}</h3>
        </div>

        <div className="flex items-center space-x-1">
          {onRefresh && (
            <button
              onClick={onRefresh}
              onMouseDown={(e) => e.stopPropagation()}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800/80 rounded-md transition-colors"
              title="Recargar datos"
            >
              <RotateCw className="w-3.5 h-3.5" />
            </button>
          )}

          {isCustomizing && (
            <button
              onClick={() => toggleWidgetVisibility(id)}
              onMouseDown={(e) => e.stopPropagation()}
              className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800/80 rounded-md transition-colors"
              title="Ocultar widget"
            >
              <EyeOff className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      <div className="p-5 flex-1 flex flex-col justify-between overflow-hidden">
        {children}
      </div>
    </div>
  );
}
