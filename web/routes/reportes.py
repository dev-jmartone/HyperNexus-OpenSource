"""
web/routes/reportes.py
Generación y descarga de reportes Excel.
Extiende ReportGenerator con hojas: Delta, por Servidor, por Origen, VDI vs VM.
"""
import os
from datetime import datetime
from flask import Blueprint, render_template, send_from_directory, redirect, url_for, flash, request

from web.db import db, Servidor, InventarioSnapshot, Maquina
from sqlalchemy import func

bp_reportes = Blueprint("reportes", __name__, url_prefix="/reportes")

# Estados válidos de snapshot completado
_ESTADOS_OK = ("ok", "completado")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORTES_DIR = os.path.join(BASE_DIR, "reportes")


@bp_reportes.route("/")
def index():
    archivos = []
    if os.path.exists(REPORTES_DIR):
        for f in sorted(os.listdir(REPORTES_DIR), reverse=True):
            if f.endswith(".xlsx"):
                ruta = os.path.join(REPORTES_DIR, f)
                archivos.append({
                    "nombre": f,
                    "size_kb": round(os.path.getsize(ruta) / 1024, 1),
                    "fecha": datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%d/%m/%Y %H:%M"),
                })

    # Snapshots para historial
    snapshots = (
        InventarioSnapshot.query
        .order_by(InventarioSnapshot.timestamp.desc())
        .limit(20)
        .all()
    )

    servidores = Servidor.query.filter_by(activo=True).all()

    return render_template(
        "reportes.html",
        archivos=archivos,
        snapshots=snapshots,
        servidores=servidores,
    )


@bp_reportes.route("/generar", methods=["POST"])
def generar():
    """Genera reporte Excel con hojas extendidas y lo descarga."""
    tipo_filter   = request.form.get("tipo", "")
    origen_filter = request.form.get("origen", "")
    servidor_id   = request.form.get("servidor_id", "")

    try:
        ruta = _generar_excel(tipo_filter, origen_filter, servidor_id)
        flash(f"Reporte generado: {os.path.basename(ruta)}", "success")
        return redirect(url_for("reportes.descargar", nombre=os.path.basename(ruta)))
    except Exception as e:
        flash(f"Error al generar reporte: {e}", "error")
        return redirect(url_for("reportes.index"))


@bp_reportes.route("/descargar/<nombre>")
def descargar(nombre: str):
    # send_from_directory (no send_file + os.path.join a mano) valida vía safe_join que
    # el path resuelto siga DENTRO de REPORTES_DIR — antes un nombre con backslashes
    # ("..\\.env") escapaba el directorio en Windows y servía cualquier archivo legible
    # por el proceso (confirmado con PoC: filtraba SECRET_KEY/FERNET_KEY del .env real).
    # No se hace un os.path.exists() manual antes: ese chequeo usaba el mismo join sin
    # sanitizar y reintroduciría la fuga; send_from_directory ya devuelve 404 solo si
    # el archivo no existe DENTRO del directorio permitido.
    from werkzeug.exceptions import NotFound
    try:
        return send_from_directory(REPORTES_DIR, nombre, as_attachment=True, download_name=nombre)
    except NotFound:
        flash("Archivo no encontrado.", "error")
        return redirect(url_for("reportes.index"))


def _get_maquinas(tipo=None, origen=None, servidor_id=None):
    """Obtiene máquinas del último snapshot por servidor."""
    subq = (
        db.session.query(
            InventarioSnapshot.servidor_id,
            func.max(InventarioSnapshot.id).label("max_id")
        )
        .filter(InventarioSnapshot.estado.in_(_ESTADOS_OK))
        .group_by(InventarioSnapshot.servidor_id)
        .subquery()
    )
    q = (
        Maquina.query
        .filter(
            Maquina.ultimo_snapshot_id.in_(
                db.session.query(subq.c.max_id)
            )
        )
    )
    if tipo:
        q = q.filter(Maquina.tipo == tipo)
    if origen:
        q = q.filter(Maquina._origen_str.ilike(f"%{origen}%"))
    if servidor_id:
        q = q.filter(Maquina.servidor_id == int(servidor_id))
    return q.all()


def _clean_sheet_title(name: str, wb=None) -> str:
    """Sanitiza, trunca a 25 caracteres y evita títulos duplicados en el Workbook de openpyxl."""
    if not name:
        name = "Hoja"
    for ch in [":", "\\", "/", "?", "*", "[", "]"]:
        name = name.replace(ch, "-")
    name = name.strip()
    
    base_title = name[:25] if len(name) > 25 else name
    final_title = base_title
    
    if wb is not None:
        existing = set(wb.sheetnames)
        c = 1
        while final_title in existing:
            suffix = f"_{c}"
            final_title = f"{base_title[:25-len(suffix)]}{suffix}"
            c += 1
            
    return final_title


