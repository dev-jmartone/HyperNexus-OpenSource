import React, { useState, useEffect, useRef, useMemo } from 'react';
import { 
  Terminal, 
  Activity, 
  CheckCircle2, 
  AlertTriangle, 
  XCircle, 
  Copy, 
  Check, 
  Trash2, 
  ArrowDown, 
  Search, 
  Maximize2, 
  Minimize2, 
  Clock, 
  Zap, 
  ShieldCheck, 
  Cpu, 
  Sparkles, 
  Radio,
  FileCode,
  Ban,
  Loader2
} from 'lucide-react';

export function SseConsole({
  jobStatus,
  progressPct,
  progressMsg,
  logEvents = [],
  onClearLogs,
  onStartExtraction,
  canStart,
  selectedCount = 0,
  onCancel,
  cancelling = false
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [copied, setCopied] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const logContainerRef = useRef(null);
  const timerRef = useRef(null);

  // Live timer during job run
  useEffect(() => {
    if (jobStatus === 'running') {
      setElapsedSeconds(0);
      timerRef.current = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [jobStatus]);

  // Auto scroll logic
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logEvents, autoScroll]);

  const formatTimer = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Filtered log entries based on search query
  const filteredLogs = useMemo(() => {
    if (!searchQuery.trim()) return logEvents;
    const q = searchQuery.toLowerCase();
    return logEvents.filter(
      (log) =>
        (log.msg || '').toLowerCase().includes(q) ||
        (log.time || '').toLowerCase().includes(q) ||
        (log.type || '').toLowerCase().includes(q)
    );
  }, [logEvents, searchQuery]);

  const handleCopyLogs = () => {
    const text = logEvents
      .map((l) => `[${l.time}] ${l.msg}`)
      .join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Determine current active phase based on logEvents stream, progress %, and jobStatus
  const currentPhase = useMemo(() => {
    if (jobStatus === 'completed' || progressPct >= 100) return 4;

    // Scan logEvents backwards to detect active phase from real backend log output
    for (let i = logEvents.length - 1; i >= 0; i--) {
      const msg = logEvents[i]?.msg || '';
      if (msg.includes('Fase 3') || msg.includes('Reconciliación') || msg.includes('Integridad')) {
        return 4;
      }
      if (msg.includes('Fase 2') || msg.includes('vCenter REST') || msg.includes('vCenter') || msg.includes('VCenter')) {
        return 3;
      }
      if (msg.includes('Fase 1') || msg.includes('Horizon REST') || msg.includes('Horizon')) {
        return 2;
      }
    }

    if (jobStatus === 'running' || logEvents.length > 0) return 1;
    return 0;
  }, [logEvents, jobStatus, progressPct]);

  const phases = [
    { id: 1, name: 'Autenticación', desc: 'Credenciales & Sesión' },
    { id: 2, name: 'Horizon CS', desc: 'Extracción Servidores VDI' },
    { id: 3, name: 'vCenter REST', desc: 'Extracción Infraestructura' },
    { id: 4, name: 'Reconciliación', desc: 'Auditoría & Guardado DB' },
  ];

  // Helper to parse log text and colorize badges, file paths, and tags
  const renderFormattedLogMessage = (msg) => {
    if (!msg) return null;

    // Highlight file paths like 'data/audit_reconciliacion.json' or 'data/audit_vms_diagnostico.log'
    const parts = msg.split(/('(?:data|logs|config)\/[^']+')/g);

    return (
      <span className="leading-relaxed">
        {parts.map((part, i) => {
          if (part.startsWith("'") && part.endsWith("'")) {
            return (
              <span
                key={i}
                className="inline-flex items-center gap-1 mx-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-indigo-500/15 text-indigo-300 border border-indigo-500/30"
              >
                <FileCode className="w-3 h-3 text-indigo-400 shrink-0" />
                {part.replace(/'/g, '')}
              </span>
            );
          }

          // Parse known tag brackets like [Fase 3], [Auditoría Diagnóstica], [vCenter DT], [Motor Reconciliacion]
          const subParts = part.split(/(\[[^\]]+\])/g);

          return subParts.map((sub, j) => {
            if (sub.startsWith('[') && sub.endsWith(']')) {
              const tagContent = sub.slice(1, -1);
              let badgeStyle = 'bg-slate-800 text-slate-300 border-slate-700';

              if (tagContent.toLowerCase().includes('fase')) {
                badgeStyle = 'bg-sky-500/20 text-sky-300 border-sky-500/40 font-bold';
              } else if (tagContent.toLowerCase().includes('auditoría') || tagContent.toLowerCase().includes('diagnóstica')) {
                badgeStyle = 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40 font-semibold';
              } else if (tagContent.toLowerCase().includes('reconciliac')) {
                badgeStyle = 'bg-purple-500/20 text-purple-300 border-purple-500/40 font-semibold';
              } else if (tagContent.toLowerCase().includes('vcenter') || tagContent.toLowerCase().includes('horizon')) {
                badgeStyle = 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30 font-medium';
              }

              return (
                <span
                  key={j}
                  className={`inline-block mx-1 px-1.5 py-0.2 rounded text-[10px] uppercase font-mono border ${badgeStyle}`}
                >
                  {tagContent}
                </span>
              );
            }
            return sub;
          });
        })}
      </span>
    );
  };

  return (
    <div className={`space-y-4 ${isFullscreen ? 'fixed inset-4 z-50 bg-slate-950 p-6 rounded-2xl border border-slate-700 shadow-2xl flex flex-col justify-between overflow-hidden' : ''}`}>
      {/* Upper Progress & Phase Status Panel */}
      <div className="bg-slate-900/80 border border-slate-800/80 rounded-2xl p-5 backdrop-blur-xl shadow-xl space-y-4">
        {/* Main Status Bar & Big Percentage */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center space-x-3.5">
            <div className={`p-3 rounded-xl border flex items-center justify-center transition-all ${
              jobStatus === 'running' ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-400 animate-pulse' :
              jobStatus === 'completed' ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400' :
              jobStatus === 'error' ? 'bg-rose-500/20 border-rose-500/40 text-rose-400' :
              jobStatus === 'cancelled' ? 'bg-amber-500/20 border-amber-500/40 text-amber-400' :
              'bg-slate-800/60 border-slate-700 text-slate-400'
            }`}>
              {jobStatus === 'running' && <Activity className="w-5 h-5 animate-spin" />}
              {jobStatus === 'completed' && <CheckCircle2 className="w-5 h-5" />}
              {jobStatus === 'error' && <XCircle className="w-5 h-5" />}
              {jobStatus === 'cancelled' && <Ban className="w-5 h-5" />}
              {(!jobStatus || jobStatus === 'idle') && <Radio className="w-5 h-5" />}
            </div>

            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Estado SSE:
                </span>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border flex items-center gap-1 ${
                  jobStatus === 'running' ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40' :
                  jobStatus === 'completed' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' :
                  jobStatus === 'error' ? 'bg-rose-500/20 text-rose-300 border-rose-500/40' :
                  jobStatus === 'cancelled' ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' :
                  'bg-slate-800 text-slate-400 border-slate-700'
                }`}>
                  {jobStatus === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-ping" />}
                  {jobStatus === 'running' ? 'Extrayendo...' :
                   jobStatus === 'completed' ? 'Completado' :
                   jobStatus === 'error' ? 'Error' :
                   jobStatus === 'cancelled' ? 'Cancelado' : 'En Espera'}
                </span>
              </div>
              <p className="text-sm font-bold text-slate-100 mt-0.5 flex items-center gap-2">
                <span>{progressMsg || 'Esperando inicio de extracción...'}</span>
              </p>
            </div>
          </div>

          {/* Right Metrics Cards */}
          <div className="flex items-center gap-3">
            {jobStatus === 'running' && (
              <div className="px-3 py-1.5 bg-slate-950/60 border border-slate-800 rounded-xl text-center">
                <div className="text-[10px] text-slate-500 uppercase font-mono">Tiempo</div>
                <div className="text-xs font-bold text-slate-200 font-mono flex items-center justify-center gap-1">
                  <Clock className="w-3 h-3 text-indigo-400" />
                  {formatTimer(elapsedSeconds)}
                </div>
              </div>
            )}

            <div className="px-3 py-1.5 bg-slate-950/60 border border-slate-800 rounded-xl text-center">
              <div className="text-[10px] text-slate-500 uppercase font-mono">Eventos</div>
              <div className="text-xs font-bold text-slate-200 font-mono">{logEvents.length}</div>
            </div>

            <div className="px-4 py-2 bg-gradient-to-br from-slate-950 to-slate-900 border border-slate-800 rounded-2xl text-right min-w-[90px] shadow-inner">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Progreso</div>
              <div className={`text-xl font-black font-mono tracking-tight ${
                jobStatus === 'completed' ? 'text-emerald-400' :
                jobStatus === 'error' ? 'text-rose-400' :
                jobStatus === 'cancelled' ? 'text-amber-400' :
                'text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-sky-400'
              }`}>
                {progressPct}%
              </div>
            </div>

            {jobStatus === 'running' && onCancel && (
              <button
                type="button"
                onClick={onCancel}
                disabled={cancelling}
                title="Cancelar extracción en curso"
                className="flex items-center gap-1.5 px-3 py-2 bg-rose-600/90 hover:bg-rose-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl text-xs font-bold transition-all shadow-lg shadow-rose-500/20"
              >
                {cancelling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
                <span>{cancelling ? 'Cancelando...' : 'Cancelar'}</span>
              </button>
            )}
          </div>
        </div>

        {/* Animated Smooth Progress Bar */}
        <div className="relative w-full bg-slate-950 h-3.5 rounded-full overflow-hidden border border-slate-800/80 p-0.5 shadow-inner">
          <div
            className={`h-full rounded-full transition-all duration-500 relative overflow-hidden ${
              jobStatus === 'completed'
                ? 'bg-gradient-to-r from-emerald-600 via-emerald-500 to-teal-400 shadow-lg shadow-emerald-500/20'
                : jobStatus === 'error'
                ? 'bg-gradient-to-r from-rose-600 to-rose-500'
                : jobStatus === 'cancelled'
                ? 'bg-gradient-to-r from-amber-600 to-amber-500'
                : 'bg-gradient-to-r from-indigo-600 via-indigo-500 to-sky-400'
            }`}
            style={{ width: `${progressPct}%` }}
          >
            {jobStatus === 'running' && (
              <div className="absolute inset-0 bg-white/20 animate-[shimmer_1.5s_infinite] bg-[linear-gradient(90deg,transparent_0%,rgba(255,255,255,0.4)_50%,transparent_100%)] bg-[length:200%_100%]" />
            )}
          </div>
        </div>

        {/* 4-Step Visual Phase Stepper */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-2 border-t border-slate-800/60">
          {phases.map((p) => {
            const isDone = currentPhase > p.id || jobStatus === 'completed';
            const isActive = currentPhase === p.id && jobStatus === 'running';

            return (
              <div
                key={p.id}
                className={`p-2.5 rounded-xl border transition-all flex items-center space-x-2.5 ${
                  isDone
                    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                    : isActive
                    ? 'bg-indigo-500/20 border-indigo-500/50 text-indigo-200 shadow-md shadow-indigo-500/10'
                    : 'bg-slate-950/40 border-slate-800/60 text-slate-500'
                }`}
              >
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                    isDone
                      ? 'bg-emerald-500 text-slate-950 font-black'
                      : isActive
                      ? 'bg-indigo-500 text-white animate-bounce'
                      : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {isDone ? <Check className="w-3.5 h-3.5 stroke-[3]" /> : p.id}
                </div>
                <div className="min-w-0">
                  <div className="text-[11px] font-bold truncate leading-tight">{p.name}</div>
                  <div className="text-[9px] text-slate-400 truncate mt-0.5">{p.desc}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Main Terminal Window */}
      <div className={`bg-slate-950 border border-slate-800/90 rounded-2xl overflow-hidden shadow-2xl flex flex-col ${isFullscreen ? 'flex-1 min-h-0' : ''}`}>
        {/* Terminal Header Bar with Mac OS dots & Action Buttons */}
        <div className="px-4 py-2.5 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between gap-3 text-xs">
          {/* OS Window Controls */}
          <div className="flex items-center space-x-2">
            <div className="flex space-x-1.5 mr-2">
              <span className="w-3 h-3 rounded-full bg-rose-500/80 inline-block border border-rose-600/40" />
              <span className="w-3 h-3 rounded-full bg-amber-500/80 inline-block border border-amber-600/40" />
              <span className="w-3 h-3 rounded-full bg-emerald-500/80 inline-block border border-emerald-600/40" />
            </div>
            <span className="text-slate-300 font-bold font-mono flex items-center gap-1.5 text-[11px]">
              <Terminal className="w-4 h-4 text-indigo-400" />
              <span>Consola SSE de Eventos</span>
            </span>
          </div>

          {/* Controls: Search, AutoScroll, Copy, Clear, Fullscreen */}
          <div className="flex items-center space-x-2">
            {/* Search Filter */}
            <div className="relative flex items-center">
              <Search className="w-3 h-3 text-slate-500 absolute left-2 pointer-events-none" />
              <input
                type="text"
                placeholder="Filtrar logs..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-7 pr-2 py-1 bg-slate-950 border border-slate-800 rounded-lg text-[11px] font-mono text-slate-200 focus:outline-none focus:border-indigo-500/50 w-28 sm:w-40 transition-all placeholder:text-slate-600"
              />
            </div>

            {/* AutoScroll Toggle Button */}
            <button
              type="button"
              onClick={() => setAutoScroll(!autoScroll)}
              title={autoScroll ? 'Auto-scroll activo' : 'Auto-scroll desactivado'}
              className={`p-1.5 rounded-lg border text-[11px] font-mono flex items-center gap-1 transition-all ${
                autoScroll
                  ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40'
                  : 'bg-slate-900 text-slate-500 border-slate-800 hover:text-slate-300'
              }`}
            >
              <ArrowDown className={`w-3.5 h-3.5 ${autoScroll ? 'animate-pulse' : ''}`} />
              <span className="hidden md:inline">AutoScroll</span>
            </button>

            {/* Copy Logs Button */}
            <button
              type="button"
              onClick={handleCopyLogs}
              disabled={logEvents.length === 0}
              title="Copiar logs al portapapeles"
              className="p-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 disabled:opacity-40 border border-slate-800 rounded-lg transition-all flex items-center gap-1 text-[11px]"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5 text-indigo-400" />}
              <span className="hidden sm:inline">{copied ? 'Copiado' : 'Copiar'}</span>
            </button>

            {/* Clear Logs Button */}
            {onClearLogs && (
              <button
                type="button"
                onClick={onClearLogs}
                disabled={logEvents.length === 0}
                title="Limpiar consola"
                className="p-1.5 bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-rose-400 disabled:opacity-40 border border-slate-800 rounded-lg transition-all text-[11px]"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}

            {/* Fullscreen Expand Toggle */}
            <button
              type="button"
              onClick={() => setIsFullscreen(!isFullscreen)}
              title={isFullscreen ? 'Contraer' : 'Pantalla Completa'}
              className="p-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 rounded-lg transition-all text-[11px]"
            >
              {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* Console Log Lines Stream */}
        <div
          ref={logContainerRef}
          className={`p-4 font-mono text-xs overflow-y-auto space-y-1 bg-slate-950 text-slate-200 selection:bg-indigo-500/30 selection:text-white ${
            isFullscreen ? 'flex-1' : 'h-80'
          }`}
        >
          {filteredLogs.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-600 py-12 space-y-2 select-none">
              <Sparkles className="w-8 h-8 text-slate-700 animate-pulse" />
              <p className="text-xs">
                {searchQuery ? 'No hay logs que coincidan con la búsqueda.' : 'Presiona "Iniciar Extracción" para transmitir logs SSE en tiempo real.'}
              </p>
            </div>
          ) : (
            filteredLogs.map((log, idx) => (
              <div
                key={idx}
                className="group flex items-start space-x-2.5 px-2 py-1 rounded hover:bg-slate-900/60 transition-colors border border-transparent hover:border-slate-800/40 text-[11.5px]"
              >
                {/* Line Index */}
                <span className="text-slate-600 text-[10px] select-none w-7 text-right shrink-0 font-mono pt-0.5">
                  {idx + 1}
                </span>

                {/* Timestamp */}
                <span className="text-slate-500 text-[10px] shrink-0 font-mono pt-0.5">
                  [{log.time}]
                </span>

                {/* Log Content with badged styling */}
                <div className="flex-1 min-w-0">
                  {renderFormattedLogMessage(log.msg)}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
