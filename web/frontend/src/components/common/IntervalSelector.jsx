import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../../services/api';
import { Clock, Radio } from 'lucide-react';
import { toastError } from '../../utils/alerts';

export function IntervalSelector() {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(false);

  const { data: config } = useQuery({
    queryKey: ['scheduler_interval'],
    queryFn: () => api.get('/config/intervalo'),
    refetchInterval: 60000,
  });

  const mutation = useMutation({
    mutationFn: (newKey) => api.post('/config/intervalo', { intervalo: newKey }),
    onSuccess: () => {
      queryClient.invalidateQueries(['scheduler_interval']);
      setIsOpen(false);
    },
    onError: (e) => {
      toastError(e?.response?.data?.error || 'No se pudo cambiar el intervalo.');
    },
  });

  const currentKey = config?.key || '5m';
  const options = config?.options || ['off', '1m', '5m', '15m', '30m', '1h'];
  const isOff = currentKey === 'off';

  const labels = {
    'off': 'Apagado',
    '1m': '1 minuto',
    '5m': '5 minutos',
    '15m': '15 minutos',
    '30m': '30 minutos',
    '1h': '1 hora',
  };

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center space-x-2 bg-slate-900 border border-slate-800 hover:border-indigo-500/50 rounded-xl px-3 py-1.5 text-xs text-slate-300 hover:text-white transition-all shadow-sm group"
        title="Cambiar frecuencia de vigilancia en vivo"
      >
        <span className="relative flex h-2 w-2">
          {!isOff && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${isOff ? 'bg-slate-600' : 'bg-emerald-500'}`}></span>
        </span>
        <Clock className={`w-3.5 h-3.5 group-hover:rotate-12 transition-transform ${isOff ? 'text-slate-500' : 'text-indigo-400'}`} />
        <span className="font-mono font-medium">{currentKey}</span>
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-56 bg-slate-900 border border-slate-800 rounded-xl shadow-2xl p-3 z-50 animate-fadeIn backdrop-blur-xl">
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800">
            <span className="text-[11px] font-bold text-slate-300 flex items-center">
              <Radio className="w-3.5 h-3.5 mr-1.5 text-emerald-400 animate-pulse" />
              Frecuencia de Escaneo
            </span>
            <span className="text-[10px] text-slate-500 font-mono">Backend + UI</span>
          </div>

          <div className="grid grid-cols-6 gap-1 mb-2">
            {options.map((opt) => {
              const isSelected = opt === currentKey;
              const isOffOption = opt === 'off';
              return (
                <button
                  key={opt}
                  onClick={() => mutation.mutate(opt)}
                  disabled={mutation.isLoading}
                  title={isOffOption ? 'Pausar la extracción automática' : undefined}
                  className={`py-1 rounded-lg text-xs font-mono font-bold transition-all ${
                    isSelected
                      ? (isOffOption
                          ? 'bg-rose-600 text-white shadow-lg shadow-rose-500/30 ring-1 ring-rose-400'
                          : 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/30 ring-1 ring-indigo-400')
                      : 'bg-slate-800/80 text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                  }`}
                >
                  {isOffOption ? '⏻' : opt}
                </button>
              );
            })}
          </div>

          <p className="text-[10px] text-slate-400 text-center font-sans">
            {isOff
              ? <span className="text-rose-400">Extracción automática en pausa — solo corre manual.</span>
              : <>Extracción automática + refresco de widgets cada <strong className="text-slate-200">{labels[currentKey] || currentKey}</strong></>}
          </p>
        </div>
      )}
    </div>
  );
}