def _generar_excel(tipo_filter="", origen_filter="", servidor_id="") -> str:
    """Genera el Excel extendido y retorna la ruta."""
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
    warnings.filterwarnings("ignore", message=".*Title is more than 31 characters.*")

    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.dataframe import dataframe_to_rows
    from openpyxl.chart import BarChart, PieChart, Reference

    os.makedirs(REPORTES_DIR, exist_ok=True)
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"Inventario_VDI_{fecha}.xlsx"
    ruta   = os.path.join(REPORTES_DIR, nombre)

    maquinas = _get_maquinas(tipo_filter, origen_filter, servidor_id)
    servidores = {s.id: s for s in Servidor.query.all()}

    # Estilos
    HEADER_FONT  = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    HEADER_FILL  = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    THIN         = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    def apply_header(ws, row=1):
        for cell in ws[row]:
            cell.font  = HEADER_FONT
            cell.fill  = HEADER_FILL
            cell.alignment = HEADER_ALIGN
            cell.border = THIN

    def autofit(ws):
        for col_cells in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                try:
                    if cell.value:
                        max_len = max(max_len, len(str(cell.value)))
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = min(max_len + 4, 50)

    def df_to_sheet(wb, df, title):
        clean_title = _clean_sheet_title(title, wb=wb)
        ws = wb.create_sheet(title=clean_title)
        for row in dataframe_to_rows(df, index=False, header=True):
            ws.append(row)
        apply_header(ws)
        autofit(ws)
        if ws.max_row > 1 and ws.max_column > 0:
            ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
        return ws

    wb = Workbook()
    wb.remove(wb.active)

    # ── 1. Informe (Resumen Ejecutivo) ────────────────────────────────
    informe_title = f"Informe - {datetime.now().strftime('%d-%m-%Y')}"
    ws_res = wb.create_sheet(_clean_sheet_title(informe_title, wb=wb))

    ws_res.append(["INVENTARIO VDI — RESUMEN EJECUTIVO"])
    ws_res.merge_cells("A1:G1")
    ws_res["A1"].font = Font(name="Calibri", bold=True, size=16, color="2F5496")
    ws_res["A1"].alignment = Alignment(horizontal="center")
    ws_res.append([])
    ws_res.append(["Fecha del reporte:", datetime.now().strftime("%d/%m/%Y %H:%M")])
    srv_str = "--"
    if servidor_id and servidor_id.isdigit():
        srv_obj = servidores.get(int(servidor_id))
        if srv_obj:
            srv_str = srv_obj.nombre
    ws_res.append(["Servidor:", srv_str])
    if tipo_filter:
        ws_res.append(["Filtro Tipo:", tipo_filter])
    if origen_filter:
        ws_res.append(["Filtro Origen:", origen_filter])
    ws_res.append([])

    total = len(maquinas)
    vdi_c = sum(1 for m in maquinas if m.tipo == "VDI")
    vm_c  = sum(1 for m in maquinas if m.tipo == "VM")
    asig  = sum(1 for m in maquinas if m.usuario_asignado)
    conec = sum(1 for m in maquinas if (m.estado_horizon or "").upper() == "CONNECTED")
    dispc = sum(1 for m in maquinas if (m.estado_horizon or "").upper() == "AVAILABLE")
    huere = sum(1 for m in maquinas if not m.usuario_asignado and (m.estado_horizon or "").upper() == "AVAILABLE")

    # Total de pools (Catálogo o de máquinas)
    from web.db import Pool
    total_pools = Pool.query.filter_by(activo=True).count()
    if not total_pools:
        total_pools = len({m.pool for m in maquinas if m.pool})

    ws_res.append(["KPI", "Valor"])
    apply_header(ws_res, ws_res.max_row)
    for label, val in [
        ("Servidor", srv_str),
        ("Total VMs/VDIs", total), ("VDI", vdi_c), ("VM", vm_c),
        ("Asignadas", asig), ("Conectadas", conec),
        ("Disponibles (libres)", dispc), ("Huérfanas (sin usuario, Available)", huere),
        ("Total de pools", total_pools),
    ]:
        ws_res.append([label, val])

    # Distribución por empresa en Informe
    ws_res.append([])
    ws_res.append(["DISTRIBUCIÓN POR EMPRESA"])
    ws_res[ws_res.max_row][0].font = Font(name="Calibri", bold=True, size=14, color="2F5496")
    ws_res.append([])
    ws_res.append(["Empresa", "Cantidad de VMs"])
    apply_header(ws_res, ws_res.max_row)

    emp_counts = {}
    for m in maquinas:
        emp = m.empresa or "Sin asignar"
        emp_counts[emp] = emp_counts.get(emp, 0) + 1

    for emp, count in sorted(emp_counts.items(), key=lambda x: -x[1]):
        ws_res.append([emp, count])

    autofit(ws_res)

    # ── 2. Inventario ────────────────────────────────────────────────
    all_rows = [_maquina_to_row(m, servidores) for m in maquinas]
    df_all = pd.DataFrame(all_rows) if all_rows else pd.DataFrame(columns=_cols())
    df_to_sheet(wb, df_all, "Inventario")

    # ── 3. Alertas ────────────────────────────────────────────────────
    ws_alerta = wb.create_sheet(_clean_sheet_title("Alertas", wb=wb))

    ws_alerta.append(["ALERTAS E INCONSISTENCIAS"])
    ws_alerta["A1"].font = Font(name="Calibri", bold=True, size=16, color="C00000")
    ws_alerta.append([])

    # Usuarios con más de 1 VDI
    user_vms: dict[str, list] = {}
    for m in maquinas:
        if m.tipo == "VDI" and m.usuario_asignado:
            k = m.usuario_asignado.lower()
            user_vms.setdefault(k, []).append(m)
    multi = {u: vms for u, vms in user_vms.items() if len(vms) > 1}

    ws_alerta.append(["USUARIOS CON MÁS DE 1 VDI ASIGNADA"])
    ws_alerta[ws_alerta.max_row][0].font = Font(bold=True, color="2F5496")
    ws_alerta.append(["Usuario", "Nombre VM", "Pool", "Empresa", "Estado"])
    apply_header(ws_alerta, ws_alerta.max_row)
    for user, vms in sorted(multi.items()):
        for m in vms:
            ws_alerta.append([m.usuario_asignado, m.nombre, m.pool, m.empresa, m.estado_horizon])
    ws_alerta.append([f"Total: {sum(len(v) for v in multi.values())} VMs en {len(multi)} usuarios"])
    ws_alerta.append([])

    # Huérfanas
    ws_alerta.append(["VMs/VDIs HUÉRFANAS (Available sin usuario)"])
    ws_alerta[ws_alerta.max_row][0].font = Font(bold=True, color="C00000")
    ws_alerta.append(["Nombre VM", "Tipo", "Pool", "Origen", "Estado"])
    apply_header(ws_alerta, ws_alerta.max_row)
    huerfanas = [m for m in maquinas if not m.usuario_asignado and (m.estado_horizon or "").upper() == "AVAILABLE"]
    for m in huerfanas:
        ws_alerta.append([m.nombre, m.tipo, m.pool, m.origen, m.estado_horizon])
    ws_alerta.append([f"Total huérfanas: {len(huerfanas)}"])
    ws_alerta.append([])

    # Usuarios en Horizon sin VM asignada
    from web.db import DirectorioUsuario
    ws_alerta.append(["USUARIOS EN HORIZON SIN VM ASIGNADA"])
    ws_alerta[ws_alerta.max_row][0].font = Font(bold=True, color="C00000")
    ws_alerta.append(["Usuario", "Nombre Completo", "Empresa", "Departamento", "Email"])
    apply_header(ws_alerta, ws_alerta.max_row)

    assigned_users = set()
    for m in maquinas:
        if m.usuario_asignado:
            u = m.usuario_asignado.lower().strip()
            if "\\" in u:
                u = u.split("\\")[-1]
            assigned_users.add(u)

    dir_users = DirectorioUsuario.query.filter_by(activo_ad=True).all() if DirectorioUsuario else []
    sin_vm = []
    for u in dir_users:
        u_name = (u.username or "").lower().strip()
        if "\\" in u_name:
            u_name = u_name.split("\\")[-1]
        if u_name and u_name not in assigned_users:
            sin_vm.append(u)

    for u in sin_vm:
        ws_alerta.append([u.username, u.nombre_completo or "", u.empresa or "", u.departamento or "", u.email or ""])
    ws_alerta.append([f"Total usuarios sin VM asignada: {len(sin_vm)}"])

    autofit(ws_alerta)

    # ── 4. Cambios (Delta) ───────────────────────────────────────────
    _generar_hoja_delta(wb, maquinas, servidores)

    wb.save(ruta)
    return ruta


