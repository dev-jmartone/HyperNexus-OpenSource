import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PoolsPage } from '../PoolsPage';
import api from '../../services/api';

vi.mock('../../services/api');

function renderWithClient(ui) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('PoolsPage', () => {
  const mockPoolsData = {
    items: [
      {
        id: 1,
        nombre: 'POOL-DESKTOPS',
        display_name: 'Desktops Pool',
        origen: 'dt',
        tipo: 'automated',
        user_assignment: 'floating',
        enabled: true,
        master_vm_actual: 'MASTER-WIN10-V1',
        snapshot_actual: 'SNAP-01',
        total_autorizaciones: 2,
        autorizaciones_locales: [{ id: 1, usuario_o_grupo: 'GRUPO_VDI', es_grupo: true }],
        autorizaciones_globales: [{ id: 2, usuario_o_grupo: 'USER_GLOBAL', es_grupo: false }],
        metricas: { total_vms: 10, conectadas: 5, disponibles: 3, desconectadas: 1, errores: 1, masters: 1, plantillas: 0, vdi_pool: 9, estaticas: 0 }
      }
    ],
    segmentacion_global: { masters: 1, plantillas: 0, vdi_pool: 9, estaticas: 0 }
  };

  const mockMastersData = {
    total: 2,
    en_uso: 1,
    en_desuso: 1,
    items: [
      {
        nombre: 'MASTER-WIN10-V1',
        origenes: ['dt'],
        en_uso: true,
        pools: [{ id: 1, nombre: 'POOL-DESKTOPS' }],
        total_vms: 10,
        disco_usado_gb: 60,
        ultima_publicacion: '2026-08-10'
      },
      {
        nombre: 'MASTER-WIN11-OLD',
        origenes: ['su'],
        en_uso: false,
        pools: [],
        total_vms: 0,
        disco_usado_gb: 80,
        ultima_publicacion: null
      }
    ]
  };

  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('renderiza la pestaña Pools por defecto con métricas y lista de pools', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/pools/detalladas') return Promise.resolve(mockPoolsData);
      return Promise.reject(new Error('URL no encontrada'));
    });

    renderWithClient(<PoolsPage />);

    expect(await screen.findByText('POOL-DESKTOPS')).toBeInTheDocument();
    expect(screen.getByText('Gestión de Pools & Autorizaciones')).toBeInTheDocument();
  });

  it('al cambiar a la pestaña Masters muestra la vista cruzada de VMs master', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/pools/detalladas') return Promise.resolve(mockPoolsData);
      if (url === '/pools/masters') return Promise.resolve(mockMastersData);
      return Promise.reject(new Error('URL no encontrada'));
    });

    renderWithClient(<PoolsPage />);

    const mastersTabButton = await screen.findByRole('button', { name: /Masters/i });
    fireEvent.click(mastersTabButton);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/pools/masters');
    });

    expect(await screen.findByText('MASTER-WIN10-V1')).toBeInTheDocument();
    expect(screen.getByText('MASTER-WIN11-OLD')).toBeInTheDocument();
    expect(screen.getByText('Uso de Imágenes Master')).toBeInTheDocument();
    expect(screen.getByText('En uso')).toBeInTheDocument();
    expect(screen.getByText('En desuso')).toBeInTheDocument();
    expect(screen.getByText('60 GB')).toBeInTheDocument();
  });
});
