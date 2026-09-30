import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSchedulerInterval } from '../useSchedulerInterval';
import api from '../../services/api';

vi.mock('../../services/api');

function wrapper({ children }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('useSchedulerInterval', () => {
  beforeEach(() => vi.resetAllMocks());

  it('con intervalo 5m, capAt60s por default limita a 60s (no 5min)', async () => {
    api.get.mockResolvedValue({ key: '5m' });
    const { result } = renderHook(() => useSchedulerInterval(), { wrapper });
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.intervalMs).toBe(60_000);
    expect(result.current.intervalKey).toBe('5m');
  });

  it('con intervalo 1m, capAt60s no cambia nada (ya es <=60s)', async () => {
    api.get.mockResolvedValue({ key: '1m' });
    const { result } = renderHook(() => useSchedulerInterval(), { wrapper });
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.intervalMs).toBe(60_000);
  });

  it('con capAt60s=false, devuelve el intervalo real sin capear (ej. 15m)', async () => {
    api.get.mockResolvedValue({ key: '15m' });
    const { result } = renderHook(() => useSchedulerInterval({ capAt60s: false }), { wrapper });
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.intervalMs).toBe(900_000);
  });

  it('con "off", igual sigue refrescando cada 60s (los widgets leen datos ya extraídos)', async () => {
    api.get.mockResolvedValue({ key: 'off' });
    const { result } = renderHook(() => useSchedulerInterval(), { wrapper });
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.intervalMs).toBe(60_000);
  });

  it('sin datos todavía (antes de resolver la query), usa el fallback de 5m capeado', () => {
    api.get.mockReturnValue(new Promise(() => {})); // nunca resuelve
    const { result } = renderHook(() => useSchedulerInterval(), { wrapper });
    expect(result.current.intervalMs).toBe(60_000);
    expect(result.current.isLoaded).toBe(false);
  });
});
