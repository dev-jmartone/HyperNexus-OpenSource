import React from 'react';
import { Search, SlidersHorizontal } from 'lucide-react';
import { useDashboardStore } from '../../store/useDashboardStore';
import { VcSessionButton } from '../common/VcSessionButton';
import { IntervalSelector } from '../common/IntervalSelector';

export function Navbar({ currentTab, searchQuery, setSearchQuery }) {
  const { setCustomizing, isCustomizing } = useDashboardStore();

  const titles = {
    dashboard: 'Dashboard Principal',
    inventario: 'Inventario de Escritorios VDI & VMs',
    arbol: 'Árbol de Carpetas por vCenter',
    directorio: 'Directorio Global de Usuarios',
    servidores: 'Servidores & vCenter Horizon',
    usuarios: 'Gestión de Usuarios del Sistema',
    auditoria: 'Registro de Auditoría de Sistema',
    reportes: 'Generación y Exportación de Reportes',
    extraer: 'Extracción de Información',
  };

  return (
    <header className="h-16 border-b border-slate-800/80 bg-slate-950/60 backdrop-blur-xl sticky top-0 z-40 px-8 flex items-center justify-between">
      <div className="flex items-center space-x-4">
        <h2 className="text-base font-bold text-slate-100 tracking-tight">
          {titles[currentTab] || 'Inventario VDI'}
        </h2>
      </div>

      <div className="flex items-center space-x-4">
        {/* Search bar */}
        <div className="relative w-64 md:w-80">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Buscar por nombre, usuario, pool..."
            className="w-full bg-slate-900/80 border border-slate-800 rounded-xl pl-9 pr-4 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
          />
        </div>

        {currentTab === 'dashboard' && (
          <button
            onClick={() => setCustomizing(!isCustomizing)}
            className="p-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700 transition-all flex items-center space-x-2 text-xs font-medium"
            title="Personalizar Dashboard"
          >
            <SlidersHorizontal className="w-4 h-4 text-indigo-400" />
            <span className="hidden sm:inline">Widgets</span>
          </button>
        )}

        {/* Live Surveillance Frequency Selector (1m, 5m, 15m, 30m, 1h) */}
        <IntervalSelector />

        {/* vCenter Session Clock & Credential Button */}
        <VcSessionButton variant="navbar" />
      </div>
    </header>
  );
}

