"""
web/routes/directorio.py
CRUD del directorio de usuarios corporativos/AD y vinculación con VMs/VDIs.
"""
import json
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, Response, stream_with_context
from sqlalchemy import func

from web.db import db, DirectorioUsuario, MaquinaUsuarioDir, Maquina, registrar_auditoria
from web.security_utils import normalizar_username

bp_directorio = Blueprint("directorio", __name__, url_prefix="/directorio")


# ── Listado / búsqueda ────────────────────────────────────────────────

@bp_directorio.route("/")
def index():
    q = request.args.get("q", "").strip()
    solo_inactivos = request.args.get("inactivos", "") == "1"

    query = DirectorioUsuario.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                DirectorioUsuario.username.ilike(like),
                DirectorioUsuario.nombre_completo.ilike(like),
                DirectorioUsuario.email.ilike(like),
                DirectorioUsuario.departamento.ilike(like),
                DirectorioUsuario.empresa.ilike(like),
            )
        )
    if solo_inactivos:
        query = query.filter(DirectorioUsuario.activo_ad == False)

    usuarios = query.order_by(DirectorioUsuario.nombre_completo).all()

    # Pre-cargar vinculaciones con VMs/VDIs y Pools para visualización en tabla
    usuarios_vms_map = {}
    vinculos = MaquinaUsuarioDir.query.all()
    maquinas_map = {m.id: m for m in Maquina.query.all()}
    for v in vinculos:
        m = maquinas_map.get(v.maquina_id)
        if m:
            if v.directorio_usuario_id not in usuarios_vms_map:
                usuarios_vms_map[v.directorio_usuario_id] = []
            usuarios_vms_map[v.directorio_usuario_id].append({
                "id": m.id,
                "nombre": m.nombre,
                "tipo": m.tipo,
                "pool": m.pool or "Estática",
                "empresa": m.empresa or "—",
            })

    return render_template(
        "directorio.html",
        usuarios=usuarios,
        usuarios_vms_map=usuarios_vms_map,
        filtros={"q": q, "inactivos": solo_inactivos},
    )


# ── Ficha de usuario ──────────────────────────────────────────────────

@bp_directorio.route("/<int:uid>")
def ficha(uid: int):
    u = DirectorioUsuario.query.get_or_404(uid)
    # VMs vinculadas
    asignaciones = (
        MaquinaUsuarioDir.query
        .filter_by(directorio_usuario_id=uid)
        .all()
    )
    maquinas_ids = [a.maquina_id for a in asignaciones]
    maquinas = Maquina.query.filter(Maquina.id.in_(maquinas_ids)).all()
    maquinas_map = {m.id: m for m in maquinas}
    return render_template(
        "directorio_ficha.html",
        usuario=u,
        asignaciones=asignaciones,
        maquinas_map=maquinas_map,
    )


# ── Crear usuario ─────────────────────────────────────────────────────

