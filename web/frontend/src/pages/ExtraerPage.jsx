import React, { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { VcSessionModal } from '../components/modals/VcSessionModal';
import { SseConsole } from '../components/common/SseConsole';
import { toastError } from '../utils/alerts';
import { 
  Zap, 
  Server, 
  Play, 
  CheckCircle, 
  AlertCircle, 
  RefreshCw, 
  Key, 
  Terminal, 
  Activity,
  Layers,
  CheckSquare,
  Square
} from 'lucide-react';

export function ExtraerPage() {
  const [selectedServers, setSelectedServers] = useState([]);
  const [mantenerCorrecciones, setMantenerCorrecciones] = useState(true);
  const [searchEngine, setSearchEngine] = useState('powercli'); // 'powercli' | 'vsphere_rest_test'
  const [isVcModalOpen, setIsVcModalOpen] = useState(false);

  // Extraction Job state
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null); // 'idle' | 'running' | 'completed' | 'error'
  const [progressPct, setProgressPct] = useState(0);
  const [progressMsg, setProgressMsg] = useState('');
  const [logEvents, setLogEvents] = useState([]);

  const logEndRef = useRef(null);

  // Check vCenter session status
  const { data: vcStatus, refetch: refetchVcStatus } = useQuery({
    queryKey: ['vc_status'],
    queryFn: () => api.get('/auth/vc_status'),
    refetchInterval: 10000,
  });

  // Detecta si hay una extracción corriendo (manual de otra pestaña, o automática
  // del scheduler) para engancharse a su stream SSE en vivo aunque esta pestaña no
  // la haya disparado. Solo se pollea mientras no estamos ya enganchados a un job.
  const { data: activeJobData } = useQuery({
    queryKey: ['active_job'],
    queryFn: () => api.get('/inventario/active_job'),
    refetchInterval: jobStatus === 'running' ? false : 4000,
  });

  useEffect(() => {
    if (jobStatus === 'running') return;
    const activeJob = activeJobData?.active ? activeJobData.job : null;
    if (activeJob?.job_id) {
      setJobId(activeJob.job_id);
      setJobStatus('running');
      setProgressPct(activeJob.pct || 0);
      setProgressMsg(activeJob.msg || 'Extracción en curso (detectada en segundo plano)...');
      setLogEvents([{
        time: new Date().toLocaleTimeString(),
        type: 'info',
        msg: `Enganchado a extracción en curso — Job #${activeJob.job_id}`,
      }]);
    }
  }, [activeJobData, jobId]);

  // Fetch servers list
  const { data: servidores, isLoading: isLoadingServidores } = useQuery({
    queryKey: ['servidores'],
    queryFn: () => api.get('/servidores'),
  });

  // Auto-select servidores activos: no solo al cargar la lista por primera vez --
  // si aparece un servidor nuevo (recién dado de alta, ej. App Volumes) mientras la
  // página ya estaba abierta con otros ya tildados, también se suma solo. Antes esto
  // corría una única vez (guardia selectedServers.length === 0), así que un servidor
  // activado después del primer load quedaba desmarcado en silencio -- se veía "todo
  // seleccionado" en el contador pero ese servidor nunca entraba a la extracción.
  const seenServerIdsRef = useRef(new Set());
  useEffect(() => {
    if (!servidores) return;
    const nuevosActivos = servidores.filter(s => s.activo && !seenServerIdsRef.current.has(s.id));
    if (nuevosActivos.length > 0) {
      setSelectedServers((prev) => Array.from(new Set([...prev, ...nuevosActivos.map(s => s.id)])));
    }
    servidores.forEach(s => seenServerIdsRef.current.add(s.id));
  }, [servidores]);

  // Auto-scroll logs to bottom
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logEvents]);

  // SSE Stream listener for job progress
  useEffect(() => {
    if (!jobId) return;

    const eventSource = new EventSource(`/inventario/stream/${jobId}`);

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.tipo === 'ping') return;

        if (data.tipo === 'pct') {
          setProgressPct(parseInt(data.msg, 10) || 0);
          return;
        }

        if (data.tipo === 'progress') {
          setProgressMsg(data.msg);
          return;
        }

        if (data.tipo === 'log') {
          setLogEvents((prev) => [...prev, {
            time: new Date().toLocaleTimeString(),
            type: 'info',
            msg: data.msg
          }]);
        }

        if (data.tipo === 'done') {
          setJobStatus('completed');
          setProgressPct(100);
          eventSource.close();
        } else if (data.tipo === 'error') {
          setJobStatus('error');
          eventSource.close();
        } else if (data.tipo === 'cancelled') {
          setJobStatus('cancelled');
          eventSource.close();
        }
      } catch (err) {
        console.error('Error parsing SSE event', err);
      }
    };

    eventSource.onerror = () => {
      console.warn('SSE EventSource disconnected');
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [jobId]);

  const handleToggleSelectAll = () => {
    if (selectedServers.length === servidores?.length) {
      setSelectedServers([]);
    } else {
      setSelectedServers(servidores?.map(s => s.id) || []);
    }
  };

  const handleToggleServer = (sid) => {
    if (selectedServers.includes(sid)) {
      setSelectedServers(selectedServers.filter(id => id !== sid));
    } else {
      setSelectedServers([...selectedServers, sid]);
    }
  };

  const handleStartExtraction = async () => {
    if (!vcStatus?.has_credentials) {
      setIsVcModalOpen(true);
      return;
    }

    if (selectedServers.length === 0) {
      toastError('Por favor seleccioná al menos un servidor para escanear.');
      return;
    }

    try {
      setJobStatus('running');
      setProgressPct(0);
      setProgressMsg('Inicializando sesión e hilos de escaneo...');
      setLogEvents([{ time: new Date().toLocaleTimeString(), type: 'info', msg: 'Escaneo iniciado bajo demanda' }]);

      const res = await api.post('/inventario/extraer_json', {
        servidor_ids: selectedServers,
        mantener_correcciones: mantenerCorrecciones
      });

      if (res.job_id) {
        setJobId(res.job_id);
      }
    } catch (e) {
      setJobStatus('error');
      const errDetail = e?.response?.data?.error || e.message;
      setProgressMsg(`Error al iniciar escaneo: ${errDetail}`);
      if (errDetail.includes('contraseña') || errDetail.includes('sesión')) {
        setIsVcModalOpen(true);
      }
    }
  };

  const [cancelling, setCancelling] = useState(false);

  const handleCancelExtraction = async () => {
    if (!jobId || jobStatus !== 'running') return;
    setCancelling(true);
    try {
      await api.post(`/inventario/cancelar/${jobId}`);
      setLogEvents((prev) => [...prev, {
        time: new Date().toLocaleTimeString(),
        type: 'info',
        msg: 'Cancelación solicitada — se corta entre fases, no es instantáneo.',
      }]);
    } catch (e) {
      // Si ya terminó justo antes de cancelar, no hay nada que hacer.
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-900/60 p-6 rounded-2xl border border-slate-800 backdrop-blur-md">
        <div>
          <h1 className="text-2xl font-black text-slate-100 tracking-tight flex items-center gap-2">
            <Zap className="w-7 h-7 text-indigo-400" />
            <span>Extracción de Información</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Extrae y sincroniza el inventario completo de Horizon CS y vCenter en tiempo real con monitoreo SSE.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Server Selector */}
        <div className="lg:col-span-1 space-y-6">
          <Card title="Servidores a Extraer" subtitle="Selecciona cuáles consultar">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <button
                  type="button"
                  onClick={handleToggleSelectAll}
                  className="text-xs font-semibold text-indigo-400 hover:text-indigo-300"
                >
                  {selectedServers.length === (servidores?.length || 0) ? 'Desmarcar Todos' : 'Marcar Todos'}
                </button>
                <span className="text-xs text-slate-400 font-mono">
                  {selectedServers.length} / {servidores?.length || 0} seleccionados
                </span>
              </div>

              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {servidores?.map((s) => (
                  <div
                    key={s.id}
                    onClick={() => handleToggleServer(s.id)}
                    className={`p-3 rounded-xl border flex items-center justify-between cursor-pointer transition-all ${
                      selectedServers.includes(s.id)
                        ? 'bg-indigo-500/10 border-indigo-500/30 text-slate-100'
                        : 'bg-slate-900/40 border-slate-800/80 text-slate-400 hover:bg-slate-800/50'
                    }`}
                  >
                    <div className="flex items-center space-x-3">
                      <input
                        type="checkbox"
                        checked={selectedServers.includes(s.id)}
                        onChange={() => {}}
                        className="w-4 h-4 accent-indigo-500 rounded"
                      />
                      <div>
                        <div className="text-xs font-bold">{s.nombre}</div>
                        <div className="text-[10px] text-slate-500 font-mono">{s.ip}</div>
                      </div>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold font-mono bg-slate-800 text-indigo-300">
                      {s.tipo}
                    </span>
                  </div>
                ))}
              </div>

              <div className="pt-3 border-t border-slate-800 space-y-3">

                <label className="flex items-center space-x-2 text-xs text-slate-300 cursor-pointer pt-1">
                  <input
                    type="checkbox"
                    checked={mantenerCorrecciones}
                    onChange={(e) => setMantenerCorrecciones(e.target.checked)}
                    className="w-4 h-4 accent-indigo-500 rounded"
                  />
                  <span>Preservar correcciones manuales de usuarios</span>
                </label>
              </div>

              <Button
                variant="primary"
                size="md"
                icon={Play}
                disabled={jobStatus === 'running' || selectedServers.length === 0}
                onClick={handleStartExtraction}
                className="w-full justify-center"
              >
                {jobStatus === 'running' ? 'Extrayendo Información...' : 'Iniciar Extracción de Información'}
              </Button>
            </div>
          </Card>
        </div>

        {/* Right Column: Live Progress & SSE Log Stream */}
        <div className="lg:col-span-2 space-y-6">
          <SseConsole
            jobStatus={jobStatus}
            progressPct={progressPct}
            progressMsg={progressMsg}
            logEvents={logEvents}
            onClearLogs={() => setLogEvents([])}
            onStartExtraction={handleStartExtraction}
            canStart={selectedServers.length > 0 && jobStatus !== 'running'}
            selectedCount={selectedServers.length}
            onCancel={handleCancelExtraction}
            cancelling={cancelling}
          />
        </div>
      </div>

      {/* Modal credentials vCenter */}
      <VcSessionModal 
        isOpen={isVcModalOpen}
        onClose={() => setIsVcModalOpen(false)}
        onSaved={() => {
          setIsVcModalOpen(false);
          refetchVcStatus();
        }}
      />
    </div>
  );
}
