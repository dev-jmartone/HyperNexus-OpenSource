import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from './store/useAuthStore';

import { Sidebar } from './components/layout/Sidebar';
import { Navbar } from './components/layout/Navbar';

import { LoginPage } from './pages/LoginPage';
import { DashboardGrid } from './components/dashboard/DashboardGrid';
import { DashboardCustomizer } from './components/dashboard/DashboardCustomizer';
import { InventarioPage } from './pages/InventarioPage';
import { ArbolPage } from './pages/ArbolPage';
import { ActividadPage } from './pages/ActividadPage';
import { DirectorioPage } from './pages/DirectorioPage';
import { PoolsPage } from './pages/PoolsPage';
import { GranjaPage } from './pages/GranjaPage';
import { ServidoresPage } from './pages/ServidoresPage';
import { UsuariosPage } from './pages/UsuariosPage';
import { AuditoriaPage } from './pages/AuditoriaPage';
import { ReportesPage } from './pages/ReportesPage';
import { ExtraerPage } from './pages/ExtraerPage';
import { CambiarPasswordModal } from './components/modals/CambiarPasswordModal';

import { useDashboardStore } from './store/useDashboardStore';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Antes en false sin razon documentada -- combinado con refetchIntervalInBackground
      // (default de React Query, tambien false) significa que un dashboard dejado en una
      // pestaña de fondo deja de refrescar solo, Y no se pone al dia ni al volver a
      // mirarlo. Confirmado como causa real de "los KPI no se actualizan" (2026-09-02).
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
});

function AppContent() {
  const { user, isAuthenticated, isLoading, checkAuth } = useAuthStore();
  const [currentTab, setCurrentTab] = useState('dashboard');
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    checkAuth();

    const handleUnauthorized = () => {
      useAuthStore.getState().logout();
    };

    window.addEventListener('unauthorized', handleUnauthorized);
    return () => window.removeEventListener('unauthorized', handleUnauthorized);
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      useDashboardStore.getState().syncFromServer();
    }
  }, [isAuthenticated]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400">
        <div className="flex items-center space-x-3">
          <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
          <span className="text-sm font-medium">Cargando HyperNexus...</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  const renderContent = () => {
    switch (currentTab) {
      case 'dashboard':
        return <DashboardGrid />;
      case 'inventario':
        return <InventarioPage globalSearch={searchQuery} />;
      case 'arbol':
        return <ArbolPage />;
      case 'actividad':
        return <ActividadPage />;
      case 'pools':
        return <PoolsPage />;
      case 'granja':
        return <GranjaPage />;
      case 'directorio':
        return <DirectorioPage globalSearch={searchQuery} />;
      case 'extraer':
        return <ExtraerPage />;
      case 'servidores':
        return <ServidoresPage />;
      case 'usuarios':
        return <UsuariosPage />;
      case 'auditoria':
        return <AuditoriaPage />;
      case 'reportes':
        return <ReportesPage />;
      default:
        return <DashboardGrid />;
    }
  };


  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex font-sans selection:bg-indigo-500 selection:text-white">
      <Sidebar currentTab={currentTab} setCurrentTab={setCurrentTab} />

      <div className="flex-1 flex flex-col min-w-0">
        <Navbar 
          currentTab={currentTab} 
          searchQuery={searchQuery} 
          setSearchQuery={setSearchQuery} 
        />

        <main className="flex-1 p-8 overflow-y-auto">
          {renderContent()}
        </main>
      </div>

      <DashboardCustomizer />

      {/* Mandatory Password Change Popup if must_change_password */}
      {user?.must_change_password && (
        <CambiarPasswordModal
          isOpen={true}
          isForced={true}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
