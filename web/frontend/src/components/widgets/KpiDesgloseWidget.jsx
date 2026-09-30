import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { Server, Layers, Power, PowerOff, Wifi, CheckCircle, Crown, Copy, MonitorSmartphone, Box } from 'lucide-react';
import { WidgetWrapper } from './WidgetWrapper';
import { useSchedulerInterval } from '../../hooks/useSchedulerInterval';

export function KpiDesgloseWidget({ id, title }) {
  const [tab, setTab] = useState('servidor'); // 'servidor' | 'origen'
  const { intervalMs } = useSchedulerInterval();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['kpis_desglose'],
    queryFn: () => api.get('/kpis/desglose'),
    refetchInterval: intervalMs,
  });

  if (isLoading) {
    return (
      <WidgetWrapper id={id} title={title}>
        <div className="animate-pulse grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-28 bg-slate-800/40 rounded-xl border border-slate-800"></div>
          ))}
        </div>
      </WidgetWrapper>
    );
  }

  const items = tab === 'servidor' ? (data?.por_servidor || []) : (data?.por_origen || []);
  const seg = data?.segmentacion_global;

  return (
    <WidgetWrapper id={id} title={title} onRefresh={refetch}>
      <div className="space-y-4">
        {/* Segmentación global: Masters / Plantillas / VDI en Pool / Estáticas */}
        {seg && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div className="bg-purple-500/10 border border-purple-500/20 rounded-xl p-2.5 flex items-center justify-between" title="Golden images usadas para clonar pools">
              <span className="flex items-center gap-1.5 text-[11px] text-purple-300 font-semibold"><Crown className="w-3.5 h-3.5" /> Masters</span>
              <span className="font-mono font-bold text-sm text-purple-300">{seg.masters}</span>
            </div>
            <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-xl p-2.5 flex items-center justify-between" title="Plantillas de vCenter, no están en uso">
              <span className="flex items-center gap-1.5 text-[11px] text-indigo-300 font-semibold"><Copy className="w-3.5 h-3.5" /> Plantillas</span>
              <span className="font-mono font-bold text-sm text-indigo-300">{seg.plantillas}</span>
            </div>
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-2.5 flex items-center justify-between" title="VDIs con pool de Horizon asignado">
              <span className="flex items-center gap-1.5 text-[11px] text-emerald-300 font-semibold"><MonitorSmartphone className="w-3.5 h-3.5" /> VDI Pool</span>
              <span className="font-mono font-bold text-sm text-emerald-300">{seg.vdi_pool}</span>
            </div>
            <div className="bg-slate-700/30 border border-slate-600/30 rounded-xl p-2.5 flex items-center justify-between" title="VMs/VDIs sin pool -- standalone">
              <span className="flex items-center gap-1.5 text-[11px] text-slate-300 font-semibold"><Box className="w-3.5 h-3.5" /> Estáticas</span>
              <span className="font-mono font-bold text-sm text-slate-300">{seg.estaticas}</span>
            </div>
          </div>
        )}

        {/* Toggle switch: Por Servidor vs Por Origen */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-1 bg-slate-900/90 p-1 rounded-xl border border-slate-800">
            <button
              onClick={() => setTab('servidor')}
              className={`flex items-center space-x-1.5 px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                tab === 'servidor'
                  ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Server className="w-3.5 h-3.5" />
              <span>Por Servidor</span>
            </button>

            <button
              onClick={() => setTab('origen')}
              className={`flex items-center space-x-1.5 px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                tab === 'origen'
                  ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Por Origen / Área</span>
            </button>
          </div>

          <span className="text-[11px] text-slate-400 font-medium hidden sm:inline">
            {items.length} {tab === 'servidor' ? 'Servidores' : 'Orígenes'} registrados
          </span>
        </div>

        {/* Cards Grid per area/servidor */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((item, idx) => {
            const pctOn = item.total > 0 ? Math.round((item.encendidas / item.total) * 100) : 0;
            const pctOff = item.total > 0 ? Math.round((item.apagadas / item.total) * 100) : 0;
            const pctSinDato = Math.max(0, 100 - pctOn - pctOff);

            return (
              <div
                key={idx}
                className="bg-slate-900/60 border border-slate-800 hover:border-indigo-500/40 rounded-xl p-4 transition-all flex flex-col justify-between group"
              >
                {/* Header title */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    {tab === 'servidor' ? (
                      <Server className="w-4 h-4 text-indigo-400 shrink-0" />
                    ) : (
                      <Layers className="w-4 h-4 text-cyan-400 shrink-0" />
                    )}
                    <span className="font-bold text-sm text-slate-100 truncate max-w-[160px]">
                      {item.nombre}
                    </span>
                  </div>
                  <span className="text-xs font-mono font-bold text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded-full border border-indigo-500/20">
                    {item.total} VMs
                  </span>
                </div>

                {/* Status stats grid */}
                <div className="grid grid-cols-2 gap-2 my-3">
                  <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-2 flex items-center justify-between">
                    <div className="flex items-center space-x-1.5">
                      <Power className="w-3.5 h-3.5 text-emerald-400" />
                      <span className="text-[11px] text-slate-300 font-medium">Encendidas</span>
                    </div>
                    <span className="font-mono font-bold text-xs text-emerald-400">{item.encendidas}</span>
                  </div>

                  <div className="bg-rose-500/10 border border-rose-500/20 rounded-lg p-2 flex items-center justify-between">
                    <div className="flex items-center space-x-1.5">
                      <PowerOff className="w-3.5 h-3.5 text-rose-400" />
                      <span className="text-[11px] text-slate-300 font-medium">Apagadas</span>
                    </div>
                    <span className="font-mono font-bold text-xs text-rose-400">{item.apagadas}</span>
                  </div>
                </div>

                {/* Sesiones -- el detalle VDI vs VM real ya esta en la fila de
                    Masters/Plantillas/VDI Pool/Estaticas de abajo (tipo_provisionamiento,
                    misma clasificacion que el resto del dashboard). La vieja fila usaba
                    Maquina.tipo (VDI/VM por plataforma de origen, no por uso real) y podia
                    no coincidir con esa -- ej. un Master capturado via Horizon contaba como
                    "VDI" ahi pero como "Master" aca, dos numeros que no cuadraban. */}
                <div className="flex items-center justify-between text-[11px] text-slate-400 border-t border-slate-800/80 pt-2">
                  {item.sin_dato_energia > 0 ? (
                    <span className="font-mono text-amber-400" title="Sin estado de energia determinable (ni encendida ni apagada)">
                      ⚠️ {item.sin_dato_energia} sin dato
                    </span>
                  ) : <span />}
                  <div className="flex items-center space-x-3">
                    <span className="flex items-center text-emerald-400" title="Sesiones conectadas">
                      <Wifi className="w-3 h-3 mr-1" /> {item.conectadas}
                    </span>
                    <span className="flex items-center text-sky-400" title="Libres disponibles">
                      <CheckCircle className="w-3 h-3 mr-1" /> {item.disponibles}
                    </span>
                  </div>
                </div>

                {/* Segmentación por servidor/origen */}
                <div className="flex items-center justify-between text-[10px] text-slate-500 font-mono pt-1.5">
                  <span className="flex items-center gap-0.5" title="Masters"><Crown className="w-2.5 h-2.5" />{item.masters}</span>
                  <span className="flex items-center gap-0.5" title="Plantillas"><Copy className="w-2.5 h-2.5" />{item.plantillas}</span>
                  <span className="flex items-center gap-0.5" title="VDI Pool"><MonitorSmartphone className="w-2.5 h-2.5" />{item.vdi_pool}</span>
                  <span className="flex items-center gap-0.5" title="Estáticas"><Box className="w-2.5 h-2.5" />{item.estaticas}</span>
                </div>

                {/* Visual Progress Bar (Encendidas vs Apagadas) */}
                <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden mt-3 flex">
                  <div
                    className="bg-emerald-500 h-full transition-all duration-500"
                    style={{ width: `${pctOn}%` }}
                    title={`${pctOn}% Encendidas`}
                  />
                  <div
                    className="bg-rose-500 h-full transition-all duration-500"
                    style={{ width: `${pctOff}%` }}
                    title={`${pctOff}% Apagadas`}
                  />
                  {pctSinDato > 0 && (
                    <div
                      className="bg-slate-600 h-full transition-all duration-500"
                      style={{ width: `${pctSinDato}%` }}
                      title={`${pctSinDato}% sin dato de energía`}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </WidgetWrapper>
  );
}
