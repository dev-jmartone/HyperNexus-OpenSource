import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../../services/api';
import { Button } from '../ui/Button';
import { Key, Lock, AlertCircle, CheckCircle2 } from 'lucide-react';

export function VcSessionModal({ isOpen, onClose, onSaved }) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  // Sin esto el modal siempre se ve como formulario vacío pidiendo clave, aunque ya
  // haya una sesión válida guardada (hasta 30min desde la última vez) — confunde,
  // parece que "la está pidiendo de nuevo" cuando en realidad no hace falta.
  const { data: vcStatus } = useQuery({
    queryKey: ['vc_status'],
    queryFn: () => api.get('/auth/vc_status'),
    enabled: isOpen,
  });
  const hasCreds = Boolean(vcStatus?.has_credentials);
  const minutosRestantes = Math.ceil((vcStatus?.remaining_seconds || 0) / 60);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (!password) return;

    try {
      setIsLoading(true);
      await api.post('/auth/set_vc_credentials', { vc_password: password });
      await queryClient.invalidateQueries({ queryKey: ['vc_status'] });
      setIsLoading(false);
      setPassword('');
      if (onSaved) onSaved();
      if (onClose) onClose();
    } catch (err) {
      setIsLoading(false);
      setError(err.response?.data?.error || 'Error al guardar credenciales');
    }
  };

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-md bg-slate-900 p-6 rounded-2xl border border-slate-800 shadow-2xl space-y-4 my-auto relative z-[10000]">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-2">
            <Key className="w-5 h-5 text-amber-400" />
            <h3 className="text-base font-bold text-slate-100">Credenciales de Sesión vCenter / Horizon</h3>
          </div>
          <button 
            type="button" 
            onClick={onClose} 
            className="text-slate-400 hover:text-slate-200 text-xl font-bold p-1 rounded-lg hover:bg-slate-800 transition-colors"
          >
            ×
          </button>
        </div>

        {hasCreds ? (
          <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-300 text-xs font-semibold flex items-center">
            <CheckCircle2 className="w-4 h-4 mr-2 shrink-0" />
            Ya tenés una sesión activa{vcStatus?.vc_usuario ? ` como ${vcStatus.vc_usuario.split('@')[0]}` : ''} — vence en ~{minutosRestantes} min. Solo cargá una clave nueva si querés reemplazarla.
          </div>
        ) : (
          <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-indigo-300 text-xs">
            🔒 Por seguridad, tu contraseña de red de vCenter se almacena únicamente en la memoria de sesión activa durante 30 minutos para permitir las extracciones.
          </div>
        )}

        {error && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-400 text-xs font-semibold flex items-center">
            <AlertCircle className="w-4 h-4 mr-2 shrink-0" /> {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3 text-xs">
          <div>
            <label className="block text-slate-400 font-medium mb-1">Contraseña de Sesión vCenter / Horizon *</label>
            <div className="relative">
              <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Ingresá tu contraseña de red"
                className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-4 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                autoFocus
              />
            </div>
          </div>

          <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
            <Button type="button" variant="secondary" size="sm" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" variant="primary" size="sm" disabled={isLoading}>
              {isLoading ? 'Guardando...' : 'Guardar Credenciales'}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}

