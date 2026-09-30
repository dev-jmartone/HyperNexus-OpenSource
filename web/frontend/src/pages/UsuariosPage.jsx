import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import {
  Users,
  UserPlus,
  ShieldCheck,
  Key,
  Trash2,
  Edit3,
  CheckCircle,
  X,
  Lock,
  Mail,
  User
} from 'lucide-react';
import { confirmarEliminar, exito, error as alertaError, toastExito } from '../utils/alerts';

export function UsuariosPage() {
  const queryClient = useQueryClient();
  
  // Modals state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [resetPwdUser, setResetPwdUser] = useState(null);

  // Form states
  const [formUsername, setFormUsername] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formNombre, setFormNombre] = useState('');
  const [formPassword, setFormPassword] = useState('');
  const [formRol, setFormRol] = useState('operador');
  const [formActivo, setFormActivo] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');

  // Reset pwd state
  const [newPassword, setNewPassword] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const { data: usuarios, isLoading } = useQuery({
    queryKey: ['usuarios'],
    queryFn: () => api.get('/usuarios'),
  });

  const handleOpenCreate = () => {
    setFormUsername('');
    setFormEmail('');
    setFormNombre('');
    setFormPassword('');
    setFormRol('operador');
    setFormActivo(true);
    setErrorMsg('');
    setIsCreateOpen(true);
  };

  const handleOpenEdit = (u) => {
    setEditingUser(u);
    setFormUsername(u.username || '');
    setFormEmail(u.email || '');
    setFormNombre(u.nombre_completo || '');
    setFormRol(u.rol || 'operador');
    setFormActivo(u.activo !== false);
    setErrorMsg('');
  };

  const handleCreateSubmit = async (e) => {
    e.preventDefault();
    if (!formUsername) {
      setErrorMsg('El nombre de usuario es obligatorio');
      return;
    }
    if (isSaving) return;
    setIsSaving(true);
    try {
      await api.post('/usuarios/crear', {
        username: formUsername,
        password: formPassword,
        email: formEmail,
        nombre_completo: formNombre,
        rol: formRol
      });
      setIsCreateOpen(false);
      queryClient.invalidateQueries(['usuarios']);
      toastExito(`Usuario '${formUsername}' creado${formPassword ? '' : ' con contraseña por defecto (1234)'}.`);
    } catch (err) {
      setErrorMsg(err?.response?.data?.error || 'Error al crear usuario');
    } finally {
      setIsSaving(false);
    }
  };

  const handleEditSubmit = async (e) => {
    e.preventDefault();
    if (isSaving) return;
    setIsSaving(true);
    try {
      await api.post(`/usuarios/${editingUser.id}/editar`, {
        email: formEmail,
        nombre_completo: formNombre,
        rol: formRol,
        activo: formActivo
      });
      setEditingUser(null);
      queryClient.invalidateQueries(['usuarios']);
      toastExito('Usuario actualizado.');
    } catch (err) {
      setErrorMsg(err?.response?.data?.error || 'Error al actualizar usuario');
    } finally {
      setIsSaving(false);
    }
  };

  const handleResetPasswordSubmit = async (e) => {
    e.preventDefault();
    if (!newPassword || isSaving) return;
    setIsSaving(true);
    try {
      await api.post(`/usuarios/${resetPwdUser.id}/editar`, {
        password: newPassword
      });
      const username = resetPwdUser.username;
      setResetPwdUser(null);
      setNewPassword('');
      exito('Contraseña actualizada', `La contraseña de ${username} se cambió con éxito.`);
    } catch (err) {
      alertaError('No se pudo resetear la contraseña', err?.response?.data?.error || '');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (u) => {
    const confirmado = await confirmarEliminar({
      titulo: `¿Eliminar a ${u.username}?`,
      texto: 'Esta acción no se puede deshacer.',
    });
    if (!confirmado) return;
    try {
      await api.post(`/usuarios/${u.id}/eliminar`);
      queryClient.invalidateQueries(['usuarios']);
      toastExito(`Usuario '${u.username}' eliminado.`);
    } catch (err) {
      alertaError('Error al eliminar usuario', err?.response?.data?.error || '');
    }
  };

  return (
    <div className="space-y-6">
      <Card 
        title="Administración de Usuarios de la Aplicación" 
        subtitle="Cuentas con acceso de administración u operaciones al panel"
        action={
          <Button variant="primary" size="sm" icon={UserPlus} onClick={handleOpenCreate}>
            Nuevo Usuario
          </Button>
        }
      >
        {isLoading ? (
          <div className="py-12 text-center text-slate-400 animate-pulse">Cargando usuarios...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300 border-collapse">
              <thead className="bg-slate-900 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Usuario</th>
                  <th className="py-3 px-4">Nombre Completo</th>
                  <th className="py-3 px-4">Email</th>
                  <th className="py-3 px-4">Rol</th>
                  <th className="py-3 px-4">Estado</th>
                  <th className="py-3 px-4 text-center">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {usuarios?.map((u) => (
                  <tr key={u.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-4 font-bold font-mono text-slate-100 flex items-center">
                      <ShieldCheck className="w-4 h-4 mr-2 text-indigo-400 shrink-0" />
                      {u.username}
                    </td>
                    <td className="py-3 px-4 text-slate-200">{u.nombre_completo || '—'}</td>
                    <td className="py-3 px-4 font-mono text-slate-400">{u.email || '—'}</td>
                    <td className="py-3 px-4">
                      <Badge variant={u.rol === 'admin' ? 'purple' : u.rol === 'operador' ? 'info' : 'neutral'}>
                        {u.rol?.toUpperCase()}
                      </Badge>
                    </td>
                    <td className="py-3 px-4">
                      <Badge variant={u.activo !== false ? 'success' : 'danger'}>
                        {u.activo !== false ? 'Activo' : 'Inactivo'}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <div className="flex items-center justify-center space-x-2">
                        <button
                          onClick={() => handleOpenEdit(u)}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-400 hover:bg-slate-800 transition-colors"
                          title="Editar Rol y Datos"
                        >
                          <Edit3 className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => setResetPwdUser(u)}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-amber-400 hover:bg-slate-800 transition-colors"
                          title="Resetear Contraseña"
                        >
                          <Key className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(u)}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-colors"
                          title="Eliminar Usuario"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Modal Crear Usuario */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                <UserPlus className="w-5 h-5 text-indigo-400" />
                <span>Nuevo Usuario de Aplicación</span>
              </h3>
              <button onClick={() => setIsCreateOpen(false)} className="text-slate-400 hover:text-slate-200">
                <X className="w-5 h-5" />
              </button>
            </div>

            {errorMsg && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-400 text-xs font-semibold">
                {errorMsg}
              </div>
            )}

            <form onSubmit={handleCreateSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-300 font-semibold mb-1">Nombre de Usuario (Username)*</label>
                <input 
                  type="text"
                  required
                  value={formUsername}
                  onChange={(e) => setFormUsername(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
                  placeholder="ej. jdoe"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-semibold mb-1">Contraseña Inicial</label>
                <input
                  type="password"
                  value={formPassword}
                  onChange={(e) => setFormPassword(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
                  placeholder="Vacío = contraseña por defecto (1234)"
                />
                <p className="text-[10px] text-slate-500 mt-1">
                  Si la dejás vacía, el usuario se crea con la contraseña <span className="font-mono text-slate-400">1234</span> y
                  se le va a pedir cambiarla al ingresar por primera vez.
                </p>
              </div>

              <div>
                <label className="block text-slate-300 font-semibold mb-1">Nombre Completo</label>
                <input 
                  type="text"
                  value={formNombre}
                  onChange={(e) => setFormNombre(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
                  placeholder="Juan Martone"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-semibold mb-1">Email</label>
                <input 
                  type="email"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
                  placeholder="juan@empresa.com"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-semibold mb-1">Rol de Acceso</label>
                <select
                  value={formRol}
                  onChange={(e) => setFormRol(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
                >
                  <option value="admin">Administrador (Acceso Total)</option>
                  <option value="operador">Operador (Edición & Sync)</option>
                  <option value="lectura">Lectura (Solo Consulta)</option>
                </select>
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <Button type="button" variant="secondary" size="sm" onClick={() => setIsCreateOpen(false)}>
                  Cancelar
                </Button>
                <Button type="submit" variant="primary" size="sm" disabled={isSaving}>
                  {isSaving ? 'Creando...' : 'Crear Usuario'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Editar Rol / Usuario */}
      {editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                <Edit3 className="w-5 h-5 text-indigo-400" />
                <span>Editar Usuario ({editingUser.username})</span>
              </h3>
              <button onClick={() => setEditingUser(null)} className="text-slate-400 hover:text-slate-200">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleEditSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-300 font-semibold mb-1">Nombre Completo</label>
                <input 
                  type="text"
                  value={formNombre}
                  onChange={(e) => setFormNombre(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-semibold mb-1">Email</label>
                <input 
                  type="email"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-semibold mb-1">Rol de Acceso</label>
                <select
                  value={formRol}
                  onChange={(e) => setFormRol(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-indigo-500 outline-none"
                >
                  <option value="admin">Administrador (Acceso Total)</option>
                  <option value="operador">Operador (Edición & Sync)</option>
                  <option value="lectura">Lectura (Solo Consulta)</option>
                </select>
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <Button type="button" variant="secondary" size="sm" onClick={() => setEditingUser(null)}>
                  Cancelar
                </Button>
                <Button type="submit" variant="primary" size="sm" disabled={isSaving}>
                  {isSaving ? 'Guardando...' : 'Guardar Cambios'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Resetear Contraseña */}
      {resetPwdUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm">
          <div className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                <Key className="w-5 h-5 text-amber-400" />
                <span>Resetear Contraseña</span>
              </h3>
              <button onClick={() => setResetPwdUser(null)} className="text-slate-400 hover:text-slate-200">
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-400">
              Establece una nueva clave para el usuario <strong className="text-slate-200">{resetPwdUser.username}</strong>:
            </p>

            <form onSubmit={handleResetPasswordSubmit} className="space-y-4 text-xs">
              <div>
                <input 
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:border-amber-500 outline-none"
                  placeholder="Nueva contraseña"
                />
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <Button type="button" variant="secondary" size="sm" onClick={() => setResetPwdUser(null)}>
                  Cancelar
                </Button>
                <Button type="submit" variant="primary" size="sm" disabled={isSaving}>
                  {isSaving ? 'Cambiando...' : 'Cambiar Clave'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
