import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { IntervalSelector } from '../IntervalSelector';
import api from '../../../services/api';
import { toastError } from '../../../utils/alerts';

vi.mock('../../../services/api');
vi.mock('../../../utils/alerts', () => ({
  toastError: vi.fn(),
}));

function renderWithClient(ui) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('IntervalSelector', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('muestra el intervalo actual (5m) traído del backend', async () => {
    api.get.mockResolvedValue({ key: '5m', seconds: 300, enabled: true, options: ['off', '1m', '5m', '15m', '30m', '1h'] });
    renderWithClient(<IntervalSelector />);
    expect(await screen.findByText('5m')).toBeInTheDocument();
  });

  it('estado "off" muestra el punto apagado (gris) y texto de pausa al abrir el panel', async () => {
    api.get.mockResolvedValue({ key: 'off', seconds: 0, enabled: false, options: ['off', '1m', '5m', '15m', '30m', '1h'] });
    renderWithClient(<IntervalSelector />);
    const button = await screen.findByText('off');
    fireEvent.click(button);
    expect(await screen.findByText(/en pausa/i)).toBeInTheDocument();
  });

  it('clickear una opción llama a POST /config/intervalo con la key elegida', async () => {
    api.get.mockResolvedValue({ key: '5m', seconds: 300, enabled: true, options: ['off', '1m', '5m', '15m', '30m', '1h'] });
    api.post.mockResolvedValue({ key: '15m', seconds: 900, enabled: true, options: ['off', '1m', '5m', '15m', '30m', '1h'] });

    renderWithClient(<IntervalSelector />);
    fireEvent.click(await screen.findByText('5m'));
    fireEvent.click(await screen.findByText('15m'));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/config/intervalo', { intervalo: '15m' });
    });
  });

  it('si el backend rechaza (403, no-admin), muestra un toast con el mensaje de error', async () => {
    api.get.mockResolvedValue({ key: '5m', seconds: 300, enabled: true, options: ['off', '1m', '5m', '15m', '30m', '1h'] });
    api.post.mockRejectedValue({ response: { data: { error: 'Solo administradores pueden cambiar el intervalo.' } } });

    renderWithClient(<IntervalSelector />);
    fireEvent.click(await screen.findByText('5m'));
    fireEvent.click(await screen.findByText('1h'));

    await waitFor(() => {
      expect(toastError).toHaveBeenCalledWith('Solo administradores pueden cambiar el intervalo.');
    });
  });
});
