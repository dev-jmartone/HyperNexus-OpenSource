import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { FileText, Download, RefreshCw, BarChart2, CheckCircle2, AlertCircle, Clock, Server } from 'lucide-react';

export function ReportesPage() {
  const [tipo, setTipo] = useState('');
  const [origen, setOrigen] = useState('');
  const [servidorId, setServidorId] = useState('');

  const [isGenerating, setIsGenerating] = useState(false);
  const [genStatus, setGenStatus] = useState(null);

  const { data: servidores } = useQuery({
    queryKey: ['servidores'],
    queryFn: () => api.get('/servidores'),
  });

  const { data: archivos, refetch: refetchArchivos, isLoading: isLoadingArchivos } = useQuery({
    queryKey: ['reportes_archivos'],
    queryFn: () => api.get('/reportes/archivos'),
  });

  const { data: snapshots, isLoading: isLoadingSnapshots } = useQuery({
    queryKey: ['snapshots'],
    queryFn: () => api.get('/snapshots'),
  });

  const handleGenerarReporte = async (e) => {
    e.preventDefault();
    try {
      setIsGenerating(true);
      setGenStatus('Generando libro de trabajo Excel multi-hoja...');
      const res = await api.post('/reportes/generar', {
        tipo, origen, servidor_id: servidorId
      });
      setIsGenerating(false);
      setGenStatus(`¡Reporte '${res.filename}' generado con éxito!`);
      refetchArchivos();
      if (res.download_url) {
        const link = document.createElement('a');
        link.href = res.download_url;
        link.setAttribute('download', res.filename || 'reporte.xlsx');
        document.body.appendChild(link);
        link.click();
        link.remove();
      }
      setTimeout(() => setGenStatus(null), 5000);
    } catch (err) {
      setIsGenerating(false);
      setGenStatus('Error al generar el reporte Excel: ' + (err?.response?.data?.error || err.message));
    }
  };


  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: List of generated reports */}
        <div className="lg:col-span-2 space-y-6">
          <Card 
            title="Archivos de Reportes Excel Generados" 
            subtitle="Libros de trabajo multitabla descargables"
            action={
              <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => refetchArchivos()}>
                Actualizar Lista
              </Button>
            }
          >
            {isLoadingArchivos ? (
              <div className="py-16 text-center text-slate-400 animate-pulse">Cargando reportes almacenados...</div>
            ) : archivos?.length === 0 ? (
              <div className="py-12 text-center text-slate-500">No se han generado reportes en el servidor.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300 border-collapse">
                  <thead className="bg-slate-900 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                    <tr>
                      <th className="py-3 px-4">Nombre del Archivo</th>
                      <th className="py-3 px-4">Tamaño</th>
                      <th className="py-3 px-4">Fecha Modificación</th>
                      <th className="py-3 px-4 text-center">Acción</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {archivos?.map((arch, idx) => (
                      <tr key={idx} className="hover:bg-slate-800/40 transition-colors">
                        <td className="py-3 px-4 font-mono font-bold text-indigo-400 flex items-center">
                          <FileText className="w-4 h-4 mr-2 text-indigo-400 shrink-0" />
                          {arch.nombre}
                        </td>
                        <td className="py-3 px-4 font-mono text-slate-400">{arch.size_kb} KB</td>
                        <td className="py-3 px-4 text-slate-300 font-mono">{arch.fecha}</td>
                        <td className="py-3 px-4 text-center">
                          <a
                            href={arch.download_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center space-x-1 px-3 py-1 bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 rounded-lg hover:bg-emerald-600/30 font-medium text-xs transition-colors"
                          >
                            <Download className="w-3.5 h-3.5" />
                            <span>Descargar</span>
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* Snapshots History Table */}
          <Card title="📈 Historial de Snapshots por Servidor" subtitle="Registro de ejecuciones de escaneo">
            {isLoadingSnapshots ? (
              <div className="py-12 text-center text-slate-400 animate-pulse">Cargando snapshots...</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300 border-collapse">
                  <thead className="bg-slate-900 uppercase text-[10px] text-slate-400 font-semibold border-b border-slate-800">
                    <tr>
                      <th className="py-2.5 px-3">Servidor</th>
                      <th className="py-2.5 px-3">Fecha y Hora</th>
                      <th className="py-2.5 px-3 text-center">VMs Totales</th>
                      <th className="py-2.5 px-3">Estado</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {snapshots?.map((snap) => (
                      <tr key={snap.id} className="hover:bg-slate-800/40">
                        <td className="py-2.5 px-3 font-semibold text-slate-200">{snap.servidor_nombre || '—'}</td>
                        <td className="py-2.5 px-3 font-mono text-slate-400">{snap.timestamp}</td>
                        <td className="py-2.5 px-3 font-mono font-bold text-center text-slate-100">{snap.total_vms || 0}</td>
                        <td className="py-2.5 px-3">
                          {snap.estado === 'ok' || snap.estado === 'completado' ? (
                            <Badge variant="success">OK</Badge>
                          ) : (
                            <Badge variant="danger">{snap.estado}</Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        {/* Right Column: Generation Panel */}
        <div className="space-y-6">
          <Card title="📋 Generar Nuevo Reporte Excel" subtitle="Reporte dinámico multi-hoja">
            <form onSubmit={handleGenerarReporte} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 font-medium mb-1">Filtrar por Tipo</label>
                <select
                  value={tipo}
                  onChange={(e) => setTipo(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500"
                >
                  <option value="">Todos (VDI + VM)</option>
                  <option value="VDI">Solo VDI</option>
                  <option value="VM">Solo VM</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-400 font-medium mb-1">Filtrar por Origen</label>
                <select
                  value={origen}
                  onChange={(e) => setOrigen(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500 uppercase"
                >
                  <option value="">Todos los orígenes</option>
                  <option value="dt">DT</option>
                  <option value="su">SU</option>
                  <option value="core">CORE</option>
                  <option value="mz">MZ</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-400 font-medium mb-1">Filtrar por Servidor</label>
                <select
                  value={servidorId}
                  onChange={(e) => setServidorId(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-indigo-500"
                >
                  <option value="">Todos los servidores</option>
                  {servidores?.map(s => (
                    <option key={s.id} value={s.id}>{s.nombre}</option>
                  ))}
                </select>
              </div>

              {genStatus && (
                <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-indigo-300 text-xs font-medium flex items-center">
                  {isGenerating && <div className="w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mr-2 shrink-0"></div>}
                  <span>{genStatus}</span>
                </div>
              )}

              <Button type="submit" variant="primary" size="md" icon={BarChart2} disabled={isGenerating} className="w-full justify-center">
                {isGenerating ? 'Generando Excel...' : '📊 Generar y Descargar'}
              </Button>
            </form>

            <div className="mt-4 pt-4 border-t border-slate-800 text-[11px] text-slate-400 space-y-1">
              <strong className="text-slate-300 block mb-1">El archivo Excel incluye:</strong>
              <ul className="list-disc pl-4 space-y-0.5 text-slate-400">
                <li>Resumen Ejecutivo (KPIs)</li>
                <li>Hoja VDI (Solo Escritorios)</li>
                <li>Hoja VM (Solo Servidores Virtuales)</li>
                <li>Inventario Completo</li>
                <li>Hojas por Empresa, Pool y Origen</li>
                <li>Alertas (Huérfanas, Duplicadas, Deltas)</li>
              </ul>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
