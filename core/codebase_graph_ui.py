"""
core/codebase_graph_ui.py
Servidor HTTP independiente que renderiza la interfaz visual interactiva Web UI del Grafo de Codebase (codebase-memory-mcp) en el puerto 9749 (http://localhost:9749).
"""
import http.server
import json
import os
import socketserver
import subprocess
import threading

PORT = 9749
PROJECT_NAME = os.environ.get("PROJECT_NAME", "InventarioVDI")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Codebase Knowledge Graph — Visualizer</title>
  <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      background: #0b0f1a;
      color: #f1f5f9;
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    header {
      background: #111827;
      border-bottom: 1px solid rgba(255,255,255,0.1);
      padding: 12px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      z-index: 10;
    }
    .brand { display: flex; align-items: center; gap: 10px; }
    .brand-icon {
      width: 32px; height: 32px; border-radius: 8px;
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      display: flex; align-items: center; justify-content: center;
      font-weight: bold; font-size: 1.1rem; box-shadow: 0 0 14px rgba(59,130,246,0.3);
    }
    h1 { font-size: 1.1rem; font-weight: 700; color: #f1f5f9; }
    .subtitle { font-size: 0.72rem; color: #94a3b8; }
    .controls { display: flex; align-items: center; gap: 12px; }
    input[type="text"] {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.15);
      color: #fff; padding: 6px 12px; border-radius: 6px;
      font-size: 0.85rem; outline: none; width: 240px;
    }
    select {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.15);
      color: #fff; padding: 6px 10px; border-radius: 6px;
      font-size: 0.85rem; outline: none;
    }
    .badge {
      background: rgba(59,130,246,0.15); border: 1px solid #3b82f6;
      color: #60a5fa; padding: 4px 10px; border-radius: 20px;
      font-size: 0.75rem; font-weight: 600;
    }
    #main-container { flex: 1; display: flex; position: relative; }
    #mynetwork { flex: 1; height: 100%; background: #0b0f1a; }
    #info-panel {
      width: 340px; background: #111827; border-left: 1px solid rgba(255,255,255,0.1);
      padding: 16px; overflow-y: auto; display: none;
    }
    #info-panel h3 { font-size: 1rem; margin-bottom: 8px; color: #60a5fa; word-break: break-all; }
    .prop-row { margin-bottom: 8px; font-size: 0.82rem; }
    .prop-label { color: #94a3b8; font-weight: 600; }
    .prop-val { color: #f1f5f9; word-break: break-all; font-family: monospace; }
  </style>
</head>
<body>

<header>
  <div class="brand">
    <div class="brand-icon">🕸️</div>
    <div>
      <h1>Codebase Knowledge Graph</h1>
      <div class="subtitle">codebase-memory-mcp · inventario-vdi</div>
    </div>
  </div>
  <div class="controls">
    <input type="text" id="search-input" placeholder="Buscar nodo (ej. Directorio, Maquina)..." oninput="filterGraph()">
    <select id="type-filter" onchange="filterGraph()">
      <option value="">Todos los tipos</option>
      <option value="Class">Clases</option>
      <option value="Function">Funciones</option>
      <option value="File">Archivos</option>
      <option value="Module">Módulos</option>
      <option value="Route">Rutas API/URL</option>
    </select>
    <span class="badge" id="stats-badge">Cargando Grafo...</span>
  </div>
</header>

<div id="main-container">
  <div id="mynetwork"></div>
  <div id="info-panel">
    <h3 id="node-title">Selecciona un nodo</h3>
    <div class="prop-row"><span class="prop-label">Tipo:</span> <span class="prop-val" id="node-label">-</span></div>
    <div class="prop-row"><span class="prop-label">Archivo:</span> <span class="prop-val" id="node-file">-</span></div>
    <div class="prop-row"><span class="prop-label">Qualified Name:</span> <span class="prop-val" id="node-qname">-</span></div>
    <div class="prop-row"><span class="prop-label">Conexiones Salientes:</span> <span class="prop-val" id="node-out">-</span></div>
    <div class="prop-row"><span class="prop-label">Conexiones Entrantes:</span> <span class="prop-val" id="node-in">-</span></div>
  </div>
</div>

<script>
let network = null;
let allNodes = [];
let allEdges = [];

async function loadGraph() {
  try {
    const res = await fetch('/api/graph');
    const data = await res.json();
    
    document.getElementById('stats-badge').textContent = `${data.nodes.length} Nodos · ${data.edges.length} Relaciones`;
    
    allNodes = data.nodes.map(n => {
      let color = '#3b82f6';
      let shape = 'dot';
      if (n.type === 'Class') { color = '#8b5cf6'; shape = 'diamond'; }
      else if (n.type === 'Function') { color = '#10b981'; shape = 'dot'; }
      else if (n.type === 'File') { color = '#f59e0b'; shape = 'square'; }
      else if (n.type === 'Module') { color = '#06b6d4'; shape = 'triangle'; }
      else if (n.type === 'Route') { color = '#ec4899'; shape = 'star'; }
      
      return {
        id: n.id,
        label: n.name,
        title: `${n.type}: ${n.name}\\nPath: ${n.file || ''}`,
        color: { background: color, border: '#fff' },
        shape: shape,
        size: Math.max(12, Math.min(32, 10 + (n.in_degree || 0) * 1.5)),
        rawData: n
      };
    });

    allEdges = data.edges.map(e => ({
      from: e.from,
      to: e.to,
      arrows: 'to',
      color: { color: 'rgba(255,255,255,0.18)', highlight: '#60a5fa' }
    }));

    const container = document.getElementById('mynetwork');
    const graphData = {
      nodes: new vis.DataSet(allNodes),
      edges: new vis.DataSet(allEdges)
    };

    const options = {
      nodes: { font: { color: '#f1f5f9', size: 12 } },
      edges: { smooth: { type: 'continuous' } },
      physics: {
        stabilization: { iterations: 150 },
        barnesHut: { gravitationalConstant: -4000, springLength: 90 }
      },
      interaction: { hover: true, tooltipDelay: 100 }
    };

    network = new vis.Network(container, graphData, options);

    network.on("click", function (params) {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        const n = allNodes.find(item => item.id === nodeId);
        if (n && n.rawData) {
          showNodeDetails(n.rawData);
        }
      }
    });

  } catch(e) {
    document.getElementById('stats-badge').textContent = 'Error al cargar grafo.';
  }
}

function showNodeDetails(d) {
  document.getElementById('info-panel').style.display = 'block';
  document.getElementById('node-title').textContent = d.name;
  document.getElementById('node-label').textContent = d.type || 'N/A';
  document.getElementById('node-file').textContent = d.file || 'N/A';
  document.getElementById('node-qname').textContent = d.qname || d.id;
  document.getElementById('node-out').textContent = d.out_degree || 0;
  document.getElementById('node-in').textContent = d.in_degree || 0;
}

function filterGraph() {
  const q = document.getElementById('search-input').value.toLowerCase();
  const t = document.getElementById('type-filter').value;

  const filteredNodes = allNodes.filter(n => {
    const matchQ = !q || n.label.toLowerCase().includes(q) || (n.rawData.file && n.rawData.file.toLowerCase().includes(q));
    const matchT = !t || n.rawData.type === t;
    return matchQ && matchT;
  });

  const nodeIds = new Set(filteredNodes.map(n => n.id));
  const filteredEdges = allEdges.filter(e => nodeIds.has(e.from) && nodeIds.has(e.to));

  network.setData({
    nodes: new vis.DataSet(filteredNodes),
    edges: new vis.DataSet(filteredEdges)
  });
}

loadGraph();
</script>
</body>
</html>
"""


def fetch_graph_data():
    """Retorna los 601 nodos y 2014 relaciones de data/codebase_graph.json."""
    json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "codebase_graph.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Graph UI Error] Error al leer codebase_graph.json: {e}")

    return {"nodes": [], "edges": []}


class GraphUIHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/graph":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = fetch_graph_data()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))


def start_server_in_background(port=PORT):
    """Inicia el servidor Web UI independiente en segundo plano."""
    try:
        handler = GraphUIHandler
        httpd = socketserver.TCPServer(("0.0.0.0", port), handler)
        httpd.allow_reuse_address = True
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        print(f"[Graph UI] Servidor Web UI visual corriendo en http://localhost:{port}")
        return httpd
    except Exception as e:
        print(f"[Graph UI] No se pudo iniciar servidor en puerto {port}: {e}")
        return None


if __name__ == "__main__":
    start_server_in_background(PORT)
    import time
    while True:
        time.sleep(1)
