import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { useAuthStore } from '../store/useAuthStore';
import { Server, CheckCircle2, ShieldAlert, Cpu, RefreshCw, HardDrive, Plus, Edit, Trash2, Plug, Lock, Globe } from 'lucide-react';
import { confirmarEliminar, toastExito, toastError } from '../utils/alerts';

export function ServidoresPage() {
  const { user } = useAuthStore();
  const isAdmin = user?.rol === 'admin';

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingServer, setEditingServer] = useState(null);

  // Form State matching exact legacy _form_servidor.html
  const [nombre, setNombre] = useState('');
  const [host, setHost] = useState('');
  const [tipo, setTipo] = useState('horizon');
  const [tipoMaquina, setTipoMaquina] = useState('VDI');
  const [origen, setOrigen] = useState('dt');
  const [dominio, setDominio] = useState('');

  const [testResult, setTestResult] = useState(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const { data: servidores, isLoading, refetch } = useQuery({
    queryKey: ['servidores'],
    queryFn: () => api.get('/servidores'),
  });

  const handleOpenCreate = () => {
    setEditingServer(null);
    setNombre('');
    setHost('');
    setTipo('horizon');
    setTipoMaquina('VDI');
    setOrigen('dt');
    setDominio('CORP');
    setIsModalOpen(true);
  };

  const handleOpenEdit = (s) => {
    setEditingServer(s);
    setNombre(s.nombre || '');
    setHost(s.host || '');
    setTipo(s.tipo || 'horizon');
    setTipoMaquina(s.tipo_maquina || 'VDI');
    setOrigen(s.origen || 'dt');
    setDominio(s.dominio || '');
    setIsModalOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isSaving) return;
    setIsSaving(true);
    try {
      const payload = {
        nombre, host, tipo, tipo_maquina: tipoMaquina, origen, dominio
      };

      if (editingServer) {
        await api.post(`/servidores/${editingServer.id}/editar`, payload);
      } else {
        await api.post('/servidores/crear', payload);
      }
      setIsModalOpen(false);
      refetch();
      toastExito(editingServer ? 'Servidor actualizado.' : 'Servidor creado.');
    } catch (err) {
      toastError(err.response?.data?.error || 'Error al guardar servidor');
    } finally {
      setIsSaving(false);
    }
  };

  const handleTestConnection = async (id) => {
    try {
      setIsTesting(id);
      setTestResult(null);
      const res = await api.post(`/servidores/${id}/probar`);
      setTestResult({ id, ...res });
      setIsTesting(false);
    } catch (e) {
      setIsTesting(false);
      setTestResult({ id, ok: false, msg: 'Error de red o endpoint' });
    }
  };

  const handleDelete = async (s) => {
    const confirmado = await confirmarEliminar({
      titulo: `¿Eliminar el servidor '${s.nombre}'?`,
      texto: 'Se van a perder sus credenciales guardadas y su historial de extracciones.',
    });
    if (!confirmado) return;
    try {
      await api.post(`/servidores/${s.id}/eliminar`);
      refetch();
      toastExito(`Servidor '${s.nombre}' eliminado.`);
    } catch (e) {
      toastError('Error al eliminar servidor');
    }
  };

  return (
    <div className="space-y-6">
      <Card 
        title="Servidores Horizon CS & vCenters Configurados" 
        subtitle="Monitoreo y Administración de Infraestructura"
        action={
          <div className="flex items-center space-x-2">
            <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => refetch()}>
              Actualizar
            </Button>
            {isAdmin && (
              <Button variant="primary" size="sm" icon={Plus} onClick={handleOpenCreate}>
                Agregar Servidor
              </Button>
            )}
          </div>
        }
      >
        {isLoading ? (
          <div className="py-20 text-center text-slate-400 animate-pulse">Cargando servidores desde la base de datos...</div>
        ) : servidores?.length === 0 ? (
          <div className="py-12 text-center text-slate-500">No hay servidores registrados.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {servidores?.map((s) => (
              <div key={s.id} className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-4 hover:border-indigo-500/40 transition-colors flex flex-col justify-between">
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
                      <Server className="w-5 h-5" />
                    </div>
                    <Badge variant={s.activo ? 'success' : 'neutral'}>
                      {s.activo ? 'ACTIVO' : 'INACTIVO'}
                    </Badge>
                  </div>

                  <div>
                    <h4 className="text-base font-bold text-slate-100">{s.nombre}</h4>
                    <p className="text-xs text-slate-400 font-mono mt-0.5">{s.host}</p>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/80">
                      <span className="text-slate-500 uppercase text-[10px] block">Tipo Servidor</span>
                      <span className="font-semibold text-slate-200 uppercase">{s.tipo}</span>
                    </div>
                    <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/80">
                      <span className="text-slate-500 uppercase text-[10px] block">Origen / Código</span>
                      <span className="font-mono font-bold text-indigo-400 uppercase">{s.origen || '—'}</span>
                    </div>
                  </div>

                  <div className="pt-2 flex items-center justify-between text-xs text-slate-400">
                    <span className="flex items-center">
                      <HardDrive className="w-3.5 h-3.5 mr-1.5 text-slate-500" />
                      VMs Registradas
                    </span>
                    <span className="font-bold text-slate-100 font-mono text-sm">{s.total_vms || 0} VMs</span>
                  </div>

                  {testResult?.id === s.id && (
                    <div className={`p-2 rounded-lg text-xs font-semibold ${testResult.ok ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
                      {testResult.msg}
                    </div>
                  )}
                </div>

                {/* Card Actions */}
                <div className="pt-3 border-t border-slate-800/80 flex items-center justify-between">
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    icon={Plug}
                    disabled={isTesting === s.id}
                    onClick={() => handleTestConnection(s.id)}
                  >
                    {isTesting === s.id ? 'Probando...' : 'Probar Conexión'}
                  </Button>

                  {isAdmin && (
                    <div className="flex items-center space-x-1">
                      <button
                        onClick={() => handleOpenEdit(s)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-400 hover:bg-slate-800 transition-colors"
                        title="Editar Servidor"
                      >
                        <Edit className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(s)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                        title="Eliminar Servidor"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Create / Edit Server Modal matching exact legacy _form_servidor.html */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md glass-panel p-6 rounded-2xl border border-slate-800 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-slate-100">
                {editingServer ? `Editar Servidor: ${editingServer.nombre}` : 'Agregar Nuevo Servidor'}
              </h3>
              <button onClick={() => setIsModalOpen(false)} className="text-slate-400 hover:text-slate-200 text-xl font-bold">×</button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 font-medium mb-1">Nombre del Servidor *</label>
                <input
                  type="text"
                  required
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  placeholder="ej. Horizon DT Principal"
                  className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-medium mb-1">Host / IP *</label>
                <input
                  type="text"
                  required
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="ej. horizon.empresa.com"
                  className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 font-medium mb-1">Tipo de Servidor *</label>
                  <select
                    value={tipo}
                    onChange={(e) => setTipo(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="horizon">HORIZON</option>
                    <option value="vcenter">VCENTER</option>
                    <option value="appvolumes">APP VOLUMES</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 font-medium mb-1">Tipo de Máquinas *</label>
                  <select
                    value={tipoMaquina}
                    onChange={(e) => setTipoMaquina(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="VDI">VDI</option>
                    <option value="VM">VM</option>
                    <option value="ambos">Ambos</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 font-medium mb-1">Origen</label>
                  <select
                    value={origen}
                    onChange={(e) => setOrigen(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500 uppercase"
                  >
                    <option value="dt">DT</option>
                    <option value="su">SU</option>
                    <option value="core">CORE</option>
                    <option value="mz">MZ</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 font-medium mb-1">Dominio por Defecto</label>
                  <input
                    type="text"
                    value={dominio}
                    onChange={(e) => setDominio(e.target.value)}
                    placeholder="ej. CORP"
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              {/* Security info banner matching exact legacy form */}
              <div className="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-[11px] text-indigo-300">
                🔒 Las credenciales (Usuario / Contraseña) no se almacenan en la base de datos por seguridad. Se ingresan por sesión mediante el botón de credenciales vCenter en la barra superior.
              </div>

              <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
                <Button type="button" variant="secondary" size="sm" onClick={() => setIsModalOpen(false)} disabled={isSaving}>
                  Cancelar
                </Button>
                <Button type="submit" variant="primary" size="sm" disabled={isSaving}>
                  {isSaving ? 'Guardando...' : (editingServer ? 'Guardar Cambios' : 'Crear Servidor')}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