@bp_directorio.route("/crear", methods=["POST"])
def crear():
    username = request.form.get("username", "").strip()
    if not username:
        flash("Username requerido.", "error")
        return redirect(url_for("directorio.index"))

    if DirectorioUsuario.query.filter(func.lower(DirectorioUsuario.username) == username.lower()).first():
        flash(f"Usuario '{username}' ya existe en el directorio.", "error")
        return redirect(url_for("directorio.index"))

    u = DirectorioUsuario(
        username=username,
        nombre_completo=request.form.get("nombre_completo", "").strip() or None,
        email=request.form.get("email", "").strip() or None,
        departamento=request.form.get("departamento", "").strip() or None,
        empresa=request.form.get("empresa", "").strip() or None,
        telefono=request.form.get("telefono", "").strip() or None,
        activo_ad=request.form.get("activo_ad") == "1",
        notas=request.form.get("notas", "").strip() or None,
    )
    db.session.add(u)
    registrar_auditoria(
        accion="crear_directorio_usuario",
        recurso=username,
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    flash(f"Usuario '{username}' creado en el directorio.", "success")
    return redirect(url_for("directorio.index"))


# ── Editar usuario ────────────────────────────────────────────────────

@bp_directorio.route("/<int:uid>/editar", methods=["POST"])
def editar(uid: int):
    u = DirectorioUsuario.query.get_or_404(uid)
    u.username        = request.form.get("username", u.username).strip()
    u.nombre_completo = request.form.get("nombre_completo", "").strip() or None
    u.email           = request.form.get("email", "").strip() or None
    u.departamento    = request.form.get("departamento", "").strip() or None
    u.empresa         = request.form.get("empresa", "").strip() or None
    u.telefono        = request.form.get("telefono", "").strip() or None
    u.activo_ad       = request.form.get("activo_ad") == "1"
    u.notas           = request.form.get("notas", "").strip() or None

    registrar_auditoria(
        accion="editar_directorio_usuario",
        recurso=u.username,
        recurso_id=u.id,
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({"ok": True})


# ── Eliminar usuario ──────────────────────────────────────────────────

@bp_directorio.route("/<int:uid>/eliminar", methods=["POST"])
def eliminar(uid: int):
    u = DirectorioUsuario.query.get_or_404(uid)
    username = u.username
    db.session.delete(u)
    registrar_auditoria(
        accion="eliminar_directorio_usuario",
        recurso=username,
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    flash(f"Usuario '{username}' eliminado del directorio.", "success")
    return redirect(url_for("directorio.index"))


# ── Vincular usuario a VM ─────────────────────────────────────────────

@bp_directorio.route("/api/vincular", methods=["POST"])
def api_vincular():
    """Vincula un DirectorioUsuario a una Maquina."""
    data = request.get_json(silent=True) or {}
    maquina_id = data.get("maquina_id")
    usuario_id = data.get("directorio_usuario_id")
    tipo = data.get("tipo", "principal")
    notas = data.get("notas", "") or None

    if not maquina_id or not usuario_id:
        return jsonify({"ok": False, "error": "maquina_id y directorio_usuario_id requeridos"}), 400

    # Verificar existencia
    if not Maquina.query.get(maquina_id):
        return jsonify({"ok": False, "error": "Máquina no encontrada"}), 404
    if not DirectorioUsuario.query.get(usuario_id):
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404

    # Verificar que no exista ya
    existente = MaquinaUsuarioDir.query.filter_by(
        maquina_id=maquina_id,
        directorio_usuario_id=usuario_id
    ).first()
    if existente:
        return jsonify({"ok": False, "error": "Vínculo ya existe"}), 409

    vinculo = MaquinaUsuarioDir(
        maquina_id=maquina_id,
        directorio_usuario_id=usuario_id,
        tipo=tipo,
        notas=notas,
        activo=True,
    )
    db.session.add(vinculo)
    registrar_auditoria(
        accion="vincular_vm_usuario",
        recurso=f"maquina:{maquina_id}",
        recurso_id=maquina_id,
        detalle=f"usuario_dir_id={usuario_id}, tipo={tipo}",
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({"ok": True, "vinculo_id": vinculo.id})


# ── Desvincular usuario de VM ─────────────────────────────────────────

@bp_directorio.route("/api/desvincular/<int:vid>", methods=["DELETE"])
def api_desvincular(vid: int):
    """Elimina un vínculo Maquina↔DirectorioUsuario."""
    v = MaquinaUsuarioDir.query.get_or_404(vid)
    db.session.delete(v)
    registrar_auditoria(
        accion="desvincular_vm_usuario",
        recurso=f"maquina:{v.maquina_id}",
        recurso_id=v.maquina_id,
        detalle=f"vinculo_id={vid}",
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({"ok": True})


# ── API: usuarios del directorio (para selector en modales) ──────────

@bp_directorio.route("/api/buscar")
def api_buscar():
    q = request.args.get("q", "").strip()
    query = DirectorioUsuario.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                DirectorioUsuario.username.ilike(like),
                DirectorioUsuario.nombre_completo.ilike(like),
                DirectorioUsuario.email.ilike(like),
            )
        )
    usuarios = query.order_by(DirectorioUsuario.nombre_completo).limit(20).all()
    return jsonify([u.to_dict() for u in usuarios])


# ── API: VMs vinculadas a una VM ──────────────────────────────────────

@bp_directorio.route("/api/maquina/<int:mid>/usuarios")
def api_usuarios_de_maquina(mid: int):
    """Retorna los usuarios del directorio vinculados a una máquina."""
    vinculos = MaquinaUsuarioDir.query.filter_by(maquina_id=mid).all()
    resultado = []
    for v in vinculos:
        u = DirectorioUsuario.query.get(v.directorio_usuario_id)
        if u:
            resultado.append({
                "vinculo_id": v.id,
                "tipo": v.tipo,
                "notas": v.notas or "",
                "activo": v.activo,
                **u.to_dict(),
            })
    return jsonify(resultado)


# ── API: Buscar e importar usuarios detectados en las extracciones ────

@bp_directorio.route("/api/extraidos")
def api_extraidos():
    """Retorna los usuarios detectados en las extracciones de máquinas.
    Agrupa por username y lista sus VMs/VDIs asignadas.
    """
    q = request.args.get("q", "").strip().lower()

    maquinas = (
        Maquina.query
        .filter(Maquina.usuario_asignado != None, Maquina.usuario_asignado != "")
        .filter(Maquina.activo == True)
        .all()
    )

    directorio_map = {
        u.username.lower(): u for u in DirectorioUsuario.query.all()
    }

    usuarios_dict = {}
    for m in maquinas:
        raw_user = (m.usuario_asignado or "").strip()
        if not raw_user:
            continue

        username_clean = normalizar_username(raw_user)
        if not username_clean:
            continue

        key = username_clean.lower()

        if key not in usuarios_dict:
            dir_u = directorio_map.get(key)
            usuarios_dict[key] = {
                "username": username_clean,
                "nombre_completo": dir_u.nombre_completo if dir_u and dir_u.nombre_completo else "",
                "empresa": (m.empresa or (dir_u.empresa if dir_u else "") or "").strip(),
                "registrado": dir_u is not None,
                "directorio_usuario_id": dir_u.id if dir_u else None,
                "vms": []
            }

        usuarios_dict[key]["vms"].append({
            "id": m.id,
            "nombre": m.nombre,
            "tipo": m.tipo,
            "pool": m.pool or "Estática",
            "empresa": m.empresa or "—",
            "estado": m.estado_horizon or m.estado_vcenter or "—"
        })
        if m.empresa and not usuarios_dict[key]["empresa"]:
            usuarios_dict[key]["empresa"] = m.empresa

    resultado = list(usuarios_dict.values())

    if q:
        resultado = [
            u for u in resultado
            if q in u["username"].lower()
            or q in (u["nombre_completo"] or "").lower()
            or q in (u["empresa"] or "").lower()
            or any(q in vm["nombre"].lower() for vm in u["vms"])
        ]

    resultado.sort(key=lambda u: (u["registrado"], u["username"].lower()))
    return jsonify(resultado)


@bp_directorio.route("/api/importar_extraidos", methods=["POST"])
def api_importar_extraidos():
    """Registra usuarios detectados en las extracciones y los vincula a sus VMs."""
    data = request.get_json(silent=True) or {}
    items = data.get("usuarios", [])
    if not items:
        return jsonify({"ok": False, "error": "No se enviaron usuarios para registrar"}), 400

    importados_count = 0
    vinculos_count = 0

    for item in items:
        username = (item.get("username") or "").strip()
        if not username:
            continue

        nombre_completo = (item.get("nombre_completo") or "").strip() or None
        empresa = (item.get("empresa") or "").strip() or None
        maquina_ids = item.get("maquina_ids", [])

        from web.db import get_or_create_directorio_usuario
        habia = DirectorioUsuario.query.filter(func.lower(DirectorioUsuario.username) == username.lower()).first()
        u = get_or_create_directorio_usuario(username, empresa=empresa, nombre_completo=nombre_completo)
        if not u:
            continue
        if not habia:
            importados_count += 1

        for mid in maquina_ids:
            if not Maquina.query.get(mid):
                continue
            existente = MaquinaUsuarioDir.query.filter_by(
                maquina_id=mid,
                directorio_usuario_id=u.id
            ).first()
            if not existente:
                vinculo = MaquinaUsuarioDir(
                    maquina_id=mid,
                    directorio_usuario_id=u.id,
                    tipo="principal",
                    activo=True,
                )
                db.session.add(vinculo)
                vinculos_count += 1

    registrar_auditoria(
        accion="importar_usuarios_extraidos",
        detalle=f"usuarios={importados_count}, vinculos={vinculos_count}",
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({"ok": True, "importados": importados_count, "vinculos": vinculos_count})


@bp_directorio.route("/api/sincronizar_todo", methods=["POST"])
def api_sincronizar_todo():
    """Sincroniza todas las máquinas extraídas en la DB con DirectorioUsuario y MaquinaUsuarioDir."""
    maquinas = Maquina.query.filter(Maquina.usuario_asignado != None, Maquina.usuario_asignado != '').all()
    created_u = 0
    created_v = 0

    from web.db import get_or_create_directorio_usuario
    for m in maquinas:
        user_raw = (m.usuario_asignado or "").strip()
        if not user_raw:
            continue

        clean_u = normalizar_username(user_raw)
        habia = DirectorioUsuario.query.filter(func.lower(DirectorioUsuario.username) == clean_u.lower()).first() if clean_u else None
        dir_u = get_or_create_directorio_usuario(user_raw, empresa=m.empresa)
        if not dir_u:
            continue
        if not habia:
            created_u += 1

        vinc = MaquinaUsuarioDir.query.filter_by(maquina_id=m.id, directorio_usuario_id=dir_u.id).first()
        if not vinc:
            vinc = MaquinaUsuarioDir(
                maquina_id=m.id,
                directorio_usuario_id=dir_u.id,
                tipo="principal",
                activo=True
            )
            db.session.add(vinc)
            created_v += 1

    registrar_auditoria(
        accion="sincronizar_todo_directorio",
        detalle=f"usuarios_creados={created_u}, vinculos_creados={created_v}",
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({"ok": True, "usuarios_creados": created_u, "vinculos_creados": created_v})


def _enriquecer_usuario_gal(u: DirectorioUsuario, outlook_client=None) -> bool:
    """Enriquece un DirectorioUsuario consultando la caché o MAPI/ADSI del GAL en OutlookClient."""
    if not u or not u.username:
        return False
    if outlook_client is None:
        from core.outlook_client import OutlookClient
        outlook_client = OutlookClient()
        outlook_client.cargar_cache()

    contacto = outlook_client.obtener_contacto_gal(u.username)
    if not contacto:
        clas = outlook_client.clasificar_usuario(u.username)
        if clas and clas.get("encontrado"):
            contacto = {
                "name": clas.get("usuario"),
                "email": clas.get("email"),
                "company": clas.get("empresa"),
                "department": clas.get("department") or clas.get("title"),
            }

    if contacto:
        changed = False
        name = (contacto.get("name") or "").strip()
        email = (contacto.get("email") or "").strip()
        company = (contacto.get("company") or "").strip()
        dept = (contacto.get("department") or contacto.get("title") or "").strip()

        if name and not u.nombre_completo:
            u.nombre_completo = name
            changed = True
        if email and not u.email:
            u.email = email
            changed = True
        if company and (not u.empresa or u.empresa == "—"):
            u.empresa = company
            changed = True
        if dept and not u.departamento:
            u.departamento = dept
            changed = True
        return changed
    return False


@bp_directorio.route("/api/enriquecer_gal", methods=["POST"])
def api_enriquecer_gal():
    """Ejecuta el enriquecimiento de nombre, email, empresa y departamento para todos los usuarios desde Outlook GAL."""
    from core.outlook_client import OutlookClient
    out = OutlookClient()
    out.cargar_cache()

    usuarios = DirectorioUsuario.query.all()
    count_enriquecidos = 0

    for u in usuarios:
        if _enriquecer_usuario_gal(u, out):
            count_enriquecidos += 1

    registrar_auditoria(
        accion="enriquecer_directorio_gal",
        detalle=f"usuarios_enriquecidos={count_enriquecidos}",
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({"ok": True, "enriquecidos": count_enriquecidos})


@bp_directorio.route("/api/verificar_ad", methods=["POST"])
def api_verificar_ad():
    """Consulta Active Directory para todos los usuarios del Directorio.
    Verifica si existen en AD, si están activos o inactivos, e importa Nombre, Email, Empresa, Departamento y Teléfono.
    """
    ad_domain = os.environ.get("AD_DOMAIN", "corp.local")
    ad = ADClient(domain=ad_domain)
    usuarios = DirectorioUsuario.query.all()
    usernames = [u.username for u in usuarios]

    res_ad = ad.verificar_usuarios(usernames)

    actualizados = 0
    encontrados = 0
    inactivos_o_no_ad = 0

    for u in usuarios:
        info = res_ad.get(u.username.lower())
        if not info:
            info = res_ad.get(normalizar_username(u.username).lower())

        if info and info.get("encontrado_ad"):
            encontrados += 1
            changed = False

            ad_activo = info.get("activo_ad", True)
            if u.activo_ad != ad_activo:
                u.activo_ad = ad_activo
                changed = True

            if not ad_activo:
                inactivos_o_no_ad += 1

            if info.get("nombre_completo") and not u.nombre_completo:
                u.nombre_completo = info["nombre_completo"]
                changed = True
            if info.get("email") and not u.email:
                u.email = info["email"]
                changed = True
            if info.get("empresa") and (not u.empresa or u.empresa == "—"):
                u.empresa = info["empresa"]
                changed = True
            if info.get("departamento") and not u.departamento:
                u.departamento = info["departamento"]
                changed = True
            if info.get("telefono") and not u.telefono:
                u.telefono = info["telefono"]
                changed = True
            # AD real puede tener el logon name (username acá) y el sAMAccountName
            # (pre-Windows 2000) como strings distintos -- guardar el sam aparte para
            # poder matchear contra App Volumes sea cual sea la forma que use cada lado.
            if info.get("sam_account_name") and u.sam_account_name != info["sam_account_name"]:
                u.sam_account_name = info["sam_account_name"]
                changed = True

            if changed:
                actualizados += 1
        else:
            inactivos_o_no_ad += 1
            if u.activo_ad:
                u.activo_ad = False
                actualizados += 1

    registrar_auditoria(
        accion="verificar_directorio_ad",
        detalle=f"total={len(usuarios)}, encontrados={encontrados}, inactivos_o_no_ad={inactivos_o_no_ad}, actualizados={actualizados}",
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({
        "ok": True,
        "total": len(usuarios),
        "encontrados": encontrados,
        "inactivos_o_no_ad": inactivos_o_no_ad,
        "actualizados": actualizados,
    })


@bp_directorio.route("/stream_verificar_ad")
def stream_verificar_ad():
    """SSE Stream que emite progreso en tiempo real de la verificación con Active Directory."""
    def generate():
        def send(tipo, msg):
            payload = json.dumps({"tipo": tipo, "msg": str(msg)}, ensure_ascii=False)
            return f"data: {payload}\n\n"

        ad_domain = os.environ.get("AD_DOMAIN", "corp.local")
        yield send("log", f"Iniciando verificación masiva con Active Directory ({ad_domain})...")
        yield send("pct", "5")

        from core.ad_client import ADClient
        ad = ADClient(domain=ad_domain)

        usuarios = DirectorioUsuario.query.all()
        total = len(usuarios)
        if not total:
            yield send("pct", "100")
            yield send("done", "No hay usuarios en el directorio para verificar.")
            return

        usernames = [u.username for u in usuarios]
        yield send("log", f"Cargados {total} usuarios del directorio. Ejecutando consultas masivas Get-ADUser...")
        yield send("pct", "15")

        res_ad = ad.verificar_usuarios(usernames)

        encontrados = 0
        inactivos_o_no_ad = 0
        actualizados = 0

        yield send("pct", "75")
        yield send("log", "Procesando resultados y actualizando base de datos...")

        for idx, u in enumerate(usuarios, 1):
            info = res_ad.get(u.username.lower())
            if not info:
                info = res_ad.get(normalizar_username(u.username).lower())

            status_str = "SIN AD"
            if info and info.get("encontrado_ad"):
                encontrados += 1
                changed = False

                ad_activo = info.get("activo_ad", True)
                status_str = "ACTIVO AD" if ad_activo else "INACTIVO AD"

                if u.activo_ad != ad_activo:
                    u.activo_ad = ad_activo
                    changed = True

                if not ad_activo:
                    inactivos_o_no_ad += 1

                if info.get("nombre_completo") and not u.nombre_completo:
                    u.nombre_completo = info["nombre_completo"]
                    changed = True
                if info.get("email") and not u.email:
                    u.email = info["email"]
                    changed = True
                if info.get("empresa") and (not u.empresa or u.empresa == "—"):
                    u.empresa = info["empresa"]
                    changed = True
                if info.get("departamento") and not u.departamento:
                    u.departamento = info["departamento"]
                    changed = True
                if info.get("telefono") and not u.telefono:
                    u.telefono = info["telefono"]
                    changed = True
                if info.get("sam_account_name") and u.sam_account_name != info["sam_account_name"]:
                    u.sam_account_name = info["sam_account_name"]
                    changed = True

                if changed:
                    actualizados += 1
            else:
                inactivos_o_no_ad += 1
                if u.activo_ad:
                    u.activo_ad = False
                    actualizados += 1

            pct = 75 + int((idx / total) * 20)
            yield send("pct", str(pct))
            yield send("progress", f"[{idx}/{total}] {u.username} ({status_str})")
            yield send("log", f"  [{status_str}] {u.username} — {u.nombre_completo or 'Sin nombre'}")

        db.session.commit()
        yield send("pct", "100")
        yield send("done", f"Verificación AD completada: {encontrados} encontrados activos en {ad_domain}, {inactivos_o_no_ad} inactivos o fuera de AD.")

    return Response(stream_with_context(generate()), mimetype="text/event-stream")
