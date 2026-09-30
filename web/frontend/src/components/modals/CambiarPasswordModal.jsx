import React, { useState } from 'react';
import api from '../../services/api';
import { Button } from '../ui/Button';
import { Lock, X, CheckCircle, AlertCircle } from 'lucide-react';

export function CambiarPasswordModal({ isOpen, onClose }) {
  const [actualPassword, setActualPassword] = useState('');
  const [nuevaPassword, setNuevaPassword] = useState('');
  const [confirmarPassword, setConfirmarPassword] = useState('');
  
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg('');
    setSuccessMsg('');

    if (nuevaPassword !== confirmarPassword) {
      setErrorMsg('Las contraseñas no coinciden');
      return;
    }

    if (nuevaPassword.length < 4) {
      setErrorMsg('La nueva contraseña debe tener al menos 4 caracteres');
      return;
    }

    try {
      setIsLoading(true);
      await api.post('/auth/cambiar_password', {
        actual_password: actualPassword,
        nueva_password: nuevaPassword
      });
      setIsLoading(false);
      setSuccessMsg('Contraseña actualizada con éxito');
      setActualPassword('');
      setNuevaPassword('');
      setConfirmarPassword('');
      setTimeout(() => {
        setSuccessMsg('');
        onClose();
      }, 1500);
    } catch (err) {
      setIsLoading(false);
      setErrorMsg(err?.response?.data?.error || 'Error al cambiar la contraseña');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Lock className="w-5 h-5 text-indigo-400" />
            <span>Cambiar Contraseña de Perfil</span>
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        {errorMsg && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-400 text-xs font-semibold flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {successMsg && (
          <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-xs font-semibold flex items-center space-x-2">
            <CheckCircle className="w-4 h-4 shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          <div>
            <label className="block text-slate-300 font-semibold mb-1">Contraseña Actual*</label>
            <input 
              type="password"
              required
              value={actualPassword}
              onChange={(e) => setActualPassword(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
              placeholder="••••••••"
            />
          </div>

          <div>
            <label className="block text-slate-300 font-semibold mb-1">Nueva Contraseña*</label>
            <input 
              type="password"
              required
              value={nuevaPassword}
              onChange={(e) => setNuevaPassword(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
              placeholder="••••••••"
            />
          </div>

          <div>
            <label className="block text-slate-300 font-semibold mb-1">Confirmar Nueva Contraseña*</label>
            <input 
              type="password"
              required
              value={confirmarPassword}
              onChange={(e) => setConfirmarPassword(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
              placeholder="••••••••"
            />
          </div>

          <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
            <Button type="button" variant="secondary" size="sm" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" variant="primary" size="sm" disabled={isLoading}>
              {isLoading ? 'Guardando...' : 'Actualizar Contraseña'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
