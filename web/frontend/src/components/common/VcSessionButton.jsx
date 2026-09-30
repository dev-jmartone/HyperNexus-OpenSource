import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { Key, Clock } from 'lucide-react';
import { VcSessionModal } from '../modals/VcSessionModal';

export function VcSessionButton({ variant = 'navbar', className = '' }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const { data: vcStatus } = useQuery({
    queryKey: ['vc_status'],
    queryFn: () => api.get('/auth/vc_status'),
    refetchInterval: 10000,
  });

  const hasCreds = Boolean(vcStatus?.has_credentials);
  const initialSeconds = vcStatus?.remaining_seconds || 0;
  const usuario = vcStatus?.vc_usuario || '';

  useEffect(() => {
    setSecondsLeft(initialSeconds);
  }, [initialSeconds]);

  useEffect(() => {
    if (!hasCreds || secondsLeft <= 0) return;

    const timer = setInterval(() => {
      setSecondsLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);

    return () => clearInterval(timer);
  }, [hasCreds, secondsLeft > 0]);

  const formatTime = (totalSecs) => {
    if (totalSecs <= 0) return '00:00';
    const m = Math.floor(totalSecs / 60);
    const s = totalSecs % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const isExpired = !hasCreds || secondsLeft <= 0;

  return (
    <>
      <button
        type="button"
        onClick={() => setIsModalOpen(true)}
        className={
          className ||
          (variant === 'navbar'
            ? `px-3 py-1.5 rounded-xl border flex items-center space-x-2 text-xs font-semibold transition-all ${
                !isExpired
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20 shadow-sm shadow-emerald-500/10'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20'
              }`
            : `px-4 py-2 rounded-xl font-bold text-xs flex items-center space-x-2 transition-all ${
                !isExpired
                  ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/25'
                  : 'bg-amber-500/15 text-amber-300 border border-amber-500/30 hover:bg-amber-500/25'
              }`)
        }
        title="Ingresar o modificar contraseña de sesión vCenter/Horizon"
      >
        {!isExpired ? (
          <>
            <Clock className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
            <span>
              vCenter{usuario ? ` (${usuario.split('@')[0]})` : ''}: {formatTime(secondsLeft)}
            </span>
          </>
        ) : (
          <>
            <Key className="w-3.5 h-3.5 text-amber-400" />
            <span>🔐 Configurar Clave vCenter</span>
          </>
        )}
      </button>

      <VcSessionModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
      />
    </>
  );
}
