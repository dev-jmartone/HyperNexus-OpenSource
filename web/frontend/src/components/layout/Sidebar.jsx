import React, { useState } from 'react';
import { 
  LayoutDashboard, 
  Monitor, 
  Users, 
  Server, 
  FileText, 
  ShieldCheck, 
  LogOut,
  SlidersHorizontal,
  ChevronRight,
  ChevronLeft,
  UserPlus,
  Zap,
  Layers,
  Sprout,
  FolderTree
} from 'lucide-react';
import { useAuthStore } from '../../store/useAuthStore';
import { useDashboardStore } from '../../store/useDashboardStore';

export function Sidebar({ currentTab, setCurrentTab }) {
  const { user, logout } = useAuthStore();
  const { setCustomizing, isCustomizing } = useDashboardStore();
  const [isCollapsed, setIsCollapsed] = useState(false);

  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'inventario', label: 'Inventario VDI', icon: Monitor },
    { id: 'arbol', label: 'Árbol vCenter', icon: FolderTree },
    { id: 'actividad', label: 'Actividad & Novedades', icon: Zap },
    { id: 'pools', label: 'Pools & Autorizaciones', icon: Layers },
    { id: 'granja', label: 'Granja RDS & Apps', icon: Sprout },
    { id: 'directorio', label: 'Directorio Usuarios', icon: Users },
    { id: 'extraer', label: 'Extracción de Información', icon: Zap },
    { id: 'servidores', label: 'Servidores & VCs', icon: Server },
    { id: 'usuarios', label: 'Gestión Usuarios', icon: UserPlus, adminOnly: true },
    { id: 'auditoria', label: 'Auditoría', icon: ShieldCheck, adminOnly: true },
    { id: 'reportes', label: 'Reportes & Excel', icon: FileText },
  ];


  // Strictly respect manual collapse state
  const isExpanded = !isCollapsed;

  return (
    <aside 
      className={`bg-slate-950/95 border-r border-slate-800/80 flex flex-col h-screen sticky top-0 backdrop-blur-xl transition-all duration-200 z-50 shrink-0 ${
        isExpanded ? 'w-64' : 'w-16'
      }`}
    >
      {/* Brand Header */}
      <div className="p-3 border-b border-slate-800/80 flex items-center justify-between">
        <div className="flex items-center space-x-3 overflow-hidden">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-400 flex items-center justify-center text-white shrink-0 shadow-lg shadow-indigo-600/30">
            <Monitor className="w-5 h-5" />
          </div>
          {isExpanded && (
            <div className="truncate">
              <h1 className="text-sm font-bold text-slate-100 tracking-tight leading-none">HyperNexus</h1>
              <span className="text-[10px] text-slate-400 font-mono">v2.0 • Orchestrator</span>
            </div>
          )}
        </div>

        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-1.5 text-slate-400 hover:text-slate-100 hover:bg-slate-900 rounded-lg transition-colors"
          title={isCollapsed ? 'Expandir Sidebar' : 'Colapsar a Solo Iconos'}
        >
          {isCollapsed ? <ChevronRight className="w-4 h-4 text-indigo-400" /> : <ChevronLeft className="w-4 h-4 text-slate-400" />}
        </button>
      </div>

      {/* Navigation list */}
      <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
        {isExpanded && (
          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-3 mb-2">
            Navegación
          </div>
        )}

        {navItems.map((item) => {
          if (item.adminOnly && user?.rol !== 'admin') return null;

          const Icon = item.icon;
          const isActive = currentTab === item.id;

          return (
            <button
              key={item.id}
              onClick={() => setCurrentTab(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl font-medium text-sm transition-all duration-150 ${
                isActive
                  ? 'bg-indigo-600/15 text-indigo-400 border border-indigo-500/30 shadow-md shadow-indigo-500/5'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60 border border-transparent'
              }`}
              title={!isExpanded ? item.label : undefined}
            >
              <div className="flex items-center space-x-3 shrink-0 mx-auto md:mx-0">
                <Icon className={`w-5 h-5 shrink-0 ${isActive ? 'text-indigo-400' : 'text-slate-400'}`} />
                {isExpanded && <span className="truncate">{item.label}</span>}
              </div>
              {isExpanded && isActive && <ChevronRight className="w-4 h-4 text-indigo-400 shrink-0" />}
            </button>
          );
        })}

        {currentTab === 'dashboard' && (
          <div className="pt-3 border-t border-slate-800/80 mt-3">
            {isExpanded && (
              <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-3 mb-2">
                Personalización
              </div>
            )}
            <button
              onClick={() => setCustomizing(!isCustomizing)}
              className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl font-medium text-sm border transition-all ${
                isCustomizing 
                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 animate-pulse' 
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60 border-slate-800/60'
              }`}
              title={!isExpanded ? 'Personalizar Layout' : undefined}
            >
              <SlidersHorizontal className="w-5 h-5 shrink-0 mx-auto md:mx-0" />
              {isExpanded && <span className="truncate">{isCustomizing ? 'Editando...' : 'Personalizar Layout'}</span>}
            </button>
          </div>
        )}
      </nav>

      {/* User profile footer */}
      <div className="p-2 border-t border-slate-800/80 bg-slate-900/40">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3 truncate">
            <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center font-bold text-slate-300 text-xs shrink-0 mx-auto md:mx-0">
              {user?.username?.substring(0, 2).toUpperCase() || 'US'}
            </div>
            {isExpanded && (
              <div className="truncate">
                <div className="text-xs font-semibold text-slate-200 truncate">{user?.nombre_completo || user?.username}</div>
                <div className="text-[10px] text-slate-400 capitalize">{user?.rol || 'Usuario'}</div>
              </div>
            )}
          </div>
          {isExpanded && (
            <button
              onClick={logout}
              className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors"
              title="Cerrar sesión"
            >
              <LogOut className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