def _maquina_to_row(m: "Maquina", servidores: dict) -> dict:
    return {
        "Tipo":                     m.tipo,
        "Origen":                   m.origen or "",
        "Nombre VM":                m.nombre,
        "DNS":                      m.dns or "",
        "Pool":                     m.pool or "",
        "Empresa":                  m.empresa or "",
        "Usuario Asignado":         m.usuario_asignado or "",
        "Manager":                  m.manager or "",
        "Estado operacional":       m.estado or "",
        "Fecha de ultimo ingreso":  m.fecha_ultimo_ingreso or "",
        "SO":                       m.so or "",
        "Anotación":                getattr(m, 'annotation', '') or "",
    }


def _cols():
    return [
        "Tipo", "Origen", "Nombre VM", "DNS", "Pool",
        "Empresa", "Usuario Asignado", "Manager",
        "Estado operacional", "Fecha de ultimo ingreso", "SO", "Anotación"
    ]


def _generar_hoja_delta(wb, maquinas_actuales, servidores):
    """Compara snapshot actual vs anterior y produce hoja Cambios."""
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    # Buscar snapshot anterior (segundo más reciente por servidor)
    from web.db import InventarioSnapshot
    from sqlalchemy import func

    nombres_actuales = {m.nombre for m in maquinas_actuales}

    ws = wb.create_sheet(_clean_sheet_title("Cambios (Delta)", wb=wb))


    ws.append(["CAMBIOS DETECTADOS RESPECTO A LA EXTRACCIÓN ANTERIOR"])
    ws["A1"].font = Font(bold=True, size=14, color="2F5496")
    ws.append([])

    # Obtener máquinas del penúltimo snapshot
    subq_prev = (
        db.session.query(
            InventarioSnapshot.servidor_id,
            func.max(InventarioSnapshot.id).label("max_id")
        )
        .filter(InventarioSnapshot.estado.in_(("ok", "completado")))
        .group_by(InventarioSnapshot.servidor_id)
        .subquery()
    )
    # Penúltimo: excluir los IDs del último snapshot por servidor
    last_ids = [
        db.session.query(subq_prev.c.max_id)
        .filter(subq_prev.c.servidor_id == m.servidor_id)
        .scalar() for m in maquinas_actuales
    ]
    last_ids_unique = list(set(filter(None, last_ids)))

    maquinas_prev = []
    if last_ids_unique:
        # Buscar snapshot anterior a los actuales
        snaps_ant = (
            InventarioSnapshot.query
            .filter(
                InventarioSnapshot.estado.in_(("ok", "completado")),
                ~InventarioSnapshot.id.in_(last_ids_unique)
            )
            .order_by(InventarioSnapshot.timestamp.desc())
            .limit(len(servidores))
            .all()
        )
        if snaps_ant:
            prev_ids = [s.id for s in snaps_ant]
            maquinas_prev = Maquina.query.filter(Maquina.ultimo_snapshot_id.in_(prev_ids)).all()

    nombres_prev = {m.nombre for m in maquinas_prev}

    nuevas    = [m for m in maquinas_actuales if m.nombre not in nombres_prev]
    eliminadas= [m for m in maquinas_prev if m.nombre not in nombres_actuales]

    # Cambios de estado
    prev_map = {m.nombre: m for m in maquinas_prev}
    cambios   = []
    for m in maquinas_actuales:
        if m.nombre in prev_map:
            p = prev_map[m.nombre]
            if m.estado_horizon != p.estado_horizon or m.usuario_asignado != p.usuario_asignado:
                cambios.append({
                    "nombre": m.nombre,
                    "campo": "Estado/Usuario",
                    "anterior": f"Estado:{p.estado_horizon} | Usuario:{p.usuario_asignado}",
                    "nuevo": f"Estado:{m.estado_horizon} | Usuario:{m.usuario_asignado}",
                })

    # VMs nuevas
    ws.append(["VMs/VDIs NUEVAS (aparecieron)"])
    ws[ws.max_row][0].font = Font(bold=True, color="2E7D32")
    ws.append(["Nombre VM", "Tipo", "Pool", "Empresa", "Estado"])
    for m in nuevas:
        ws.append([m.nombre, m.tipo, m.pool, m.empresa, m.estado_horizon])
    ws.append([f"Total nuevas: {len(nuevas)}"])
    ws.append([])

    # VMs eliminadas
    ws.append(["VMs/VDIs ELIMINADAS (desaparecieron)"])
    ws[ws.max_row][0].font = Font(bold=True, color="C00000")
    ws.append(["Nombre VM", "Tipo", "Pool", "Empresa", "Estado previo"])
    for m in eliminadas:
        ws.append([m.nombre, m.tipo, m.pool, m.empresa, m.estado_horizon])
    ws.append([f"Total eliminadas: {len(eliminadas)}"])
    ws.append([])

    # Cambios de estado/usuario
    ws.append(["CAMBIOS DE ESTADO / USUARIO"])
    ws[ws.max_row][0].font = Font(bold=True, color="E65100")
    ws.append(["Nombre VM", "Campo", "Valor Anterior", "Valor Nuevo"])
    for c in cambios:
        ws.append([c["nombre"], c["campo"], c["anterior"], c["nuevo"]])
    ws.append([f"Total cambios: {len(cambios)}"])

    for col_cells in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 4, 60)
