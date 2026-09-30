import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../services/api';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Zap, X, CheckCircle2, AlertTriangle, Play, Server, Lock } from 'lucide-react';

export function ExtraerModal({ isOpen, onClose, onCompleted }) {
  const [selectedServers, setSelectedServers] = useState([]);
  const [vcPassword, setVcPassword] = useState('');
  const [searchEngine, setSearchEngine] = useState('powercli'); // 'powercli' | 'vsphere_rest_test'
  const [keepCorrections, setKeepCorrections] = useState(true);
  
  const [jobId, setJobId] = useState(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [pct, setPct] = useState(0);
  const [currentMsg, setCurrentMsg] = useState('');
  const [logs, setLogs] = useState([]);
  const [jobStatus, setJobStatus] = useState(null); // 'done' | 'error'

  const { data: servidores } = useQuery({
    queryKey: ['servidores'],
    queryFn: () => api.get('/servidores'),
    enabled: isOpen,
  });

  const handleToggleServer = (id) => {
    if (selectedServers.includes(id)) {
      setSelectedServers(selectedServers.filter(s => s !== id));
    } else {
      setSelectedServers([...selectedServers, id]);
    }
  };

  const handleStartExtraction = async (e) => {
    e.preventDefault();
    if (selectedServers.length === 0) return;

    try {
      setIsExtracting(true);
      setLogs([]);
      setPct(0);
      setJobStatus(null);
      setCurrentMsg('Iniciando tarea de extracción...');

      // Call extraction POST
      const res = await api.post('/inventario/extraer_json', {
        servidor_ids: selectedServers,
        vc_password: vcPassword || 'session_active',
        mantener_correcciones: keepCorrections
      });

      if (res.job_id) {
        setJobId(res.job_id);
      }
    } catch (err) {
      setIsExtracting(false);
      setJobStatus('error');
      setCurrentMsg(err.response?.data?.error || 'Error al iniciar extracción');
    }
  };

  // SSE Listener for real-time progress
  useEffect(() => {
    if (!jobId) return;

    const eventSource = new EventSource(`/inventario/stream/${jobId}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.tipo === 'pct') {
          setPct(parseInt(data.msg) || 0);
        } else if (data.tipo === 'progress') {
          setCurrentMsg(data.msg);
        } else if (data.tipo === 'log') {
          setLogs(prev => [...prev.slice(-40), data.msg]);
        } else if (data.tipo === 'done') {
          setPct(100);
          setJobStatus('done');
          setIsExtracting(false);
          eventSource.close();
          if (onCompleted) onCompleted();
        } else if (data.tipo === 'error') {
          setJobStatus('error');
          setIsExtracting(false);
          eventSource.close();
        }
      } catch (e) {
        // SSE parse error
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [jobId]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-xl glass-panel p-6 rounded-2xl border border-slate-800 shadow-2xl space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <Zap className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-100">Nueva Extracción de Inventario</h3>
              <p className="text-xs text-slate-400">Horizon CS & vCenter Real-Time Extraction</p>
            </div>
          </div>
          {!isExtracting && (
            <button onClick={onClose} className="text-slate-400 hover:text-slate-200 text-xl font-bold">×</button>
          )}
        </div>

        {!isExtracting && !jobStatus ? (
          <form onSubmit={handleStartExtraction} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                1. Seleccionar Servidores Activos
              </label>
              <div className="space-y-2 max-h-40 overflow-y-auto pr-1">
                {servidores?.map((s) => (
                  <label key={s.id} className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 cursor-pointer hover:border-slate-700">
                    <div className="flex items-center space-x-3">
                      <input 
                        type="checkbox"
                        checked={selectedServers.includes(s.id)}
                        onChange={() => handleToggleServer(s.id)}
                        className="w-4 h-4 accent-indigo-600 rounded"
                      />
                      <span className="text-xs font-semibold text-slate-200">{s.nombre} ({s.host})</span>
                    </div>
                    <Badge variant="info">{s.tipo}</Badge>
                  </label>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                2. Contraseña de Sesión vCenter / Horizon (opcional si ya está guardada)
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="password"
                  value={vcPassword}
                  onChange={(e) => setVcPassword(e.target.value)}
                  placeholder="Contraseña de red (dejar en blanco para usar guardada)"
                  className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-4 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <input
                type="checkbox"
                id="keepCorr"
                checked={keepCorrections}
                onChange={(e) => setKeepCorrections(e.target.checked)}
                className="w-4 h-4 accent-indigo-600 rounded"
              />
              <label htmlFor="keepCorr" className="text-xs text-slate-300">
                Mantener correcciones manuales anteriores
              </label>
            </div>

            <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
              <Button type="button" variant="secondary" size="sm" onClick={onClose}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" size="sm" icon={Play} disabled={selectedServers.length === 0}>
                Iniciar Extracción
              </Button>
            </div>
          </form>
        ) : (
          /* Live Streaming Progress Screen */
          <div className="space-y-4 py-2">
            <div>
              <div className="flex justify-between text-xs font-bold text-slate-200 mb-1.5">
                <span>{currentMsg}</span>
                <span className="font-mono">{pct}%</span>
              </div>
              <div className="w-full bg-slate-900 rounded-full h-3 overflow-hidden border border-slate-800">
                <div 
                  className="bg-gradient-to-r from-indigo-500 to-emerald-400 h-full transition-all duration-300"
                  style={{ width: `${pct}%` }}
                ></div>
              </div>
            </div>

            {/* Terminal Live Log Window */}
            <div className="bg-slate-950 border border-slate-800 rounded-xl p-3 h-48 overflow-y-auto font-mono text-[11px] text-slate-300 space-y-1">
              {logs.map((l, i) => (
                <div key={i} className="leading-tight text-slate-400">
                  <span className="text-indigo-400">❯</span> {l}
                </div>
              ))}
            </div>

            {jobStatus === 'done' && (
              <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-xs font-semibold flex items-center justify-between">
                <span className="flex items-center"><CheckCircle2 className="w-4 h-4 mr-2" /> Extracción completada con éxito!</span>
                <Button variant="primary" size="sm" onClick={onClose}>Listo</Button>
              </div>
            )}

            {jobStatus === 'error' && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-400 text-xs font-semibold flex items-center justify-between">
                <span className="flex items-center"><AlertTriangle className="w-4 h-4 mr-2" /> Error durante la extracción</span>
                <Button variant="secondary" size="sm" onClick={() => { setJobStatus(null); setIsExtracting(false); }}>Reintentar</Button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
