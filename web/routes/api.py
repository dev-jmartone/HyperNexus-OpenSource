"""
web/routes/api.py
Endpoints JSON para charts y tablas en el frontend.
"""
from flask import Blueprint, jsonify, request, session, send_from_directory
from flask_wtf.csrf import generate_csrf
from sqlalchemy import func

from web.extensions import limiter

from web.db import (
    db, Servidor, InventarioSnapshot, Maquina, Usuario, AuditoriaLog,
    DirectorioUsuario, MaquinaUsuarioDir, HistorialUsuarioVDI, MaquinaHistorial,
    Datastore, HostEsxi, InfraEvento, Pool,
    registrar_auditoria
)
from web.auth import get_current_user, login_user, logout_user
from web.kpi_utils import clasificar_estado_maquina, clasificar_provisionamiento, TIPOS_EVENTO_IMPORTANTES, _POOLS_SIN_ASIGNAR, es_huerfana
from web.cache import cache_get_or_set
from web.routes.directorio import (
    api_sincronizar_todo, api_verificar_ad, api_enriquecer_gal,
    api_extraidos, api_importar_extraidos, api_vincular, api_desvincular
)

bp_api = Blueprint("api", __name__, url_prefix="/api")


@bp_api.route("/configuracion/webhook", methods=["GET", "POST"])
def configuracion_webhook_api():
    from web.db import Configuracion
    if request.method == "POST":
        # Restringido a admin -- URL de alertas systemwide, mismo criterio que
        # servidores/usuarios (hallazgo de seguridad: cualquier autenticado podía
        # apuntarla a red interna/metadata de nube -- SSRF, corregido 2026-09-07).
        user = get_current_user()
        if not user or user.rol != "admin":
            return jsonify({"error": "Solo administradores pueden configurar el webhook."}), 403

        data = request.get_json() or {}
        url = (data.get("webhook_url") or "").strip()
        if url:
            from web.security_utils import url_webhook_es_segura
            if not url_webhook_es_segura(url):
                return jsonify({
                    "status": "error",
                    "error": "URL inválida o apunta a una dirección no permitida (loopback/link-local/metadata de nube).",
                }), 400

        cfg = Configuracion.query.filter_by(clave="webhook_url").first()
        if not cfg:
            cfg = Configuracion(clave="webhook_url", valor=url, descripcion="URL Webhook para Alertas")
            db.session.add(cfg)
        else:
            cfg.valor = url
        db.session.commit()
        return jsonify({"status": "ok", "webhook_url": url})
    
    cfg = Configuracion.query.filter_by(clave="webhook_url").first()
    return jsonify({"webhook_url": cfg.valor if cfg else ""})


@bp_api.route("/directorio/usuarios/<int:uid>")
def directorio_usuario_ficha(uid: int):
    u = DirectorioUsuario.query.get_or_404(uid)
    vinculos = MaquinaUsuarioDir.query.filter_by(directorio_usuario_id=uid).all()
    v_map = {v.maquina_id: v for v in vinculos}

    # Buscar por M:M y por usuario_asignado directo
    maquinas_ids = set(v_map.keys())
    raw_vms = Maquina.query.filter(
        db.or_(
            Maquina.id.in_(maquinas_ids) if maquinas_ids else False,
            Maquina.usuario_asignado.ilike(f"%{u.username}%"),
            (Maquina.usuario_asignado.ilike(f"%{u.nombre_completo}%") if u.nombre_completo else False)
        )
    ).all()

    vms_list = []
    for m in raw_vms:
        v = v_map.get(m.id)
        vms_list.append({
            "vinculo_id": v.id if v else None,
            "tipo_vinculo": v.tipo if v else "directo",
            "maquina": m.to_dict()
        })

    from web.appvolumes_utils import apps_asignadas_para_usuario, actividad_reciente_para_usuario
    from web.granja_utils import autorizaciones_granja_para_usuario
    granja = autorizaciones_granja_para_usuario(u)

    return jsonify({
        "usuario": u.to_dict(),
        "asignaciones": vms_list,
        "appvolumes_apps": apps_asignadas_para_usuario(u),
        "appvolumes_actividad": actividad_reciente_para_usuario(u),
        "granja_aplicaciones": granja["aplicaciones"],
        "granja_vdi_vms": granja["vdi_vms"],
    })



@bp_api.route("/directorio/sincronizar_todo", methods=["POST"])
def directorio_sincronizar_todo():
    return api_sincronizar_todo()


@bp_api.route("/directorio/verificar_ad", methods=["POST"])
def directorio_verificar_ad():
    return api_verificar_ad()


@bp_api.route("/directorio/enriquecer_gal", methods=["POST"])
def directorio_enriquecer_gal():
    return api_enriquecer_gal()


@bp_api.route("/directorio/extraidos")
def directorio_extraidos():
    return api_extraidos()


@bp_api.route("/directorio/importar_extraidos", methods=["POST"])
def directorio_importar_extraidos():
    return api_importar_extraidos()


@bp_api.route("/directorio/vincular", methods=["POST"])
def directorio_vincular():
    return api_vincular()


@bp_api.route("/directorio/desvincular/<int:vid>", methods=["DELETE", "POST"])
def directorio_desvincular(vid: int):
    return api_desvincular(vid)


@bp_api.route("/directorio/duplicados", methods=["GET"])
def api_directorio_duplicados():
    """
    Retorna la lista de usuarios duplicados en DirectorioUsuario confirmados contra AD real.
    Operación no destructiva (dry-run).
    """
    from web.directorio_dedup_utils import detectar_duplicados_confirmados_ad
    try:
        duplicados = detectar_duplicados_confirmados_ad()
        return jsonify({"ok": True, "duplicados": duplicados, "total": len(duplicados)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error al detectar duplicados: {e}"}), 500


@bp_api.route("/directorio/duplicados/fusionar", methods=["POST"])
def api_directorio_duplicados_fusionar():
    """
    Ejecuta la fusión de un par específico de DirectorioUsuario (canonico_id, absorbido_id).
    Re-apunta vínculos M:M, copia campos faltantes a la fila canónica y borra la fila absorbida.
    """
    from web.directorio_dedup_utils import fusionar_directorio_usuarios
    data = request.get_json() or {}
    canonico_id = data.get("canonico_id") or data.get("id_canonico")
    absorbido_id = data.get("absorbido_id") or data.get("id_absorbido")

    if not canonico_id or not absorbido_id:
        return jsonify({"ok": False, "error": "Parámetros 'canonico_id' y 'absorbido_id' son requeridos."}), 400

    try:
        res = fusionar_directorio_usuarios(
            canonico_id=int(canonico_id),
            absorbido_id=int(absorbido_id),
            user_id=session.get("user_id"),
            username_req=session.get("username"),
            ip=request.remote_addr,
        )
        status_code = 200 if res.get("ok") else 400
        return jsonify(res), status_code
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Error al fusionar usuarios: {e}"}), 500


@bp_api.route("/config/intervalo", methods=["GET", "POST"])
def config_intervalo():
    from web.scheduler import get_scheduler_interval, set_scheduler_interval
    if request.method == "POST":
        user = get_current_user()
        if not user or user.rol != "admin":
            return jsonify({"error": "Solo administradores pueden cambiar el intervalo de extracción automática."}), 403
        data = request.get_json(silent=True) or {}
        key = data.get("intervalo") or data.get("key") or "5m"
        info = set_scheduler_interval(key)
        return jsonify(info)
    return jsonify(get_scheduler_interval())



import threading
from datetime import datetime
from web import jobs as _jobs
from web.routes.inventario import _ejecutar_extraccion

@bp_api.route("/servidores")
def servidores_api():
    servidores = Servidor.query.all()
    res = []
    for s in servidores:
        d = s.to_dict()
        d["total_vms"] = Maquina.query.filter_by(servidor_id=s.id).count()
        res.append(d)
    return jsonify(res)


@bp_api.route("/inventario/extraer_json", methods=["POST"])
def inventario_extraer_json():
    user = get_current_user()
    if not user:
        return jsonify({"error": "No autorizado"}), 401
    
    data = request.get_json(silent=True) or request.form
    servidor_ids = data.get("servidor_ids", [])
    mantener_correcciones = bool(data.get("mantener_correcciones", True))

    user_email = (user.email.strip() if user.email else user.username)

    from web.db import obtener_credencial_desencriptada
    vc_password = obtener_credencial_desencriptada(user.id)

    if not servidor_ids:
        return jsonify({"error": "Seleccioná al menos un servidor para escanear."}), 400

    if not vc_password:
        return jsonify({"error": "Falta la contraseña de sesión de vCenter/Horizon. Ingresala desde el botón de credenciales."}), 400

    job_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    started = _jobs.try_start_job(job_id, {
        "status": "running",
        "pct": 0,
        "msg": "Iniciando extracción...",
        "created_at": datetime.utcnow().isoformat(),
        "servidores_count": len(servidor_ids),
    })
    if not started:
        return jsonify({"error": "Ya hay una extracción en curso (manual o automática). "
                                  "Esperá a que termine — lanzar dos en paralelo satura vCenter/Horizon."}), 409

    t = threading.Thread(
        target=_ejecutar_extraccion,
        args=(job_id, [str(sid) for sid in servidor_ids], mantener_correcciones, user_email, vc_password),
        daemon=True
    )
    t.start()

    return jsonify({"ok": True, "job_id": job_id})


@bp_api.route("/inventario/progreso/<job_id>")
def api_inventario_progreso(job_id: str):
    job_info = _jobs.get_job(job_id)
    if not job_info:
        return jsonify({"error": "Job no encontrado"}), 404
    return jsonify(job_info)


@bp_api.route("/inventario/active_job")
def api_inventario_active_job():
    """Job corriendo ahora mismo (manual O automático) — para que el frontend se
    enganche a su stream SSE aunque no lo haya disparado esta pestaña/sesión."""
    job = _jobs.get_active_job()
    if job:
        return jsonify({"ok": True, "active": True, "job": job})
    return jsonify({"ok": True, "active": False})


@bp_api.route("/inventario/cancelar/<job_id>", methods=["POST"])
def api_inventario_cancelar(job_id: str):
    user = get_current_user()
    if not user:
        return jsonify({"error": "No autorizado"}), 401
    job = _jobs.get_job(job_id)
    if not job:
        return jsonify({"error": "Job no encontrado"}), 404
    if job.get("status") != "running":
        return jsonify({"error": "El job no está corriendo."}), 400
    _jobs.request_cancel(job_id)
    return jsonify({"ok": True})




@bp_api.route("/servidores/crear", methods=["POST"])
def servidores_crear():
    user = get_current_user()
    if not user or user.rol != "admin":
        return jsonify({"error": "Solo administradores pueden agregar servidores."}), 403
    data = request.get_json(silent=True) or request.form
    try:
        s = Servidor(
            nombre=data.get("nombre", "").strip(),
            host=data.get("host", "").strip(),
            tipo=data.get("tipo", "horizon"),
            tipo_maquina=data.get("tipo_maquina", "VDI"),
            origen=data.get("origen", "dt"),
            usuario=data.get("usuario", "").strip(),
            dominio=data.get("dominio", "").strip(),
            puerto=int(data.get("puerto", 443)),
            activo=True
        )
        pwd = data.get("password", "")
        if pwd:
            s.password = pwd
        db.session.add(s)
        registrar_auditoria("crear_servidor", recurso=s.nombre, detalle=f"host={s.host}, tipo={s.tipo}")
        db.session.commit()
        return jsonify({"success": True, "servidor": s.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@bp_api.route("/servidores/<int:sid>/editar", methods=["POST"])
def servidores_editar(sid: int):
    user = get_current_user()
    if not user or user.rol != "admin":
        return jsonify({"error": "No autorizado"}), 403
    s = Servidor.query.get_or_404(sid)
    data = request.get_json(silent=True) or request.form
    try:
        s.nombre = data.get("nombre", s.nombre).strip()
        s.host = data.get("host", s.host).strip()
        s.tipo = data.get("tipo", s.tipo)
        s.tipo_maquina = data.get("tipo_maquina", s.tipo_maquina)
        s.origen = data.get("origen", s.origen)
        s.usuario = data.get("usuario", s.usuario or "").strip()
        s.dominio = data.get("dominio", s.dominio or "").strip()
        s.puerto = int(data.get("puerto", s.puerto))
        s.activo = bool(data.get("activo", True))
        pwd = data.get("password", "")
        if pwd:
            s.password = pwd
        registrar_auditoria("editar_servidor", recurso=s.nombre, detalle=f"host={s.host}")
        db.session.commit()
        return jsonify({"success": True, "servidor": s.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@bp_api.route("/servidores/<int:sid>/probar", methods=["POST"])
def servidores_probar(sid: int):
    s = Servidor.query.get_or_404(sid)
    # Simulación o prueba de socket/HTTPS
    import socket
    try:
        sock = socket.create_connection((s.host, s.puerto or 443), timeout=3)
        sock.close()
        return jsonify({"ok": True, "msg": f"Conexión exitosa a {s.host}:{s.puerto}"})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error de puerto/red: {e}"})


@bp_api.route("/servidores/<int:sid>/eliminar", methods=["POST"])
def servidores_eliminar(sid: int):
    user = get_current_user()
    if not user or user.rol != "admin":
        return jsonify({"error": "No autorizado"}), 403
    s = Servidor.query.get_or_404(sid)
    try:
        nombre = s.nombre
        db.session.delete(s)
        registrar_auditoria("eliminar_servidor", recurso=nombre)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@bp_api.route("/maquinas/<int:mid>")
def maquinas_detalle(mid: int):
    """Ficha completa de una VM por id -- para abrir el mismo detalle (Ficha Técnica &
    Trazabilidad) desde otra vista (ej. el árbol de vCenter) sin depender de que la fila
    ya esté cargada en la tabla paginada de /api/maquinas.

    m.to_dict() solo trae columnas del modelo -- responsable/categoria_estatica son
    enriquecimiento calculado que hoy SOLO agrega maquinas_api() (el listado), no el
    modelo. Sin esto acá, este endpoint devolvía esos campos vacíos en silencio (bug
    real encontrado 2026-09-04 armando el panel del Árbol) -- se replica el mismo
    cálculo, mismas fuentes únicas (_categoria_estatica_codigo, _master_names_lower)."""
    m = Maquina.query.get_or_404(mid)
    d = m.to_dict()

    d["categoria_estatica"] = ""
    if m.tipo_provisionamiento == "VM_ESTATICA":
        codigo = _categoria_estatica_codigo(m.nombre, _master_names_lower())
        d["categoria_estatica"] = _CATEGORIA_ESTATICA_LABELS.get(codigo, "")

    fila_resp = (
        db.session.query(MaquinaUsuarioDir, DirectorioUsuario)
        .join(DirectorioUsuario, MaquinaUsuarioDir.directorio_usuario_id == DirectorioUsuario.id)
        .filter(MaquinaUsuarioDir.maquina_id == m.id, MaquinaUsuarioDir.tipo == "principal", MaquinaUsuarioDir.activo == True)
        .first()
    )
    if fila_resp:
        mud, du = fila_resp
        d["responsable"] = du.nombre_completo or du.username
        d["responsable_vinculo_id"] = mud.id
        d["responsable_username"] = du.username
        d["responsable_email"] = du.email
    else:
        d["responsable"] = ""
        d["responsable_vinculo_id"] = None
        d["responsable_username"] = ""
        d["responsable_email"] = ""

    imagen = Pool.query.filter(db.func.lower(Pool.nombre) == (m._pool_str or "").lower()).first() if m._pool_str else None
    d["master_vm_actual"] = imagen.master_vm_actual if imagen else ""
    d["snapshot_actual"] = imagen.snapshot_actual if imagen else ""

    # Cruce con Directorio/AD para el usuario dinámico de Horizon (antes solo se hacía
    # este cruce para el Responsable manual) -- mismo criterio de matching que usa
    # AppVolumesWritable.entity_name (username limpio, sin prefijo de dominio).
    d["usuario_asignado_email"] = ""
    d["usuario_asignado_departamento"] = ""
    d["usuario_asignado_activo_ad"] = None
    if m.usuario_asignado:
        # Comparación case-insensitive: Horizon y AD no siempre coinciden en mayúsculas
        # para el mismo usuario real (confirmado con datos reales, ej. "Jonieva" vs
        # "JOnieva") -- un == exacto no matcheaba, dejaba el cruce vacío en silencio.
        ua_limpio = m.usuario_asignado.split("\\")[-1].strip().lower()
        du_asignado = DirectorioUsuario.query.filter(
            db.or_(
                db.func.lower(DirectorioUsuario.username) == ua_limpio,
                db.func.lower(DirectorioUsuario.sam_account_name) == ua_limpio,
            )
        ).first()
        if du_asignado:
            d["usuario_asignado_email"] = du_asignado.email or ""
            d["usuario_asignado_departamento"] = du_asignado.departamento or ""
            d["usuario_asignado_activo_ad"] = du_asignado.activo_ad

    d["primera_deteccion"] = m.primera_deteccion.isoformat() if m.primera_deteccion else None
    d["updated_at"] = m.updated_at.isoformat() if m.updated_at else None

    return jsonify(d)


@bp_api.route("/maquinas/<int:mid>/editar", methods=["POST"])
def maquinas_editar(mid: int):
    """
    El estado operacional (`estado`) sigue siendo 100% manual, sin sincronización.
    `annotation` es la ÚNICA excepción: además de guardarse local, se intenta escribir de
    vuelta como Annotation real de la VM en vCenter (automático, en cada guardado, solo
    este campo -- vía SOAP/pyVmomi, ver core.vcenter_soap.actualizar_annotation. Notes no
    está expuesto por la REST Automation API pública, confirmado con HAR real 2026-08-12).
    Unificado con el viejo campo `notas` (2026-09-04) -- eran el mismo concepto (nota
    manual de la VM) en dos columnas separadas.

    Si cambió la anotación, hace falta sesión de vCenter activa (contraseña cacheada, ver
    /auth/vc_status) ANTES de guardar nada -- si no hay sesión, se rechaza la request
    entera (nada se comita) para no dejar una nota "guardada" localmente que en
    realidad nunca se sincronizó y el usuario cree que sí. Si la VM todavía no tiene
    external_id (sin contraparte en vCenter, ej. VDI que nunca se mergeó) no hay nada
    que sincronizar de verdad, así que ahí sí se permite el guardado local solo.
    """
    m = Maquina.query.get_or_404(mid)
    data = request.get_json(silent=True) or request.form
    try:
        annotation_nueva = data.get("annotation", m.annotation or "").strip()
        annotation_cambio = annotation_nueva != (m.annotation or "")

        if annotation_cambio and m.external_id:
            user = get_current_user()
            from web.db import obtener_credencial_desencriptada
            tiene_sesion = bool(user and obtener_credencial_desencriptada(user.id))
            if not tiene_sesion:
                return jsonify({
                    "success": False,
                    "error": "No hay sesión activa de vCenter. Iniciá sesión (contraseña de vCenter/Horizon) "
                             "antes de guardar la nota -- si no, queda guardada solo acá y nunca llega a vCenter.",
                    "requiere_sesion_vcenter": True,
                }), 409

        m.annotation = annotation_nueva
        m.estado = data.get("estado", m.estado or "").strip()
        registrar_auditoria("editar_maquina", recurso=m.nombre, detalle=f"estado={m.estado}, annotation={m.annotation[:50]}")
        db.session.commit()

        # "skipped" a secas quedaba mudo para el usuario -- no distinguía "no cambió nada"
        # de "cambió pero esta VM todavía no tiene vínculo con vCenter (sin external_id,
        # falta una extracción que la matchee)". Sin ese dato el frontend no tenía nada
        # que mostrar y el guardado parecía andar bien sin avisar que no sincronizó.
        if not annotation_cambio:
            sync_status = "skipped"
        elif not m.external_id:
            sync_status = "skipped_sin_vinculo"
        else:
            sync_status = "skipped"
        if annotation_cambio and m.external_id:
            sync_status = _sincronizar_notas_a_vcenter(m, annotation_nueva)

        resp = {"success": True, "maquina": m.to_dict(), "notas_sync_vcenter": sync_status}
        return jsonify(resp)
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


def _sincronizar_notas_a_vcenter(m: "Maquina", texto: str) -> str:
    """Intenta escribir `texto` como Annotation real en vCenter para la VM `m`.
    Devuelve "ok"/"error"/"skipped" -- nunca lanza, el guardado local ya está commiteado
    y no debe revertirse por una falla de red/API contra vCenter."""
    servidor_vc = m.servidor if (m.servidor and m.servidor.tipo == "vcenter") else None
    if not servidor_vc and m.origen:
        # Servidor.origen es una @property de Python (resuelve via origen_rel o _origen_str),
        # no una columna -- no se puede usar en filter_by(). Hay que pegarle a la columna
        # real (_origen_str) o al join contra el catálogo Origen, como hace la property.
        servidor_vc = (
            Servidor.query
            .filter(Servidor.tipo == "vcenter", Servidor.activo == True)
            .filter(db.or_(Servidor._origen_str == m.origen, Servidor.origen_rel.has(codigo=m.origen)))
            .first()
        )
    if not servidor_vc:
        return "skipped"

    user = get_current_user()
    if not user:
        return "skipped"
    from web.db import obtener_credencial_desencriptada
    password = obtener_credencial_desencriptada(user.id)
    if not password:
        return "error"

    try:
        from core.vcenter_soap import actualizar_annotation
        usuario_login = (user.email or user.username or "").strip()
        actualizar_annotation(
            servidor_vc.host, usuario_login, password, servidor_vc.dominio or "",
            m.external_id, texto,
        )
        m.annotation = texto
        db.session.commit()
        return "ok"
    except Exception as e:
        registrar_auditoria(
            "sync_notas_vcenter_error", recurso=m.nombre, resultado="error",
            detalle=f"servidor={servidor_vc.host}, external_id={m.external_id}: {e}",
        )
        db.session.commit()
        return "error"


@bp_api.route("/usuarios")
def usuarios_list():
    user = get_current_user()
    if not user or user.rol != "admin":
        return jsonify({"error": "No autorizado"}), 403
    users = Usuario.query.order_by(Usuario.username).all()
    return jsonify([u.to_dict() for u in users])


@bp_api.route("/usuarios/crear", methods=["POST"])
def usuarios_crear():
    user = get_current_user()
    if not user or user.rol != "admin":
        return jsonify({"error": "No autorizado"}), 403
    data = request.get_json(silent=True) or request.form
    username = data.get("username", "").strip()
    if Usuario.query.filter_by(username=username).first():
        return jsonify({"success": False, "error": f"El usuario '{username}' ya existe."}), 400
    try:
        pwd = data.get("password", "").strip() or "1234"
        u = Usuario(
            username=username,
            rol=data.get("rol", "usuario"),
            nombre_completo=data.get("nombre_completo", "").strip(),
            email=data.get("email", "").strip(),
            activo=True,
            must_change_password=True,
        )
        u.set_password(pwd)
        db.session.add(u)
        registrar_auditoria("crear_usuario", recurso=username, detalle=f"rol={u.rol}")
        db.session.commit()
        return jsonify({"success": True, "usuario": u.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@bp_api.route("/usuarios/<int:uid>/editar", methods=["POST"])
def usuarios_editar(uid: int):
    user = get_current_user()
    if not user or user.rol != "admin":
        return jsonify({"error": "No autorizado"}), 403
    u = Usuario.query.get_or_404(uid)
    data = request.get_json(silent=True) or request.form
    try:
        u.rol = data.get("rol", u.rol)
        u.nombre_completo = data.get("nombre_completo", u.nombre_completo or "").strip()
        u.email = data.get("email", u.email or "").strip()
        u.activo = bool(data.get("activo", u.activo))
        pwd = data.get("password", "").strip()
        if pwd:
            u.set_password(pwd)
        registrar_auditoria("editar_usuario", recurso=u.username, detalle=f"rol={u.rol}, activo={u.activo}")
        db.session.commit()
        return jsonify({"success": True, "usuario": u.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@bp_api.route("/usuarios/<int:uid>/eliminar", methods=["POST"])
def usuarios_eliminar(uid: int):
    user = get_current_user()
    if not user or user.rol != "admin":
        return jsonify({"error": "No autorizado"}), 403
    u = Usuario.query.get_or_404(uid)
    if u.rol == "admin" and Usuario.query.filter(Usuario.rol == "admin", Usuario.id != u.id, Usuario.activo == True).count() == 0:
        return jsonify({"success": False, "error": "No se puede eliminar: es el único usuario admin activo"}), 400
    try:
        username = u.username
        AuditoriaLog.query.filter_by(usuario_id=u.id).update({"usuario_id": None})
        db.session.delete(u)
        registrar_auditoria("eliminar_usuario", recurso=username)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@bp_api.route("/auth/cambiar-password", methods=["POST"])
def auth_cambiar_password():
    user = get_current_user()
    if not user:
        return jsonify({"error": "No autorizado"}), 401
    data = request.get_json(silent=True) or request.form
    actual = data.get("password_actual", "")
    nueva = data.get("password_nueva", "").strip()
    if not user.check_password(actual):
        return jsonify({"success": False, "error": "La contraseña actual es incorrecta."}), 400
    if len(nueva) < 4:
        return jsonify({"success": False, "error": "La nueva contraseña debe tener al menos 4 caracteres."}), 400
    if nueva == "1234":
        return jsonify({"success": False, "error": "Debes elegir una contraseña diferente a la predeterminada (1234)."}), 400
    
    try:
        user.set_password(nueva)
        user.must_change_password = False
        registrar_auditoria("cambiar_password", recurso=user.username, detalle="Cambio de contraseña exitoso")
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@bp_api.route("/auditoria")
def auditoria_api():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    q = AuditoriaLog.query.order_by(AuditoriaLog.timestamp.desc())
    total = q.count()
    logs = q.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [l.to_dict() for l in logs]
    })




@bp_api.route("/auth/vc_status")
def auth_vc_status():
    user = get_current_user()
    user_email = (user.email.strip() if user and user.email else user.username) if user else ""
    if not user:
        return jsonify({"has_credentials": False, "remaining_seconds": 0, "vc_usuario": ""})
        
    from web.db import obtener_credencial_desencriptada
    pwd = obtener_credencial_desencriptada(user.id)
    has_pwd = bool(pwd)
    return jsonify({
        "has_credentials": has_pwd,
        "remaining_seconds": 1800 if has_pwd else 0,
        "vc_usuario": user_email if has_pwd else ""
    })


@bp_api.route("/auth/set_vc_credentials", methods=["POST"])
def auth_set_vc_credentials():
    data = request.get_json(silent=True) or request.form
    pwd = data.get("vc_password", "").strip()
    if not pwd:
        return jsonify({"success": False, "error": "Contraseña requerida"}), 400

    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Usuario no identificado"}), 401

    user_email = (user.email.strip() if user.email else user.username)

    # Validar la clave contra un servidor real ANTES de guardarla — antes se guardaba
    # cualquier string sin probarlo, así que "has_credentials" quedaba en true aunque la
    # clave estuviera mal tipeada o vencida, y recién se descubría al fallar en medio de
    # una extracción (manual o del AutoScheduler), quedando el job sin poder autenticar.
    srv = Servidor.query.filter_by(tipo="horizon", activo=True).first() \
        or Servidor.query.filter_by(tipo="vcenter", activo=True).first()
    if srv:
        try:
            if srv.tipo == "horizon":
                from core.horizon_rest import HorizonRestClient
                HorizonRestClient().login(srv.host, user_email, pwd, srv.dominio or "")
            else:
                import ssl
                from core.vcenter_rest import vCenterRestClient
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                vCenterRestClient()._autenticar_sesion(srv.host, user_email, pwd, srv.dominio or "", ctx)
        except Exception as e:
            return jsonify({"success": False, "error": f"No se pudo autenticar contra {srv.nombre}: {e}"}), 400

    from web.db import guardar_credencial_encriptada
    guardar_credencial_encriptada(user.id, pwd, ttl_seconds=1800)
    session.pop("vc_password", None)
    session["vc_usuario"] = user_email
    return jsonify({"success": True})


# ── Dashboard preferences ──────────────────────────────────────────────

@bp_api.route("/dashboard/prefs", methods=["GET"])
def dashboard_get_prefs():
    """Devuelve las preferencias guardadas del dashboard para el usuario actual."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "No autorizado"}), 401
    if user.dashboard_prefs:
        try:
            import json as _json
            return jsonify({"prefs": _json.loads(user.dashboard_prefs)})
        except Exception:
            pass
    return jsonify({"prefs": None})


@bp_api.route("/dashboard/prefs", methods=["POST"])
def dashboard_save_prefs():
    """Guarda las preferencias del dashboard del usuario actual en la BD."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "No autorizado"}), 401
    data = request.get_json(silent=True) or {}
    prefs = data.get("prefs")
    if prefs is None:
        return jsonify({"error": "Falta el campo 'prefs'"}), 400
    if not isinstance(prefs, (dict, list)):
        return jsonify({"error": "'prefs' debe ser un objeto o lista"}), 400
    import json as _json
    serializado = _json.dumps(prefs, ensure_ascii=False)
    # Límite de tamaño -- antes se guardaba cualquier JSON del usuario sin cota, un
    # payload gigante en Usuario.dashboard_prefs es un self-DoS barato (hallazgo de
    # seguridad, corregido 2026-09-07). 64KB es generoso para un layout de dashboard real.
    LIMITE_BYTES = 64 * 1024
    if len(serializado.encode("utf-8")) > LIMITE_BYTES:
        return jsonify({"error": f"'prefs' excede el tamaño máximo permitido ({LIMITE_BYTES // 1024} KB)"}), 413
    user.dashboard_prefs = serializado
    db.session.commit()
    return jsonify({"success": True})


# ── Columnas visibles del Inventario (por usuario) ─────────────────────
# Reemplaza al viejo data/column_config.json de la app de escritorio (un solo archivo
# compartido, sin noción de usuario) -- acá cada Usuario.inventario_columnas guarda su
# propia lista, mismo patrón que dashboard_prefs/filter_presets arriba.

@bp_api.route("/inventario/columnas", methods=["GET"])
def inventario_get_columnas():
    """Devuelve las columnas visibles guardadas para el usuario actual (None = default, todas visibles)."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "No autorizado"}), 401
    if user.inventario_columnas:
        try:
            import json as _json
            return jsonify({"columnas": _json.loads(user.inventario_columnas)})
        except Exception:
            pass
    return jsonify({"columnas": None})


@bp_api.route("/inventario/columnas", methods=["POST"])
def inventario_save_columnas():
    """Guarda la lista de columnas visibles del Inventario para el usuario actual."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "No autorizado"}), 401
    data = request.get_json(silent=True) or {}
    columnas = data.get("columnas")
    if columnas is None or not isinstance(columnas, list):
        return jsonify({"error": "Falta el campo 'columnas' (lista de column keys visibles)"}), 400
    import json as _json
    user.inventario_columnas = _json.dumps(columnas, ensure_ascii=False)
    db.session.commit()
    return jsonify({"success": True})


# ── Presets de Filtros Guardados en Base de Datos ──────────────────────

@bp_api.route("/filtros/presets", methods=["GET"])
def get_filter_presets():
    """Devuelve los presets de filtros guardados en la BD para el usuario actual."""
    user = get_current_user()
    if not user:
        return jsonify({"presets": []})
    if user.filter_presets:
        try:
            import json as _json
            return jsonify({"presets": _json.loads(user.filter_presets)})
        except Exception:
            pass
    return jsonify({"presets": []})


@bp_api.route("/filtros/presets", methods=["POST"])
def save_filter_presets():
    """Guarda en la BD SQLite la lista de presets de filtros del usuario actual."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "No autorizado"}), 401
    data = request.get_json(silent=True) or {}
    presets = data.get("presets")
    if presets is None:
        return jsonify({"error": "Falta el campo 'presets'"}), 400
    import json as _json
    user.filter_presets = _json.dumps(presets, ensure_ascii=False)
    db.session.commit()
    return jsonify({"success": True})


@bp_api.route("/csrf-token")
def csrf_token():
    """Token CSRF (double-submit) para que el SPA lo mande en header X-CSRFToken en
    cada request mutante. Accesible sin login (ver allowed_endpoints en web/app.py) porque
    hace falta antes de loguear, y login_user()/logout_user() hacen session.clear(), lo que
    invalida el token anterior — el frontend vuelve a pedirlo tras login/logout."""
    return jsonify({"csrf_token": generate_csrf()})


@bp_api.route("/auth/me")
def auth_me():

    user = get_current_user()
    if not user:
        return jsonify({"authenticated": False, "user": None})
    return jsonify({
        "authenticated": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "rol": user.rol,
            "nombre_completo": user.nombre_completo,
            "email": user.email,
            "must_change_password": user.must_change_password
        }
    })


@bp_api.route("/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def auth_login():
    from datetime import datetime, timedelta
    from web.routes.auth_routes import MAX_INTENTOS_FALLIDOS, BLOQUEO_MINUTOS

    data = request.get_json(silent=True) or request.form
    username = data.get("username", "").strip()
    password = data.get("password", "")

    user = Usuario.query.filter_by(username=username, activo=True).first()
    bloqueado = bool(user and user.bloqueado_hasta and user.bloqueado_hasta > datetime.utcnow())

    if user and not bloqueado and user.check_password(password):
        user.intentos_fallidos = 0
        user.bloqueado_hasta = None
        login_user(user)
        db.session.commit()
        return jsonify({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "rol": user.rol,
                "nombre_completo": user.nombre_completo,
                "email": user.email,
                "must_change_password": user.must_change_password
            }
        })

    if user and not bloqueado:
        user.intentos_fallidos = (user.intentos_fallidos or 0) + 1
        if user.intentos_fallidos >= MAX_INTENTOS_FALLIDOS:
            user.bloqueado_hasta = datetime.utcnow() + timedelta(minutes=BLOQUEO_MINUTOS)

    registrar_auditoria(
        accion="login_bloqueado" if bloqueado else "login_fallido",
        recurso=username,
        detalle="Intento de login sobre cuenta bloqueada (JSON)" if bloqueado else "Intento de login JSON fallido",
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({"success": False, "error": "Usuario o contraseña incorrectos."}), 401


@bp_api.route("/auth/logout", methods=["POST", "GET"])
def auth_logout():
    logout_user()
    return jsonify({"success": True})


@bp_api.route("/maquinas/<int:maquina_id>/tareas_eventos")
def maquina_tareas_eventos_api(maquina_id):
    """
    Retorna la lista de tareas y eventos vCenter (sección Supervisar/Monitor)
    almacenados para una máquina virtual específica.
    """
    from web.db import VMTareaEvento
    m = Maquina.query.get_or_404(maquina_id)
    evts = (
        VMTareaEvento.query
        .filter_by(maquina_id=m.id)
        .order_by(VMTareaEvento.fecha.desc())
        .limit(100)
        .all()
    )
    return jsonify({
        "maquina_id": m.id,
        "nombre_vm": m.nombre,
        "total": len(evts),
        "eventos": [e.to_dict() for e in evts]
    })


@bp_api.route("/pools/detalladas")
def pools_detalladas_api():
    """
    Retorna la lista enriquecida de todas las Pools de Horizon junto a sus métricas de VMs
    y autorizaciones locales y globales asociadas.
    """
    from web.db import Pool, PoolEntitlement, Maquina
    pools = Pool.query.filter_by(activo=True).all()
    maquinas_activas = _get_current_machines()
    
    # Agrupar métricas por pool (lowercase)
    metrics_by_pool = {}
    segmentacion_global = {"masters": 0, "plantillas": 0, "vdi_pool": 0, "estaticas": 0}
    segmentacion_por_origen = {}
    _TP_KEY = {"MASTER": "masters", "TEMPLATE": "plantillas", "VDI_POOL": "vdi_pool", "VM_ESTATICA": "estaticas"}

    for m in maquinas_activas:
        p_name = (m.pool or "Sin Pool").strip().lower()
        if p_name not in metrics_by_pool:
            metrics_by_pool[p_name] = {
                "total_vms": 0,
                "conectadas": 0,
                "disponibles": 0,
                "desconectadas": 0,
                "errores": 0,
                "masters": 0,
                "plantillas": 0,
                "vdi_pool": 0,
                "estaticas": 0,
                "disco_usado_gb": 0.0,
                "disco_provisionado_gb": 0.0,
            }
        metrics_by_pool[p_name]["total_vms"] += 1
        metrics_by_pool[p_name]["disco_usado_gb"] += m.disk_used_gb or 0
        metrics_by_pool[p_name]["disco_provisionado_gb"] += m.disk_provisioned_gb or 0
        st = (m.estado_horizon or "").upper()
        v_st = (m.estado_vcenter or "").upper()
        is_on = v_st in ("POWERED_ON", "POWEREDON")
        is_off = v_st in ("POWERED_OFF", "POWEREDOFF")

        if st == "CONNECTED" or (is_on and bool(m.usuario_asignado)):
            metrics_by_pool[p_name]["conectadas"] += 1
        elif st == "AVAILABLE" or (is_on and not m.usuario_asignado):
            metrics_by_pool[p_name]["disponibles"] += 1
        elif st == "DISCONNECTED" or is_off:
            metrics_by_pool[p_name]["desconectadas"] += 1
        elif "ERROR" in st or "UNREACHABLE" in st or getattr(m, 'in_error_state', False):
            metrics_by_pool[p_name]["errores"] += 1

        seg_key = _TP_KEY.get(m.tipo_provisionamiento)
        if seg_key:
            metrics_by_pool[p_name][seg_key] += 1
            segmentacion_global[seg_key] += 1
            origen_key = (m.origen or "sin_origen").lower()
            if origen_key not in segmentacion_por_origen:
                segmentacion_por_origen[origen_key] = {"masters": 0, "plantillas": 0, "vdi_pool": 0, "estaticas": 0}
            segmentacion_por_origen[origen_key][seg_key] += 1

    # Agrupar autorizaciones por pool_nombre (lowercase)
    entitlements_by_pool = {}
    all_ents = PoolEntitlement.query.all()
    for e in all_ents:
        p_key = (e.pool_nombre or "").strip().lower()
        if p_key not in entitlements_by_pool:
            entitlements_by_pool[p_key] = {"locales": [], "globales": []}
        item_d = e.to_dict()
        if e.tipo_entitlement == "Global":
            entitlements_by_pool[p_key]["globales"].append(item_d)
        else:
            entitlements_by_pool[p_key]["locales"].append(item_d)

    result = []
    for p in pools:
        p_dict = p.to_dict()
        p_key = p.nombre.strip().lower()
        met = dict(metrics_by_pool.get(p_key, {
            "total_vms": 0, "conectadas": 0, "disponibles": 0, "desconectadas": 0, "errores": 0,
            "masters": 0, "plantillas": 0, "vdi_pool": 0, "estaticas": 0,
            "disco_usado_gb": 0.0, "disco_provisionado_gb": 0.0,
        }))
        met["disco_usado_gb"] = round(met.get("disco_usado_gb", 0) or 0, 1)
        met["disco_provisionado_gb"] = round(met.get("disco_provisionado_gb", 0) or 0, 1)
        ents = entitlements_by_pool.get(p_key, {"locales": [], "globales": []})
        
        p_dict["metricas"] = met
        p_dict["autorizaciones_locales"] = ents["locales"]
        p_dict["autorizaciones_globales"] = ents["globales"]
        p_dict["total_autorizaciones"] = len(ents["locales"]) + len(ents["globales"])
        result.append(p_dict)

    return jsonify({
        "total": len(result),
        "items": result,
        "segmentacion_global": segmentacion_global,
        "segmentacion_por_origen": segmentacion_por_origen,
    })


@bp_api.route("/granja/farms")
def granja_farms_api():
    """Farms con Pool RDS enlazado (si hay), sus Apps, sus RDS Servers, y el rollup de
    autorizados (derivado -- ver web/granja_utils.py)."""
    from web.db import Farm, Pool
    from web.granja_utils import autorizados_por_farm

    farms = Farm.query.filter_by(activo=True).all()
    result = []
    for f in farms:
        f_dict = f.to_dict()
        pool_rds = Pool.query.filter_by(farm_id=f.id, activo=True).first()
        f_dict["pool_enlazado"] = pool_rds.to_dict() if pool_rds else None
        f_dict["aplicaciones"] = [a.to_dict() for a in f.aplicaciones if a.activo]
        f_dict["rds_servers"] = [rs.to_dict() for rs in f.rds_servers if rs.activo]
        f_dict["autorizados"] = autorizados_por_farm(f)
        result.append(f_dict)

    return jsonify({"total": len(result), "items": result})


@bp_api.route("/granja/aplicaciones")
def granja_aplicaciones_api():
    """Aplicaciones publicadas con sus autorizaciones locales/globales enriquecidas con
    Directorio (AD), mismo shape que /pools/detalladas."""
    from web.db import AplicacionPublicada, AplicacionEntitlement
    from web.granja_utils import enriquecer_entitlements_con_directorio

    apps = AplicacionPublicada.query.filter_by(activo=True).all()
    ents_by_app = {}
    for e in AplicacionEntitlement.query.all():
        ents_by_app.setdefault(e.aplicacion_nombre, {"locales": [], "globales": []})
        item = e.to_dict()
        if e.tipo_entitlement == "Global":
            ents_by_app[e.aplicacion_nombre]["globales"].append(item)
        else:
            ents_by_app[e.aplicacion_nombre]["locales"].append(item)

    result = []
    for a in apps:
        a_dict = a.to_dict()
        ents = ents_by_app.get(a.nombre, {"locales": [], "globales": []})
        a_dict["autorizaciones_locales"] = enriquecer_entitlements_con_directorio(ents["locales"])
        a_dict["autorizaciones_globales"] = enriquecer_entitlements_con_directorio(ents["globales"])
        a_dict["total_autorizaciones"] = len(ents["locales"]) + len(ents["globales"])
        result.append(a_dict)

    return jsonify({"total": len(result), "items": result})


@bp_api.route("/pools/masters")
def pools_masters_api():
    """Vista cruzada de VMs Master: a cuántos pools/VMs alimenta cada una, cuánto storage
    consumen esos pools en total, y si sigue en uso o quedó en desuso -- para identificar
    masters viejas que ya nadie publica y podrían darse de baja.

    Bug real encontrado 2026-08-13: "en_uso" usaba solo Pool.master_vm_actual, que se
    llena parseando eventos de audit "Image Publish...succeeded" -- en la práctica, solo
    3 de 48 pools tenían ese evento capturado alguna vez (no se genera si nunca se
    republicó la imagen desde que arrancó a monitorearse este sistema). Resultado: casi
    todo mostraba "en desuso" y "total_vms" quedaba subcontado a casi 0 para masters que
    en realidad alimentan varios pools activos. Fix: usar Pool.master_moref (MoRef real de
    provisioning_settings.parent_vm_id, viene siempre en pools instant-clone, no depende
    de eventos) como fuente primaria, con master_vm_actual como fallback/complemento."""
    masters = Maquina.query.filter_by(activo=True, tipo_provisionamiento="MASTER").all()
    pools = Pool.query.filter_by(activo=True).all()
    maquinas_activas = _get_current_machines()

    stats_por_pool_id = {}
    for m in maquinas_activas:
        if not m.pool_id:
            continue
        s = stats_por_pool_id.setdefault(m.pool_id, {"vms": 0, "disco_usado_gb": 0.0, "disco_provisionado_gb": 0.0})
        s["vms"] += 1
        s["disco_usado_gb"] += m.disk_used_gb or 0
        s["disco_provisionado_gb"] += m.disk_provisioned_gb or 0

    pools_por_moref = {}
    pools_por_nombre_master = {}
    for p in pools:
        if p.master_moref:
            pools_por_moref.setdefault(p.master_moref, []).append(p)
        if p.master_vm_actual:
            pools_por_nombre_master.setdefault(p.master_vm_actual.strip().lower(), []).append(p)

    # Nombres únicos de master (case-insensitive) -- la misma master puede existir como
    # fila Maquina separada en más de un vCenter (ej. DT y MZ), no listarla duplicada.
    nombres_master = {}
    for m in masters:
        clave = m.nombre.strip().lower()
        nombres_master.setdefault(clave, []).append(m)

    resultado = []
    for clave, filas in nombres_master.items():
        pools_usando_por_id = {}
        for m in filas:
            for p in pools_por_moref.get(m.external_id, []):
                pools_usando_por_id[p.id] = p
        for p in pools_por_nombre_master.get(clave, []):
            pools_usando_por_id[p.id] = p
        pools_usando = list(pools_usando_por_id.values())
        total_vms = sum(stats_por_pool_id.get(p.id, {}).get("vms", 0) for p in pools_usando)
        disco_usado = sum(stats_por_pool_id.get(p.id, {}).get("disco_usado_gb", 0) for p in pools_usando)
        disco_prov = sum(stats_por_pool_id.get(p.id, {}).get("disco_provisionado_gb", 0) for p in pools_usando)
        fechas_pub = [p.imagen_actualizada_en for p in pools_usando if p.imagen_actualizada_en]

        resultado.append({
            "nombre": filas[0].nombre,
            "origenes": sorted({m.origen for m in filas if m.origen}),
            "en_uso": len(pools_usando) > 0,
            "pools": [{"id": p.id, "nombre": p.nombre, "snapshot_actual": p.snapshot_actual} for p in pools_usando],
            "total_pools": len(pools_usando),
            "total_vms": total_vms,
            "disco_usado_gb": round(disco_usado, 1),
            "disco_provisionado_gb": round(disco_prov, 1),
            "ultima_publicacion": max(fechas_pub).strftime("%d/%m/%Y %H:%M") if fechas_pub else "",
        })

    # Desuso primero (lo que hay que revisar), y dentro de cada grupo, más VMs impactadas primero.
    resultado.sort(key=lambda r: (r["en_uso"], -r["total_vms"]))
    return jsonify({
        "total": len(resultado),
        "en_uso": sum(1 for r in resultado if r["en_uso"]),
        "en_desuso": sum(1 for r in resultado if not r["en_uso"]),
        "items": resultado,
    })


@bp_api.route("/pools/capacidad")
def pools_capacidad_api():
    """Ocupacion de pools VDI Instant Clone/Manual (VDI_POOL) -- detecta pools sin
    escritorios 'disponibles' (riesgo real de 'No desktop available' para el proximo
    usuario que intente conectarse) o con ocupacion muy alta. No hay campo de politica
    de capacidad (min_spare_desktops/max_desktops) en la API de Horizon que este
    proyecto capture hoy -- esto mide ocupacion OBSERVADA (cuantas de las VMs que ya
    existen en el pool estan libres ahora), no la politica de auto-provisioning."""
    from web.db import Pool

    pools = Pool.query.filter_by(activo=True, enabled=True).all()
    maquinas = _get_current_machines()

    metrics = {}
    for m in maquinas:
        if m.tipo_provisionamiento != "VDI_POOL":
            continue
        p_name = (m.pool or "").strip().lower()
        if not p_name:
            continue
        d = metrics.setdefault(p_name, {"total": 0, "disponibles": 0, "conectadas": 0, "desconectadas": 0, "errores": 0})
        est = clasificar_estado_maquina(m)
        d["total"] += 1
        if est["en_error"]:
            d["errores"] += 1
        elif est["disponible"]:
            d["disponibles"] += 1
        elif est["conectada"]:
            d["conectadas"] += 1
        elif est["desconectada"] or est["apagada"]:
            d["desconectadas"] += 1

    items = []
    for p in pools:
        d = metrics.get(p.nombre.strip().lower())
        if not d or d["total"] == 0:
            continue
        pct_ocupado = round((d["total"] - d["disponibles"]) / d["total"] * 100, 1)
        sin_disponibles = d["disponibles"] == 0
        riesgo = "critico" if sin_disponibles else ("alto" if pct_ocupado >= 90 else "normal")
        items.append({
            "pool": p.display_name or p.nombre,
            "user_assignment": p.user_assignment or "Dedicated",
            **d,
            "pct_ocupado": pct_ocupado,
            "riesgo": riesgo,
        })

    items.sort(key=lambda x: -x["pct_ocupado"])
    return jsonify({
        "total_pools": len(items),
        "criticos": sum(1 for it in items if it["riesgo"] == "critico"),
        "altos": sum(1 for it in items if it["riesgo"] == "alto"),
        "items": items,
    })


def _latest_snapshot_subq():
    return (
        db.session.query(
            InventarioSnapshot.servidor_id,
            func.max(InventarioSnapshot.id).label("max_id")
        )
        .filter(InventarioSnapshot.estado.in_(("ok", "completado")))
        .group_by(InventarioSnapshot.servidor_id)
        .subquery()
    )


def _get_current_machines(servidor_id=None, tipo=None, origen=None, incluir_infra_interna=False):
    q = Maquina.query.filter_by(activo=True)
    if servidor_id:
        q = q.filter(Maquina.servidor_id == servidor_id)
    if tipo:
        q = q.filter(Maquina.tipo == tipo)
    if origen:
        # Maquina.origen es una @property de Python (resuelve via origen_rel o
        # _origen_str), no una columna mapeada -- Maquina.origen == origen se evalúa en
        # Python puro (siempre False) y .filter(False) devuelve 0 filas siempre, sin
        # importar el valor de origen. Bug pre-existente, no introducido acá: hay que
        # pegarle a la columna real (_origen_str) o al join contra el catálogo Origen.
        q = q.filter(db.or_(Maquina._origen_str == origen, Maquina.origen_rel.has(codigo=origen)))
    if not incluir_infra_interna:
        # vCLS/cp-parent/cp-replica/cp-template son plomería de plataforma (vSphere Cluster
        # Services, artefactos de Instant Clone), no VMs de negocio -- se excluyen de todo
        # KPI/agregado (este es el único punto de entrada compartido por esos endpoints) pero
        # siguen visibles/filtrables en /api/maquinas (tabla de inventario), que no pasa por acá.
        q = q.filter(db.or_(
            Maquina.tipo_provisionamiento != "VM_ESTATICA",
            db.and_(*[db.not_(Maquina.nombre.ilike(f"{p}%")) for p in _PREFIJOS_INFRA_INTERNA])
        ))
    return q.all()


@bp_api.route("/directorio/vdis_retenidas")
def directorio_vdis_retenidas_api():
    """VDI Persistente (Dedicated) cuyo usuario_asignado corresponde a una cuenta ya
    inactiva en AD (DirectorioUsuario.activo_ad=False) -- escritorio dedicado que nadie
    mas puede usar, reservado para alguien que ya no esta. Solo Persistente/Dedicated:
    en pools Floating el usuario_asignado es la ultima sesion conocida, no una reserva
    fija, así que una cuenta deshabilitada ahi no implica un recurso retenido."""
    usuarios_inactivos = {}
    for u in DirectorioUsuario.query.filter_by(activo_ad=False).all():
        if u.username:
            usuarios_inactivos[u.username.lower()] = u
        if u.sam_account_name:
            usuarios_inactivos.setdefault(u.sam_account_name.lower(), u)

    if not usuarios_inactivos:
        return jsonify({"count": 0, "items": []})

    maquinas = _get_current_machines()
    items = []
    for m in maquinas:
        if m.tipo_provisionamiento != "VDI_POOL" or not m.usuario_asignado:
            continue
        if m.persistencia != "Persistente":
            continue
        u = usuarios_inactivos.get(m.usuario_asignado.strip().lower())
        if not u:
            continue
        items.append({
            "nombre_vm": m.nombre,
            "pool": m.pool,
            "usuario_asignado": m.usuario_asignado,
            "usuario_nombre_completo": u.nombre_completo or "",
            "usuario_empresa": u.empresa or "",
        })

    return jsonify({"count": len(items), "items": items})


@bp_api.route("/directorio/usuarios")
def directorio_usuarios_api():
    q = request.args.get("q", "").strip()
    solo_inactivos = request.args.get("inactivos", "") == "1"
    empresa_filter = request.args.get("empresa", "").strip()
    estado_ad_filter = request.args.get("estado_ad", "").strip()
    con_vms_filter = request.args.get("con_vms", "").strip()

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
    if solo_inactivos or estado_ad_filter == "inactivo":
        query = query.filter(DirectorioUsuario.activo_ad == False)
    elif estado_ad_filter == "activo":
        query = query.filter(DirectorioUsuario.activo_ad == True)

    if empresa_filter:
        query = query.filter(DirectorioUsuario.empresa.ilike(f"%{empresa_filter}%"))

    users = query.order_by(DirectorioUsuario.nombre_completo).all()

    # Pre-cargar vinculaciones con VMs/VDIs
    vinculos = MaquinaUsuarioDir.query.all()
    maquinas_map = {m.id: m for m in Maquina.query.all()}
    user_vms_map = {}
    for v in vinculos:
        m = maquinas_map.get(v.maquina_id)
        if m:
            if v.directorio_usuario_id not in user_vms_map:
                user_vms_map[v.directorio_usuario_id] = []
            user_vms_map[v.directorio_usuario_id].append({
                "vinculo_id": v.id,
                "id": m.id,
                "nombre": m.nombre,
                "tipo": m.tipo,
                "pool": m.pool or "Estática",
                "empresa": m.empresa or "—",
                "estado": m.estado_horizon or m.estado_vcenter or "—",
            })

    res = []
    for u in users:
        vms = user_vms_map.get(u.id, [])
        if con_vms_filter == "con_vms" and not vms:
            continue
        if con_vms_filter == "sin_vms" and vms:
            continue

        d = u.to_dict()
        d["vms"] = vms
        res.append(d)

    return jsonify(res)


@bp_api.route("/infraestructura")
def infraestructura_api():
    """Datastores y hosts ESXi por vCenter, con % de uso — antes esta info se pedía
    para armar un lookup de nombre y se descartaba (ver core/vcenter_rest.py)."""
    servidores_map = {s.id: s.nombre for s in Servidor.query.all()}

    ds_out = []
    for d in Datastore.query.filter_by(activo=True).order_by(Datastore.nombre).all():
        item = d.to_dict()
        item["servidor_nombre"] = servidores_map.get(d.servidor_id, "—")
        ds_out.append(item)

    h_out = []
    for h in HostEsxi.query.filter_by(activo=True).order_by(HostEsxi.nombre).all():
        item = h.to_dict()
        item["servidor_nombre"] = servidores_map.get(h.servidor_id, "—")
        h_out.append(item)

    return jsonify({
        "datastores": ds_out,
        "hosts": h_out,
        "datastores_criticos": sum(1 for d in ds_out if (d.get("espacio_usado_pct") or 0) >= 90),
        "hosts_desconectados": sum(1 for h in h_out if h.get("connection_state") and h["connection_state"] != "CONNECTED"),
    })


@bp_api.route("/kpis")
def kpis():
    servidor_id = request.args.get("servidor_id")
    tipo = request.args.get("tipo")
    origen = request.args.get("origen")
    return jsonify(cache_get_or_set(
        f"kpis:{servidor_id}:{tipo}:{origen}", 45,
        lambda: _compute_kpis(servidor_id, tipo, origen)
    ))


def _compute_kpis(servidor_id, tipo, origen):
    maquinas = _get_current_machines(servidor_id=servidor_id, tipo=tipo, origen=origen)
    estados = [clasificar_estado_maquina(m) for m in maquinas]

    total      = len(maquinas)
    vdi        = sum(1 for m in maquinas if m.tipo == "VDI")
    vm         = sum(1 for m in maquinas if m.tipo == "VM")
    conectadas = sum(1 for e in estados if e["conectada"])
    disponibles= sum(1 for e in estados if e["disponible"])
    huerfanas  = sum(1 for e in estados if e["huerfana"])
    errores    = sum(1 for e in estados if e["en_error"])

    # Consumos totales de recursos (CPU, RAM, Disco)
    active_machines = [
        m for m, e in zip(maquinas, estados)
        if e["conectada"] or e["disponible"] or e["encendida"]
    ]
    
    total_cpu_vcpus  = sum(m.cpu or 0 for m in maquinas)
    active_cpu_vcpus = sum(m.cpu or 0 for m in active_machines)

    total_ram_gb  = sum(m.ram_gb or 0 for m in maquinas)
    active_ram_gb = sum(m.ram_gb or 0 for m in active_machines)

    total_disk_gb  = sum(m.disk_provisioned_gb or m.disk_used_gb or 0 for m in maquinas)
    active_disk_gb = sum(m.disk_provisioned_gb or m.disk_used_gb or 0 for m in active_machines)

    # Desglose de consumo por Servidor (vCenter / Horizon)
    desglose_servidores_map = {}
    servidores_db = {s.id: s.nombre for s in Servidor.query.all()}

    for m in maquinas:
        srv_name = servidores_db.get(m.servidor_id) or (m.origen or "Sin Clasificar").upper()
        if srv_name not in desglose_servidores_map:
            desglose_servidores_map[srv_name] = {
                "servidor": srv_name,
                "vms": 0,
                "cpu_vcpus": 0,
                "ram_gb": 0.0,
                "disco_gb": 0.0,
            }
        desglose_servidores_map[srv_name]["vms"] += 1
        desglose_servidores_map[srv_name]["cpu_vcpus"] += (m.cpu or 0)
        desglose_servidores_map[srv_name]["ram_gb"] = round(desglose_servidores_map[srv_name]["ram_gb"] + (m.ram_gb or 0.0), 2)
        desglose_servidores_map[srv_name]["disco_gb"] = round(desglose_servidores_map[srv_name]["disco_gb"] + (m.disk_provisioned_gb or m.disk_used_gb or 0.0), 2)

    # Desglose por Plataforma (VDI vs VM)
    desglose_plataforma = {
        "VDI": {"tipo": "VDI", "vms": 0, "cpu_vcpus": 0, "ram_gb": 0.0, "disco_gb": 0.0},
        "VM":  {"tipo": "VM",  "vms": 0, "cpu_vcpus": 0, "ram_gb": 0.0, "disco_gb": 0.0},
    }
    for m in maquinas:
        t_key = "VDI" if m.tipo == "VDI" else "VM"
        desglose_plataforma[t_key]["vms"] += 1
        desglose_plataforma[t_key]["cpu_vcpus"] += (m.cpu or 0)
        desglose_plataforma[t_key]["ram_gb"] = round(desglose_plataforma[t_key]["ram_gb"] + (m.ram_gb or 0.0), 2)
        desglose_plataforma[t_key]["disco_gb"] = round(desglose_plataforma[t_key]["disco_gb"] + (m.disk_provisioned_gb or m.disk_used_gb or 0.0), 2)

    return {
        "total": total, "vdi": vdi, "vm": vm,
        "conectadas": conectadas, "disponibles": disponibles,
        "huerfanas": huerfanas, "errores": errores,
        "cpu": {
            "total_vcpus": total_cpu_vcpus,
            "active_vcpus": active_cpu_vcpus,
            "pct": round((active_cpu_vcpus / total_cpu_vcpus * 100), 2) if total_cpu_vcpus > 0 else 0
        },
        "ram": {
            "total_gb": round(total_ram_gb, 2),
            "active_gb": round(active_ram_gb, 2),
            "pct": round((active_ram_gb / total_ram_gb * 100), 2) if total_ram_gb > 0 else 0
        },
        "disco": {
            "total_gb": round(total_disk_gb, 2),
            "active_gb": round(active_disk_gb, 2),
            "pct": round((active_disk_gb / total_disk_gb * 100), 2) if total_disk_gb > 0 else 0
        },
        "desglose_servidores": list(desglose_servidores_map.values()),
        "desglose_plataforma": list(desglose_plataforma.values())
    }



@bp_api.route("/kpis/desglose")
def kpis_desglose():
    """
    Devuelve desglose completo por Servidor y por Origen:
    - Total VMs / VDI / VM
    - Encendidas (PoweredOn / POWERED_ON) vs Apagadas (PoweredOff / POWERED_OFF)
    - Conectadas vs Disponibles
    """
    return jsonify(cache_get_or_set("kpis:desglose", 45, _compute_kpis_desglose))


def _compute_kpis_desglose():
    maquinas = _get_current_machines()
    servidores = {s.id: s.nombre for s in Servidor.query.all()}

    by_servidor = {}
    by_origen = {}

    for m in maquinas:
        srv_name = servidores.get(m.servidor_id, "Desconocido")
        ori_code = (m.origen or "SIN ORIGEN").upper()

        e = clasificar_estado_maquina(m)
        is_on, is_off = e["encendida"], e["apagada"]
        is_connected, is_available = e["conectada"], e["disponible"]

        tipo_prov = m.tipo_provisionamiento or clasificar_provisionamiento(m.pool)

        # Por Servidor
        if srv_name not in by_servidor:
            by_servidor[srv_name] = {
                "nombre": srv_name, "total": 0, "encendidas": 0, "apagadas": 0, "sin_dato_energia": 0,
                "vdi": 0, "vm": 0, "conectadas": 0, "disponibles": 0,
                "masters": 0, "plantillas": 0, "vdi_pool": 0, "estaticas": 0,
            }
        by_servidor[srv_name]["total"] += 1
        if m.tipo == "VDI": by_servidor[srv_name]["vdi"] += 1
        elif m.tipo == "VM": by_servidor[srv_name]["vm"] += 1
        if is_on: by_servidor[srv_name]["encendidas"] += 1
        elif is_off: by_servidor[srv_name]["apagadas"] += 1
        else: by_servidor[srv_name]["sin_dato_energia"] += 1

        if is_connected: by_servidor[srv_name]["conectadas"] += 1
        if is_available: by_servidor[srv_name]["disponibles"] += 1
        by_servidor[srv_name][{"MASTER": "masters", "TEMPLATE": "plantillas",
                                "VDI_POOL": "vdi_pool", "VM_ESTATICA": "estaticas"}[tipo_prov]] += 1

        # Por Origen
        if ori_code not in by_origen:
            by_origen[ori_code] = {
                "nombre": ori_code, "total": 0, "encendidas": 0, "apagadas": 0, "sin_dato_energia": 0,
                "vdi": 0, "vm": 0, "conectadas": 0, "disponibles": 0,
                "masters": 0, "plantillas": 0, "vdi_pool": 0, "estaticas": 0,
            }
        by_origen[ori_code]["total"] += 1
        if m.tipo == "VDI": by_origen[ori_code]["vdi"] += 1
        elif m.tipo == "VM": by_origen[ori_code]["vm"] += 1
        if is_on: by_origen[ori_code]["encendidas"] += 1
        elif is_off: by_origen[ori_code]["apagadas"] += 1
        else: by_origen[ori_code]["sin_dato_energia"] += 1

        if is_connected: by_origen[ori_code]["conectadas"] += 1
        if is_available: by_origen[ori_code]["disponibles"] += 1
        by_origen[ori_code][{"MASTER": "masters", "TEMPLATE": "plantillas",
                              "VDI_POOL": "vdi_pool", "VM_ESTATICA": "estaticas"}[tipo_prov]] += 1

    pools_distintos = {m.pool for m in maquinas if m.pool and m.pool.strip().lower() not in _POOLS_SIN_ASIGNAR}

    return {
        "por_servidor": sorted(by_servidor.values(), key=lambda x: -x["total"]),
        "por_origen": sorted(by_origen.values(), key=lambda x: -x["total"]),
        "segmentacion_global": {
            "total_vms": len(maquinas),
            "masters": sum(v["masters"] for v in by_servidor.values()),
            "plantillas": sum(v["plantillas"] for v in by_servidor.values()),
            "vdi_pool": sum(v["vdi_pool"] for v in by_servidor.values()),
            "estaticas": sum(v["estaticas"] for v in by_servidor.values()),
            "total_pools": len(pools_distintos),
        }
    }


@bp_api.route("/autorizaciones/summary")
def autorizaciones_summary():
    """Retorna resumen de autorizaciones (entitlements) de Horizon por Pool y Usuario/Grupo."""
    from web.db import PoolEntitlement, Pool
    entitlements = PoolEntitlement.query.all()
    pools = Pool.query.filter_by(activo=True).all()

    by_pool = {}
    for p in pools:
        by_pool[p.nombre] = {
            "pool": p.nombre,
            "display_name": p.display_name or p.nombre,
            "user_assignment": p.user_assignment or "Dedicated",
            "locales": 0,
            "globales": 0,
            "total": 0,
            "usuarios": []
        }

    for e in entitlements:
        p_name = e.pool_nombre or "General"
        if p_name not in by_pool:
            by_pool[p_name] = {
                "pool": p_name,
                "display_name": p_name,
                "user_assignment": "Dedicated",
                "locales": 0,
                "globales": 0,
                "total": 0,
                "usuarios": []
            }
        if e.tipo_entitlement == "Global":
            by_pool[p_name]["globales"] += 1
        else:
            by_pool[p_name]["locales"] += 1
        by_pool[p_name]["total"] += 1
        if len(by_pool[p_name]["usuarios"]) < 5:
            by_pool[p_name]["usuarios"].append({
                "nombre": e.usuario_o_grupo,
                "tipo": "Grupo" if e.es_grupo else "Usuario",
                "scope": e.tipo_entitlement
            })

    sorted_pools = sorted(by_pool.values(), key=lambda x: -x["total"])
    return jsonify({
        "total_entitlements": len(entitlements),
        "total_pools": len(pools),
        "pools": sorted_pools[:10]
    })


@bp_api.route("/hosts/summary")
def hosts_summary():
    """Distribucion de VMs/recursos por vCenter + estado real de los hosts ESXi.

    Investigado a fondo 2026-09-02: Maquina.vcenter_host NO es el host ESXi fisico --
    es la direccion del SERVIDOR vCenter (correcto para el campo "vCenter Host" que se
    muestra en la ficha de la VM). La causa es un bug real en core/vcenter_rest.py linea
    ~284 (`esxi_host = hosts_lookup.get(vm_raw.get("host")) or srv`): el lookup del host
    ESXi real por moref falla siempre (confirmado: 100% de 1447 VMs activas caen en el
    fallback `or srv`), asi que vcenter_host termina siendo la direccion del vCenter para
    absolutamente todas las VMs. No se puede arreglar el cruce VM-a-host-ESXi sin probar
    en vivo contra la API real (el fetch de /api/vcenter/host que llena hosts_lookup
    puede no traer el mismo formato de moref que el "host" del listado de VMs -- requiere
    inspeccionar la respuesta real). Mientras tanto este endpoint separa las dos cosas
    reales que SI se pueden mostrar sin inventar nada: (1) carga real por vCenter
    (vcenter_host, dato correcto) y (2) estado real de conexion de cada host ESXi (tabla
    HostEsxi, viene de una llamada aparte que si funciona) -- sin fingir que se puede
    cruzar VM con host individual todavia."""
    from web.db import HostEsxi

    maquinas = _get_current_machines()
    by_vcenter = {}
    for m in maquinas:
        key = m.vcenter_host or "Sin vCenter identificado"
        d = by_vcenter.setdefault(key, {
            "vcenter": key, "total_vms": 0, "powered_on": 0, "powered_off": 0,
            "sin_dato_energia": 0, "cpu_vcpus": 0, "ram_gb": 0.0, "disk_gb": 0.0,
        })
        d["total_vms"] += 1
        est = clasificar_estado_maquina(m)
        if est["encendida"]:
            d["powered_on"] += 1
        elif est["apagada"]:
            d["powered_off"] += 1
        else:
            d["sin_dato_energia"] += 1
        d["cpu_vcpus"] += (m.cpu or 0)
        d["ram_gb"] = round(d["ram_gb"] + (m.ram_gb or 0.0), 2)
        d["disk_gb"] = round(d["disk_gb"] + (m.disk_provisioned_gb or 0.0), 2)

    hosts_esxi = [
        {"host": h.nombre, "connection_state": h.connection_state or "DESCONOCIDO", "power_state": h.power_state or ""}
        for h in HostEsxi.query.filter_by(activo=True).order_by(HostEsxi.nombre).all()
    ]

    return jsonify({
        "por_vcenter": sorted(by_vcenter.values(), key=lambda x: -x["total_vms"]),
        "hosts_esxi": hosts_esxi,
        "hosts_esxi_caidos": sum(1 for h in hosts_esxi if h["connection_state"].upper() != "CONNECTED"),
    })


@bp_api.route("/integridad/summary")
def integridad_summary():
    """Retorna métricas de salud y reconciliación del inventario."""
    import os, json
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    audit_file = os.path.join(data_dir, "audit_reconciliacion.json")

    audit_data = {}
    if os.path.exists(audit_file):
        try:
            with open(audit_file, "r", encoding="utf-8") as f:
                audit_data = json.load(f)
        except Exception:
            pass

    from web.db import Maquina, Pool, VMTareaEvento
    activas = Maquina.query.filter_by(activo=True).all()
    total_activas = len(activas)
    # es_huerfana (kpi_utils) -- misma definicion que /api/huerfanas y /api/semaforo.
    # Antes esto contaba TODA maquina sin usuario_asignado (apagadas, templates,
    # masters incluidos), inflando el numero muy por encima de lo que mostraban los
    # otros widgets de huerfanas para el mismo dataset.
    huerfanas = sum(1 for m in activas if es_huerfana(m))
    eventos_totales = VMTareaEvento.query.count()

    resumen = audit_data.get("resumen_reconciliacion", {})
    return jsonify({
        "estado": resumen.get("estado_integridad") or ("OK" if huerfanas < 50 else "ADVERTENCIA"),
        "total_activas": total_activas,
        "huerfanas": huerfanas,
        "duplicados_fusionados": resumen.get("duplicados_fusionados", 0),
        "eventos_totales": eventos_totales,
        "eventos_huerfanos": resumen.get("eventos_huerfanos", 0),
        "fecha_auditoria": audit_data.get("fecha_auditoria") or "En Tiempo Real"
    })


@bp_api.route("/distribucion/empresa")
def distribucion_empresa():
    maquinas = _get_current_machines(
        tipo=request.args.get("tipo"),
        origen=request.args.get("origen"),
    )
    counts: dict[str, int] = {}
    display_names: dict[str, str] = {}

    for m in maquinas:
        raw = (m.empresa or "").strip()
        if not raw:
            norm_key = "SIN ASIGNAR"
            disp = "Sin Asignar"
        else:
            norm_key = raw.upper()
            disp = raw.capitalize() if raw.islower() or raw.isupper() else raw

        display_names[norm_key] = display_names.get(norm_key, disp)
        counts[norm_key] = counts.get(norm_key, 0) + 1

    sorted_items = sorted(counts.items(), key=lambda x: -x[1])
    labels = [display_names[k] for k, _ in sorted_items]
    data = [v for _, v in sorted_items]
    return jsonify({"labels": labels, "data": data})


@bp_api.route("/distribucion/pool")
def distribucion_pool():
    maquinas = _get_current_machines(
        tipo=request.args.get("tipo"),
        origen=request.args.get("origen"),
    )
    counts: dict[str, int] = {}
    for m in maquinas:
        k = m.pool or "Sin Pool"
        counts[k] = counts.get(k, 0) + 1
    counts = dict(sorted(counts.items(), key=lambda x: -x[1])[:15])
    return jsonify({"labels": list(counts.keys()), "data": list(counts.values())})


@bp_api.route("/distribucion/origen")
def distribucion_origen():
    """Ademas del total por origen, segmenta cuantas son VDI real (VDI_POOL, en un pool
    Horizon) vs VM estatica (sin pool, ej. RPA/servidores) -- pedido 2026-09-02: el total
    solo no dice si esas VMs son escritorios VDI o equipos estaticos.

    "infra_interna" (agregado 2026-09-04, corregido el mismo día) separa dentro de
    VM_ESTATICA las VMs de plataforma vSphere/Horizon (vCLS-*, cp-parent-*, cp-replica-*,
    cp-template-*, ver _PREFIJOS_INFRA_INTERNA) -- antes quedaban mezcladas en
    "vm_estatica" como si fueran equipos de usuario reales (RPA, etc.).

    OJO: "counts"/"data" (el total del donut, lo que suma "Total VDI") sigue EXCLUYENDO
    infra_interna -- mismo criterio que /api/kpis (KpiWidget "Total VDI & Conexiones"),
    /semaforo, etc. Si esas 101 VMs de plomería entraran al total acá, este widget y
    "Total VDI" mostrarían números distintos para lo que el usuario espera que sea "la
    misma cifra" (confirmado real 2026-09-04: primer intento las sumó al total, el
    usuario detectó el desvío -- 1161 vs 1060, exactamente las 101 infra interna).
    infra_interna se cuenta APARTE, visible en el tooltip/lista pero fuera del total."""
    maquinas = _get_current_machines()
    maquinas_infra = _get_current_machines(incluir_infra_interna=True)
    counts: dict[str, int] = {}
    segmentado: dict[str, dict] = {}
    for m in maquinas:
        k = m.origen or "—"
        counts[k] = counts.get(k, 0) + 1
        seg = segmentado.setdefault(k, {"vdi": 0, "vm_estatica": 0, "master": 0, "plantilla": 0, "infra_interna": 0})
        tp = m.tipo_provisionamiento
        if tp == "VDI_POOL":
            seg["vdi"] += 1
        elif tp == "VM_ESTATICA":
            seg["vm_estatica"] += 1
        elif tp == "MASTER":
            seg["master"] += 1
        elif tp == "TEMPLATE":
            seg["plantilla"] += 1

    ids_normales = {m.id for m in maquinas}
    for m in maquinas_infra:
        if m.id in ids_normales:
            continue  # ya contada arriba, esta es una de las 101 infra interna extra
        k = m.origen or "—"
        seg = segmentado.setdefault(k, {"vdi": 0, "vm_estatica": 0, "master": 0, "plantilla": 0, "infra_interna": 0})
        seg["infra_interna"] += 1
        counts.setdefault(k, 0)  # asegura que el origen aparezca en labels aunque sea 100% infra interna

    labels = list(counts.keys())
    return jsonify({
        "labels": labels,
        "data": [counts[l] for l in labels],
        "segmentado": [segmentado[l] for l in labels],
    })


def _vm_leaf(m: "Maquina") -> dict:
    """Fila liviana de VM para el árbol -- solo lo necesario para una fila 'linda' en el
    explorador (badge de tipo, estado, tools) y para anclar al ficha real vía /maquinas/<id>."""
    return {
        "id": m.id,
        "nombre": m.nombre,
        "tipo_provisionamiento": m.tipo_provisionamiento,
        "estado_horizon": m.estado_horizon,
        # Agregado 2026-09-07 -- antes el árbol solo mostraba el punto de VMware Tools,
        # nada indicaba si la VM estaba realmente encendida o apagada en vCenter.
        "estado_vcenter": m.estado_vcenter,
        "tools_status": m.tools_status,
        "pool": m.pool,
    }


def _build_folder_tree(items: list[tuple[str, dict]]) -> dict:
    """Arma un árbol anidado {vms:[...], children:{segmento: {...}}} a partir de pares
    (ruta_carpeta, vm_leaf) -- ruta_carpeta viene de obtener_folders() (core/vcenter_soap.py),
    ej. "VDI-Workloads/Pool-A". Profundidad arbitraria, igual que vCenter."""
    root: dict = {"vms": [], "children": {}}
    for folder_path, vm in items:
        node = root
        for segmento in folder_path.split("/"):
            if not segmento:
                continue
            node = node["children"].setdefault(segmento, {"vms": [], "children": {}})
        node["vms"].append(vm)
    return root


@bp_api.route("/inventario/arbol")
def inventario_arbol():
    """Árbol de inventario por vCenter (DT/MZ/SU/CORE). Dos vistas posibles, elegidas
    por el query param `vista` (default 'carpetas'):
    - 'carpetas': replica la organización en carpetas del cliente vSphere (VMs & Templates) --
      pedido 2026-09-04.
    - 'computo': jerarquía real Datacenter/Cluster/Host (vista Hosts & Clusters) --
      agregado 2026-09-07, usa Maquina.ruta_computo en vez de Maquina.folder.

    Cada vista tiene dos fuentes, nunca mezcladas en silencio:
    - "real": la ruta real (folder o ruta_computo según `vista`), capturada por SOAP vía
      core.vcenter_soap (obtener_folders / obtener_topologia_computo -- ver
      _extraer_vcenter_cred en web/routes/inventario.py). Solo existe para VMs de
      vCenters donde ya corrió una extracción con el fix correspondiente.
    - "proxy": para todo el resto (ruta vacía -- extracción vieja, o SOAP falló esa
      corrida), se arma una jerarquía equivalente con datos que sí tenemos: Masters /
      Templates / VDI Pools (por pool Horizon real) / VM Estáticas (por categoría:
      RPA / Infra Interna / Copia / Huérfana / sin subcategoría).

    Incluye infra interna (vCLS-*/cp-*) a propósito -- a diferencia de /api/kpis o
    /distribucion/origen, esto es un explorador de inventario, no un total de "desktops
    reales", y esas VMs sí existen como objetos reales en el árbol de vCenter."""
    vista = "computo" if request.args.get("vista") == "computo" else "carpetas"
    campo_ruta = "ruta_computo" if vista == "computo" else "folder"

    maquinas = _get_current_machines(incluir_infra_interna=True)
    master_names_lower = _master_names_lower()

    por_origen: dict[str, list["Maquina"]] = {}
    for m in maquinas:
        por_origen.setdefault(m.origen or "—", []).append(m)

    resultado = {}
    for origen, maqs in por_origen.items():
        con_folder = [m for m in maqs if (getattr(m, campo_ruta) or "").strip()]
        sin_folder = [m for m in maqs if not (getattr(m, campo_ruta) or "").strip()]

        real_tree = None
        if con_folder:
            real_tree = _build_folder_tree([(getattr(m, campo_ruta).strip(), _vm_leaf(m)) for m in con_folder])

        proxy = {}
        masters = [m for m in sin_folder if m.tipo_provisionamiento == "MASTER"]
        templates = [m for m in sin_folder if m.tipo_provisionamiento == "TEMPLATE"]
        vdi_pool = [m for m in sin_folder if m.tipo_provisionamiento == "VDI_POOL"]
        estaticas = [m for m in sin_folder if m.tipo_provisionamiento == "VM_ESTATICA"]
        # Antes: una VM con tipo_provisionamiento vacío/None (o cualquier valor fuera de
        # los 4 conocidos) no caía en ninguna de las 4 listas de arriba y desaparecía del
        # árbol entero, sin aviso -- bug real, corregido 2026-09-07.
        _clasificadas_ids = {m.id for m in masters + templates + vdi_pool + estaticas}
        sin_clasificar = [m for m in sin_folder if m.id not in _clasificadas_ids]

        if masters:
            proxy["Masters"] = {"total": len(masters), "vms": [_vm_leaf(m) for m in masters]}
        if templates:
            proxy["Templates"] = {"total": len(templates), "vms": [_vm_leaf(m) for m in templates]}
        if vdi_pool:
            pools: dict[str, list] = {}
            for m in vdi_pool:
                pools.setdefault(m.pool or "Sin Pool", []).append(m)
            proxy["VDI Pools"] = {
                "total": len(vdi_pool),
                "pools": {
                    p: {"total": len(vms), "vms": [_vm_leaf(m) for m in vms]}
                    for p, vms in sorted(pools.items(), key=lambda x: -len(x[1]))
                },
            }
        if estaticas:
            cats: dict[str, list] = {}
            for m in estaticas:
                codigo = _categoria_estatica_codigo(m.nombre, master_names_lower)
                label = _CATEGORIA_ESTATICA_LABELS.get(codigo, "Estática (sin subcategoría)")
                cats.setdefault(label, []).append(m)
            proxy["VM Estáticas"] = {
                "total": len(estaticas),
                "categorias": {
                    c: {"total": len(vms), "vms": [_vm_leaf(m) for m in vms]}
                    for c, vms in sorted(cats.items(), key=lambda x: -len(x[1]))
                },
            }
        if sin_clasificar:
            proxy["Sin clasificar"] = {"total": len(sin_clasificar), "vms": [_vm_leaf(m) for m in sin_clasificar]}

        resultado[origen] = {
            "total": len(maqs),
            "con_carpeta_real": len(con_folder),
            "real": real_tree,
            "proxy": proxy,
        }

    return jsonify({"vista": vista, "origenes": resultado})


@bp_api.route("/distribucion/estado")
def distribucion_estado():
    maquinas = _get_current_machines(
        tipo=request.args.get("tipo"),
        origen=request.args.get("origen"),
    )
    counts: dict[str, int] = {}
    for m in maquinas:
        k = m.estado_horizon or m.estado_vcenter or "Desconocido"
        counts[k] = counts.get(k, 0) + 1
    counts = dict(sorted(counts.items(), key=lambda x: -x[1]))
    return jsonify({"labels": list(counts.keys()), "data": list(counts.values())})


@bp_api.route("/semaforo")
def semaforo():
    """Datos para widget semáforo de salud. Clasificacion via kpi_utils.clasificar_estado_maquina
    -- unica fuente de verdad, misma que usan /api/kpis y /api/huerfanas (antes cada endpoint
    tenia su propia condicion booleana a mano y podian no coincidir para el mismo dataset)."""
    maquinas = _get_current_machines(
        tipo=request.args.get("tipo"),
        origen=request.args.get("origen"),
    )
    rojas, amarillas, verdes, grises = [], [], [], []
    for m in maquinas:
        est = clasificar_estado_maquina(m)
        if est["en_error"]:
            rojas.append(m)
        elif est["desconectada"] or est["apagada"]:
            amarillas.append(m)
        elif est["conectada"]:
            verdes.append(m)
        elif est["disponible"]:
            grises.append(m)
    return jsonify({
        "rojas": len(rojas), "amarillas": len(amarillas),
        "verdes": len(verdes), "grises": len(grises),
        "detalle_rojas": [m.to_dict() for m in rojas[:20]],
    })


@bp_api.route("/salud/agentes")
def salud_agentes_api():
    """Resumen consolidado de VMware Tools caido y Horizon Agent inalcanzable/error --
    ambos campos ya se guardan por VM (Maquina.tools_status, estado_horizon_agente) pero
    no habia ningun widget que los totalizara, solo aparecian sueltos en el feed de
    Novedades como items individuales."""
    maquinas = _get_current_machines()
    tools_caidos = [m for m in maquinas if (m.tools_status or "").strip().upper() not in ("", "RUNNING")]
    agente_caido = [
        m for m in maquinas
        if any(x in (m.estado_horizon_agente or "").upper() for x in ("UNREACHABLE", "ERROR", "ERR_"))
    ]
    return jsonify({
        "tools_caidos": {
            "count": len(tools_caidos),
            "items": [{"nombre": m.nombre, "pool": m.pool, "tools_status": m.tools_status, "usuario_asignado": m.usuario_asignado} for m in tools_caidos[:30]],
        },
        "agente_caido": {
            "count": len(agente_caido),
            "items": [{"nombre": m.nombre, "pool": m.pool, "estado_horizon_agente": m.estado_horizon_agente, "usuario_asignado": m.usuario_asignado} for m in agente_caido[:30]],
        },
    })


def _huerfana_resumen(m) -> dict:
    """Subconjunto de Maquina.to_dict() realmente consumido por HuerfanasWidget y
    VmListModal (nombre/tipo/origen/pool/empresa/usuario/estado/ip/vcenter_host para el
    link a vCenter) -- antes se exponía to_dict() completo (IPs de cliente/gateway,
    resource_pool, datastores, hardware_version, annotation) a cualquier usuario
    autenticado sin importar su rol (hallazgo de seguridad, corregido 2026-09-07)."""
    return {
        "id": m.id,
        "nombre": m.nombre,
        "tipo": m.tipo if isinstance(m.tipo, str) else m.tipo.value,
        "origen": m.origen,
        "pool": m.pool,
        "empresa": m.empresa,
        "usuario_asignado": m.usuario_asignado or "",
        "estado_horizon": m.estado_horizon or "",
        "estado": m.estado or "",
        "ip": m.ip_principal or "",
        "ip_principal": m.ip_principal or "",
        "vcenter_host": m.vcenter_host or "",
    }


@bp_api.route("/huerfanas")
def huerfanas():
    """VMs disponibles/encendidas sin usuario asignado -- via kpi_utils.es_huerfana,
    misma definicion que /api/kpis y /api/semaforo."""
    maquinas = _get_current_machines(tipo=request.args.get("tipo"))
    result = [_huerfana_resumen(m) for m in maquinas if es_huerfana(m)]
    return jsonify({"count": len(result), "items": result})


@bp_api.route("/disco/criticos")
def disco_criticos():
    """
    VDI/VM con % de disco usado en rango de riesgo (default 80-100%), para detectar
    quedarse sin espacio ANTES de que llegue al 2% libre -- hasta ahora la única señal
    era la alerta de InfraEvento cuando ya estaba casi lleno (ver _chequear_alerta_disco).
    Solo cuenta máquinas con disk_used_gb real (no None) -- la mayoría de la flota
    todavía no tiene ese dato real capturado (ver auditoría de datos fabricados
    2026-08-12), así que el total de "candidatas" siempre va a ser menor a la flota
    completa hasta que corran extracciones con los datos reales.
    """
    from web.appvolumes_utils import writables_para_maquina

    min_pct = float(request.args.get("min_pct", 80))
    max_pct = float(request.args.get("max_pct", 100))

    maquinas = _get_current_machines()
    items = []
    for m in maquinas:
        prov = m.disk_provisioned_gb
        usado = m.disk_used_gb
        if not prov or prov <= 0 or usado is None:
            continue
        pct = round((usado / prov) * 100, 1)
        if min_pct <= pct <= max_pct:
            # Cuánto de ese disco es en realidad Writable Volumes de App Volumes (perfil +
            # datos de usuario) -- pedido 2026-08-13: un usuario con varios writables
            # acumulados (ej. uno de 100GB + varios de 20GB sin desasignar) puede explicar
            # una alerta de disco que a simple vista parece "la VM está pesada", cuando en
            # realidad es basura de perfiles viejos que se puede limpiar sin tocar la VM.
            wv = writables_para_maquina(m)
            items.append({
                "id": m.id,
                "nombre": m.nombre,
                "pool": m.pool,
                "empresa": m.empresa,
                "usuario_asignado": m.usuario_asignado,
                "disk_provisioned_gb": round(prov, 1),
                "disk_used_gb": round(usado, 1),
                "disk_free_gb": round(prov - usado, 1),
                "pct_usado": pct,
                "writables_gb": wv["total_gb"],
                "writables_cantidad": wv["cantidad"],
            })

    items.sort(key=lambda x: x["pct_usado"], reverse=True)

    return jsonify({
        "count": len(items),
        "criticas_90_100": sum(1 for it in items if it["pct_usado"] >= 90),
        "advertencia_80_90": sum(1 for it in items if 80 <= it["pct_usado"] < 90),
        "items": items,
    })


@bp_api.route("/appvolumes/writables_huerfanos")
def appvolumes_writables_huerfanos_api():
    """Write Volumes de App Volumes sin montar en ninguna VM ahora mismo (attached_to
    vacio) o marcados 'orphaned' por el propio App Volumes Manager -- perfiles/datos de
    usuario que siguen ocupando VMDK real en el datastore sin que nadie los este usando.
    Distinto de /appvolumes/huerfanas (esa es la asignacion estatica User/Group/Computer
    de un AppStack de solo lectura; esto es el disco de escritura propio del usuario)."""
    from web.db import AppVolumesWritable

    writables = AppVolumesWritable.query.filter_by(activo=True).all()
    huerfanos = [
        w for w in writables
        if (w.estado or "").strip().lower() == "orphaned" or not (w.attached_to or "").strip()
    ]
    total_gb_desperdiciado = sum((w.size_mb or 0) for w in huerfanos) / 1024

    items = sorted(huerfanos, key=lambda w: -(w.size_mb or 0))[:50]
    # Solo lo que WritablesHuerfanosWidget renderiza -- to_dict() completo exponía
    # datastore_name y attached_to (VM real donde estuvo montado) a cualquier
    # autenticado sin importar su rol (hallazgo de seguridad, corregido 2026-09-07).
    items_resumen = [
        {
            "id": w.id,
            "owner_display_name": w.owner_display_name or w.entity_name or "",
            "entity_name": w.entity_name or "",
            "estado": w.estado or "",
            "size_gb": round(w.size_mb / 1024, 2) if w.size_mb else None,
        }
        for w in items
    ]
    return jsonify({
        "count": len(huerfanos),
        "total_gb_desperdiciado": round(total_gb_desperdiciado, 1),
        "items": items_resumen,
    })


@bp_api.route("/appvolumes/huerfanas")
def appvolumes_huerfanas_api():
    """Asignaciones de App Volumes vivas cuya VM/usuario ya no existe o está inactivo
    en el inventario -- candidatas a depurar manualmente en el Admin UI de App Volumes."""
    from web.appvolumes_utils import asignaciones_huerfanas

    items = asignaciones_huerfanas()
    resumen = {}
    for it in items:
        resumen[it["motivo"]] = resumen.get(it["motivo"], 0) + 1

    return jsonify({"asignaciones": items, "total": len(items), "resumen": resumen})


@bp_api.route("/appvolumes/huerfanas/verificar_ad", methods=["POST"])
def appvolumes_huerfanas_verificar_ad_api():
    """Toma los usernames de App Volumes 'no encontrados' localmente (motivo=
    usuario_no_encontrado) y los consulta contra AD real -- AD real puede tener el
    logon name y el sAMAccountName (pre-Windows 2000) como strings distintos, así que
    un usuario puede existir de verdad aunque no matchee username por string exacto.
    Si aparece en AD, se registra en DirectorioUsuario (con sam_account_name aparte)
    y deja de contar como huérfano en la próxima consulta de /appvolumes/huerfanas."""
    from web.appvolumes_utils import usuarios_no_resueltos
    from web.db import get_or_create_directorio_usuario
    from core.ad_client import ADClient

    usernames = usuarios_no_resueltos()
    if not usernames:
        return jsonify({"ok": True, "verificados": 0, "encontrados": 0, "mensaje": "Nada para verificar."})

    ad = ADClient(domain=os.environ.get("AD_DOMAIN", "corp.local"))
    res_ad = ad.verificar_usuarios(usernames)

    encontrados = 0
    for username in usernames:
        info = res_ad.get(username.lower())
        if not info or not info.get("encontrado_ad"):
            continue
        encontrados += 1

        u = get_or_create_directorio_usuario(
            username, empresa=info.get("empresa"), nombre_completo=info.get("nombre_completo")
        )
        if not u:
            continue
        u.activo_ad = info.get("activo_ad", True)
        if info.get("email") and not u.email:
            u.email = info["email"]
        if info.get("departamento") and not u.departamento:
            u.departamento = info["departamento"]
        if info.get("telefono") and not u.telefono:
            u.telefono = info["telefono"]
        if info.get("sam_account_name") and u.sam_account_name != info["sam_account_name"]:
            u.sam_account_name = info["sam_account_name"]

    registrar_auditoria(
        accion="verificar_ad_appvolumes_huerfanas",
        detalle=f"consultados={len(usernames)}, encontrados={encontrados}",
        usuario_id=session.get("user_id"),
        username=session.get("username"),
        ip=request.remote_addr,
    )
    db.session.commit()
    return jsonify({"ok": True, "verificados": len(usernames), "encontrados": encontrados})


@bp_api.route("/novedades")
def novedades_api():
    """
    Widget y Vista de Novedades y Eventos Detectados:
    - VMs nuevas detectadas (distingue entre VM nueva creada vs primer login)
    - Inicios nuevos de sesión (Logins)
    - Logouts detectados
    - VMs eliminadas / dadas de baja
    """
    from datetime import datetime, timedelta
    from web.db import VMTareaEvento

    ver_todo = request.args.get("todo") == "1"

    historial_q = MaquinaHistorial.query
    if not ver_todo:
        historial_q = historial_q.filter(MaquinaHistorial.campo_modificado.in_(TIPOS_EVENTO_IMPORTANTES))
    historial = (
        historial_q
        .order_by(MaquinaHistorial.detectado_en.desc())
        .limit(300)
        .all()
    )

    rotaciones = (
        HistorialUsuarioVDI.query
        .order_by(HistorialUsuarioVDI.detectado_en.desc())
        .limit(150)
        .all()
    )

    # eventos_vcenter en dos partes -- ventana general (300 mas recientes, cualquier tipo)
    # MAS una busqueda aparte de clonacion/creacion/baja SIN el limite de fecha (100).
    # Antes un solo query "ultimos 300 por fecha" hacia que ruido de alta frecuencia
    # (AlarmStatusChangedEvent, VmReconfiguredEvent, TaskEvent -- miles de filas) sacara
    # de la ventana a un VmClonedEvent de hace unos dias, aunque tuviera usuario real
    # asociado (confirmado contra datos reales 2026-09-02: eventos de clonacion con
    # usuario de cuenta de servicio de Instant Clone existian en la DB pero nunca
    # llegaban a mostrarse porque quedaban fuera del top 300 por volumen de ruido).
    _EVENTOS_VCENTER_RELEVANTES = ("clone", "create", "deploy", "destroy", "removed", "delete")
    eventos_vcenter = (
        VMTareaEvento.query
        .order_by(VMTareaEvento.fecha.desc())
        .limit(300)
        .all()
    )
    _ids_vcenter_ya = {ev.id for ev in eventos_vcenter}
    _cond_relevante = db.or_(*[VMTareaEvento.nombre_evento.ilike(f"%{kw}%") for kw in _EVENTOS_VCENTER_RELEVANTES])
    _q_relevantes = VMTareaEvento.query.filter(_cond_relevante)
    if _ids_vcenter_ya:
        _q_relevantes = _q_relevantes.filter(~VMTareaEvento.id.in_(_ids_vcenter_ya))
    eventos_vcenter += _q_relevantes.order_by(VMTareaEvento.fecha.desc()).limit(100).all()

    infra_eventos = (
        InfraEvento.query
        .order_by(InfraEvento.detectado_en.desc())
        .limit(150)
        .all()
    )
    servidores_por_id = {s.id: s.nombre for s in Servidor.query.all()}

    # Palabras clave de eventos de seguridad/autenticacion dentro del audit-trail crudo de
    # Horizon (bloqueos SSO, login fallido) -- confirmado 2026-09-02 contra InfraEvento
    # reales: docenas de "SSO credentials locked for user X" y "failed to authenticate"
    # estaban categorizados como "alerta" igual que datastore critico/host caido. Son
    # eventos de seguridad/acceso, categoria distinta de una alerta operacional de infra.
    _SEGURIDAD_KEYWORDS = (
        "credentials locked", "failed to authenticate", "failed to login",
        "bad username or password", "account locked", "account disabled", "locked out",
    )

    vms_nuevas = []
    logins = []
    logouts = []
    eliminadas = []
    cambios_infra = []
    alertas = []
    seguridad = []
    auditoria = []
    todos = []
    seen_keys = set()

    for ie in infra_eventos:
        dt_str = ie.detectado_en.strftime("%d/%m %H:%M") if ie.detectado_en else ""
        dt_raw = ie.detectado_en or datetime.min
        srv_nombre = servidores_por_id.get(ie.servidor_id, "—")

        if ie.tipo == "datastore_critico":
            try:
                pct = float((ie.valor_nuevo or "0%").rstrip("%"))
            except ValueError:
                pct = 0
            es_critico = pct >= 90
            badge, color = ("DATASTORE CRÍTICO", "rose") if es_critico else ("DATASTORE OK", "emerald")
            titulo = f"{'💾🛑' if es_critico else '✅'} Datastore {'crítico' if es_critico else 'recuperado'}: {ie.entidad_nombre}"
        elif ie.tipo == "host_desconectado":
            badge, color, titulo = "HOST CAÍDO", "rose", f"🛑 Host desconectado: {ie.entidad_nombre}"
        elif ie.tipo == "host_reconectado":
            badge, color, titulo = "HOST OK", "emerald", f"✅ Host reconectado: {ie.entidad_nombre}"
        elif ie.tipo == "pool_provisioning_error":
            badge, color, titulo = "POOL CON ERROR", "rose", f"🛑 Error de provisioning en pool: {ie.entidad_nombre}"
        elif ie.tipo == "pool_provisioning_resuelto":
            badge, color, titulo = "POOL OK", "emerald", f"✅ Pool recuperado: {ie.entidad_nombre}"
        elif ie.tipo == "pool_eliminado":
            badge, color, titulo = "POOL ELIMINADA", "rose", f"🔴 Pool eliminada: {ie.entidad_nombre}"
        elif ie.tipo == "horizon_audit":
            msg_lower = (ie.mensaje or "").lower()
            if any(k in msg_lower for k in _SEGURIDAD_KEYWORDS):
                badge, color = "BLOQUEO/AUTENTICACIÓN", "rose"
                titulo = f"🔒 {ie.mensaje}" if ie.mensaje else f"🔒 Evento de seguridad: {ie.entidad_nombre}"
            else:
                badge, color = "AUDITORÍA", "indigo"
                titulo = f"📋 {ie.mensaje}" if ie.mensaje else f"📋 Auditoría Horizon: {ie.entidad_nombre}"
        else:
            badge, color, titulo = ie.tipo.upper(), "amber", f"⚠️ {ie.tipo}: {ie.entidad_nombre}"

        item = {
            "tipo": f"alerta_{ie.tipo}",
            "titulo": titulo,
            "nombre_vm": ie.entidad_nombre,
            "servidor": srv_nombre,
            "origen": "",
            "usuario": "—",
            "pool": "",
            "primera_deteccion": "",
            "detalle": ie.mensaje or f"{ie.valor_anterior or '—'} ➔ {ie.valor_nuevo or '—'}",
            "fecha": dt_str,
            "raw_date": dt_raw,
            "badge": badge,
            "color": color,
        }
        # horizon_audit se separa en Seguridad (bloqueos/login fallido) o Auditoria
        # (resto del audit-trail: entitlements, logoffs admin, publish de imagen) --
        # ninguna de las dos es una "alerta" operacional de infraestructura.
        if ie.tipo == "horizon_audit":
            item["tipo"] = "seguridad" if badge == "BLOQUEO/AUTENTICACIÓN" else "auditoria"
            (seguridad if badge == "BLOQUEO/AUTENTICACIÓN" else auditoria).append(item)
        else:
            alertas.append(item)
        todos.append(item)

    # 1. Eventos en vivo de vCenter/Horizon (VMTareaEvento)
    for ev in eventos_vcenter:
        m = Maquina.query.get(ev.maquina_id) if ev.maquina_id else None
        m_nombre = m.nombre if m else "VM"
        srv_nombre = m.servidor.nombre if (m and m.servidor) else (m.origen if (m and m.origen) else ("Horizon DT" if (m and m.tipo == "VDI") else "vCenter"))
        origen_str = m.origen if m else "vCenter"
        user_str = ev.usuario or (m.usuario_asignado if m else "System")
        pool_str = m.pool if m else ""
        primera_det = m.primera_deteccion.strftime("%d/%m/%Y %H:%M") if (m and m.primera_deteccion) else ""
        dt_str = ev.fecha.strftime("%d/%m %H:%M") if ev.fecha else ""

        evt_lower = (ev.nombre_evento or "").lower()
        msg_lower = (ev.mensaje or "").lower()
        full_text = f"{evt_lower} {msg_lower}"

        dedup_key = (m_nombre, evt_lower, dt_str)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        if any(x in full_text for x in ("login", "connected", "sessionstarted", "user logged in")):
            t_tipo = "login"
            badge = "LOGIN"
            color = "indigo"
            titulo = f"🟢 Inicio de Sesión: {m_nombre}"
        elif any(x in full_text for x in ("logout", "disconnected", "sessionended", "user logged off", "guest shutdown")):
            t_tipo = "logout"
            badge = "LOGOUT"
            color = "amber"
            titulo = f"🟡 Cierre / Desconexión Sesión: {m_nombre}"
        elif any(x in full_text for x in ("poweron", "poweredon", "power on", "powering on")):
            t_tipo = "energia"
            badge = "POWER ON"
            color = "emerald"
            titulo = f"⚡ Encendido de VM: {m_nombre}"
        elif any(x in full_text for x in ("poweroff", "poweredoff", "power off", "powering off")):
            t_tipo = "energia"
            badge = "POWER OFF"
            color = "rose"
            titulo = f"🔴 Apagado de VM: {m_nombre}"
        elif any(x in full_text for x in ("reconfig", "reconfigure", "modified")):
            t_tipo = "cambio_infra"
            badge = "RECONFIGURACIÓN"
            color = "sky"
            titulo = f"⚙️ Reconfiguración de Hardware: {m_nombre}"
        elif any(x in full_text for x in ("clone", "cloned", "cloning", "created", "create virtual machine")):
            t_tipo = "creacion"
            badge = "CLONACIÓN"
            color = "emerald"
            titulo = f"🆕 VM Clonada / Creada: {m_nombre}"
        else:
            t_tipo = "vcenter_event"
            badge = ev.nombre_evento[:18].upper()
            color = "rose" if ev.estado == "error" else ("amber" if ev.estado == "warning" else "indigo")
            titulo = f"📋 Evento: {ev.nombre_evento} ({m_nombre})"

        item = {
            "tipo": t_tipo,
            "titulo": titulo,
            "nombre_vm": m_nombre,
            "servidor": srv_nombre,
            "origen": origen_str,
            "usuario": user_str,
            "pool": pool_str,
            "primera_deteccion": primera_det,
            "es_nueva_real": False,
            "detalle": f"{ev.mensaje or ev.nombre_evento} | Usuario: {user_str}",
            "fecha": dt_str,
            "raw_date": ev.fecha or datetime.min,
            "badge": badge,
            "color": color,
        }
        if t_tipo == "login":
            logins.append(item)
        elif t_tipo == "logout":
            logouts.append(item)
        elif t_tipo == "creacion":
            vms_nuevas.append(item)
        elif t_tipo == "cambio_infra" or t_tipo == "energia":
            cambios_infra.append(item)

        todos.append(item)

    for h in historial:
        m = h.maquina
        m_nombre = m.nombre if m else "VM"
        srv_nombre = m.servidor.nombre if (m and m.servidor) else (m.origen if (m and m.origen) else ("Horizon DT" if (m and m.tipo == "VDI") else "vCenter"))
        origen_str = m.origen if m else ""
        user_str = m.usuario_asignado if m else ""
        pool_str = m.pool if m else ""
        primera_det = m.primera_deteccion.strftime("%d/%m/%Y %H:%M") if (m and m.primera_deteccion) else ""
        dt_str = h.detectado_en.strftime("%d/%m %H:%M") if h.detectado_en else ""
        dt_raw = h.detectado_en or datetime.min

        # Determinar si es VM creada verdaderamente hoy/reciente (primera detección < 48hs desde ahora y respecto al evento)
        es_reciente = False
        if m and m.primera_deteccion and h.detectado_en:
            diff_sec = abs((h.detectado_en - m.primera_deteccion).total_seconds())
            diff_now = abs((datetime.utcnow() - m.primera_deteccion).total_seconds())
            if diff_sec < 86400 * 2 and diff_now < 86400 * 2:
                es_reciente = True

        if h.campo_modificado == "creacion":
            # Atribucion real: MaquinaHistorial "creacion" nunca tuvo actor (solo marca
            # "vista por primera vez"). Si vCenter reporto un VmClonedEvent/VmCreatedEvent
            # para esta misma maquina (VMTareaEvento.usuario, cuando vCenter lo informa),
            # usar ese usuario real en vez de usuario_asignado (que es la sesion Horizon
            # activa, no quien creo la VM). Confirmado 2026-09-02: estos eventos existen
            # en la DB real con usuario de cuenta de servicio o admin, solo no se cruzaban.
            usuario_creacion = None
            if m:
                ev_creacion = (
                    VMTareaEvento.query
                    .filter(VMTareaEvento.maquina_id == m.id)
                    .filter(db.or_(VMTareaEvento.nombre_evento.ilike("%clone%"), VMTareaEvento.nombre_evento.ilike("%create%")))
                    .filter(VMTareaEvento.usuario != None, VMTareaEvento.usuario != "")
                    .order_by(VMTareaEvento.fecha.desc())
                    .first()
                )
                if ev_creacion:
                    usuario_creacion = ev_creacion.usuario
            item = {
                "tipo": "creacion",
                "titulo": f"🆕 VM Nueva Creada: {m_nombre}" if es_reciente else f"ℹ️ VM Existente: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": usuario_creacion or user_str or "No identificado (sin evento de clonación vCenter)",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "es_nueva_real": es_reciente,
                "detalle": h.valor_nuevo or ("VM recién creada" if es_reciente else f"VM en inventario (Alta original: {primera_det})"),
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "NUEVA" if es_reciente else "EXISTENTE",
                "color": "emerald" if es_reciente else "indigo",
            }
            if es_reciente:
                vms_nuevas.append(item)
            todos.append(item)
        elif h.campo_modificado == "eliminacion":
            usuario_eliminacion = None
            if m:
                ev_elim = (
                    VMTareaEvento.query
                    .filter(VMTareaEvento.maquina_id == m.id)
                    .filter(db.or_(VMTareaEvento.nombre_evento.ilike("%destroy%"), VMTareaEvento.nombre_evento.ilike("%remove%"), VMTareaEvento.nombre_evento.ilike("%delete%")))
                    .filter(VMTareaEvento.usuario != None, VMTareaEvento.usuario != "")
                    .order_by(VMTareaEvento.fecha.desc())
                    .first()
                )
                if ev_elim:
                    usuario_eliminacion = ev_elim.usuario
            item = {
                "tipo": "eliminacion",
                "titulo": f"🔴 VM Dada de Baja / Inactiva: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": usuario_eliminacion or user_str or "No identificado (sin evento de baja vCenter)",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": h.valor_nuevo or "VM eliminada o fuera de servicio",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "ELIMINADA",
                "color": "rose",
            }
            eliminadas.append(item)
            todos.append(item)
        elif h.campo_modificado == "estado_horizon":
            val_ant = (h.valor_anterior or "").upper()
            val_nue = (h.valor_nuevo or "").upper()
            if val_nue == "CONNECTED":
                item = {
                    "tipo": "login",
                    "titulo": f"🟢 Inicio de Sesión: {m_nombre}",
                    "nombre_vm": m_nombre,
                    "servidor": srv_nombre,
                    "origen": origen_str,
                    "usuario": user_str or "Sin usuario asignado",
                    "pool": pool_str,
                    "primera_deteccion": primera_det,
                    "es_nueva_real": es_reciente,
                    "detalle": f"Usuario: {user_str or 'N/D'} | Estado cambió a CONNECTED (previo: {h.valor_anterior or '—'})",
                    "fecha": dt_str,
                    "raw_date": dt_raw,
                    "badge": "LOGIN",
                    "color": "indigo",
                }
                logins.append(item)
                todos.append(item)
            elif ("CONNECTED" in val_ant or "ACTIVE" in val_ant or "DISCONNECTED" in val_ant) and any(x in val_nue for x in ("DISCONNECTED", "AVAILABLE", "UNREACHABLE", "LOGGED_OFF")):
                txt_ant = h.valor_anterior or 'CONNECTED'
                txt_nue = h.valor_nuevo or 'DESCONECTADO'
                item = {
                    "tipo": "logout",
                    "titulo": f"🟡 Logout / Desconexión: {m_nombre}",
                    "nombre_vm": m_nombre,
                    "servidor": srv_nombre,
                    "origen": origen_str,
                    "usuario": user_str or "—",
                    "pool": pool_str,
                    "primera_deteccion": primera_det,
                    "detalle": f"Estado de sesión cambió de '{txt_ant}' a '{txt_nue}'",
                    "fecha": dt_str,
                    "raw_date": dt_raw,
                    "badge": "LOGOUT",
                    "color": "amber",
                }
                logouts.append(item)
                todos.append(item)
        elif h.campo_modificado == "migracion":
            item = {
                "tipo": "migracion",
                "titulo": f"🔄 VM Migrada de Servidor: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "es_nueva_real": False,
                "detalle": f"{h.valor_nuevo} (Anterior: {h.valor_anterior or 'Desconocido'})",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "MIGRACIÓN",
                "color": "amber",
            }
            cambios_infra.append(item)
            todos.append(item)
        elif h.campo_modificado in ("vcenter_host", "datastores", "folder", "resource_pool"):
            item = {
                "tipo": "cambio_host",
                "titulo": f"⚙️ Cambio de Host/Datastore: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "es_nueva_real": False,
                "detalle": f"Propiedad '{h.campo_modificado}' cambió: '{h.valor_anterior or '—'}' ➔ '{h.valor_nuevo or '—'}'",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "CAMBIO INFRA",
                "color": "sky",
            }
            cambios_infra.append(item)
            todos.append(item)
        elif h.campo_modificado == "so":
            item = {
                "tipo": "cambio_so",
                "titulo": f"💻 Cambio de Sistema Operativo: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": f"SO cambió de '{h.valor_anterior or '—'}' a '{h.valor_nuevo}'",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "CAMBIO SO",
                "color": "cyan",
            }
            cambios_infra.append(item)
            todos.append(item)
        elif h.campo_modificado == "pool":
            item = {
                "tipo": "cambio_pool",
                "titulo": f"🏊 Reasignación de Pool: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": h.valor_nuevo or pool_str,
                "primera_deteccion": primera_det,
                "detalle": f"Pool cambió de '{h.valor_anterior or 'Estática'}' a '{h.valor_nuevo}'",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "CAMBIO POOL",
                "color": "purple",
            }
            cambios_infra.append(item)
            todos.append(item)
        elif h.campo_modificado == "usuario_asignado":
            item = {
                "tipo": "cambio_usuario",
                "titulo": f"👤 Reasignación de Usuario: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": h.valor_nuevo or "Sin asignar",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": f"Usuario cambió de '{h.valor_anterior or 'Sin asignar'}' a '{h.valor_nuevo or 'Sin asignar'}'",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "CAMBIO USUARIO",
                "color": "blue",
            }
            todos.append(item)
        elif h.campo_modificado == "estado_vcenter":
            item = {
                "tipo": "estado_vcenter",
                "titulo": f"⚡ Estado Energía vCenter: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": f"Estado energía cambió: '{h.valor_anterior or '—'}' ➔ '{h.valor_nuevo}'",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "ENERGÍA",
                "color": "teal",
            }
            todos.append(item)
        elif h.campo_modificado == "tools_status":
            es_problema = (h.valor_nuevo or "").upper() != "RUNNING"
            item = {
                "tipo": "alerta_tools",
                "titulo": f"{'🛑' if es_problema else '✅'} VMware Tools {'dejó de correr' if es_problema else 'recuperado'}: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": f"VMware Tools: '{h.valor_anterior or '—'}' ➔ '{h.valor_nuevo or '—'}'",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "TOOLS CAÍDO" if es_problema else "TOOLS OK",
                "color": "rose" if es_problema else "emerald",
            }
            alertas.append(item)
            todos.append(item)
        elif h.campo_modificado == "estado_horizon_agente":
            es_problema = any(x in (h.valor_nuevo or "").upper() for x in ("UNREACHABLE", "ERROR", "ERR_"))
            item = {
                "tipo": "alerta_agente",
                "titulo": f"{'🛑' if es_problema else '✅'} Horizon Agent {'inalcanzable/error' if es_problema else 'recuperado'}: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": f"Estado Agente: '{h.valor_anterior or '—'}' ➔ '{h.valor_nuevo or '—'}'",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "AGENTE CAÍDO" if es_problema else "AGENTE OK",
                "color": "rose" if es_problema else "emerald",
            }
            alertas.append(item)
            todos.append(item)
        elif h.campo_modificado == "in_error_state":
            es_problema = (h.valor_nuevo or "").strip().lower() in ("true", "1")
            item = {
                "tipo": "alerta_error",
                "titulo": f"{'🛑' if es_problema else '✅'} VM {'entró en error' if es_problema else 'salió de error'}: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": "La VM está en estado de error en vCenter." if es_problema else "La VM salió del estado de error.",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "EN ERROR" if es_problema else "ERROR RESUELTO",
                "color": "rose" if es_problema else "emerald",
            }
            alertas.append(item)
            todos.append(item)
        elif h.campo_modificado == "maintenance_mode":
            es_mant = (h.valor_nuevo or "").strip().lower() in ("true", "1")
            item = {
                "tipo": "alerta_mantenimiento",
                "titulo": f"{'🔧' if es_mant else '✅'} VM {'entró en' if es_mant else 'salió de'} mantenimiento: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": "La VM entró en modo mantenimiento." if es_mant else "La VM salió de modo mantenimiento.",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "EN MANTENIMIENTO" if es_mant else "MANTENIMIENTO FIN",
                "color": "amber" if es_mant else "emerald",
            }
            alertas.append(item)
            todos.append(item)
        elif h.campo_modificado == "disco_critico":
            try:
                pct_nuevo = float((h.valor_nuevo or "0%").rstrip("%"))
            except ValueError:
                pct_nuevo = 0
            es_critico = pct_nuevo >= 90
            item = {
                "tipo": "alerta_disco",
                "titulo": f"{'💾🛑' if es_critico else '✅'} Disco {'crítico' if es_critico else 'recuperado'}: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": f"Uso de disco: {h.valor_anterior or '—'} ➔ {h.valor_nuevo}",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "DISCO CRÍTICO" if es_critico else "DISCO OK",
                "color": "rose" if es_critico else "emerald",
            }
            alertas.append(item)
            todos.append(item)
        elif h.campo_modificado == "snapshot_id":
            item = {
                "tipo": "snapshot",
                "titulo": f"📸 Actualización de Snapshot: {m_nombre}",
                "nombre_vm": m_nombre,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": user_str or "—",
                "pool": pool_str,
                "primera_deteccion": primera_det,
                "detalle": f"Sincronizada en Snapshot #{h.valor_nuevo}",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "SNAPSHOT",
                "color": "indigo",
            }
            todos.append(item)

    for r in rotaciones:
        dt_str = r.detectado_en.strftime("%d/%m %H:%M") if r.detectado_en else ""
        dt_raw = r.detectado_en or datetime.min
        m = Maquina.query.get(r.maquina_id) if r.maquina_id else None
        srv_nombre = m.servidor.nombre if (m and m.servidor) else (m.origen if (m and m.origen) else ("Horizon DT" if (m and m.tipo == "VDI") else "vCenter"))
        origen_str = m.origen if m else ""
        primera_det = m.primera_deteccion.strftime("%d/%m/%Y %H:%M") if (m and m.primera_deteccion) else ""

        if r.usuario_nuevo and not r.usuario_anterior:
            item = {
                "tipo": "login",
                "titulo": f"🟢 Sesión Iniciada: {r.nombre_vm}",
                "nombre_vm": r.nombre_vm,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": r.usuario_nuevo,
                "pool": r.pool or "",
                "primera_deteccion": primera_det,
                "detalle": f"Usuario ingresó a VM: {r.usuario_nuevo}",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "LOGIN",
                "color": "indigo",
            }
            logins.append(item)
            todos.append(item)
        elif r.usuario_anterior and not r.usuario_nuevo:
            item = {
                "tipo": "logout",
                "titulo": f"🟡 Cierre de Sesión: {r.nombre_vm}",
                "nombre_vm": r.nombre_vm,
                "servidor": srv_nombre,
                "origen": origen_str,
                "usuario": r.usuario_anterior,
                "pool": r.pool or "",
                "primera_deteccion": primera_det,
                "detalle": f"Usuario anterior: {r.usuario_anterior}",
                "fecha": dt_str,
                "raw_date": dt_raw,
                "badge": "LOGOUT",
                "color": "amber",
            }
            logouts.append(item)
            todos.append(item)

    # Ordenar cronológicamente todo el feed por fecha descendente
    todos.sort(key=lambda x: x.get("raw_date") or datetime.min, reverse=True)

    # Stats "en vivo" -- antes vivian en /api/eventos_realtime, un endpoint aparte que
    # duplicaba ~400 lineas de esta misma clasificacion (mismas 4 tablas de origen).
    # Se fusiona todo en un solo endpoint/widget (2026-09-02).
    now = datetime.utcnow()
    hace_1h = now - timedelta(hours=1)
    total_ultimahora = sum(1 for x in todos if isinstance(x.get("raw_date"), datetime) and x["raw_date"] >= hace_1h)
    ultimo_raw = todos[0]["raw_date"] if todos else None
    ultimo_hace_seg = int((now - ultimo_raw).total_seconds()) if isinstance(ultimo_raw, datetime) else None

    def _hace_str(seg):
        if seg is None:
            return "—"
        if seg < 60:
            return f"hace {seg}s"
        if seg < 3600:
            return f"hace {seg // 60}m"
        if seg < 86400:
            return f"hace {seg // 3600}h"
        return f"hace {seg // 86400}d"

    return jsonify({
        "kpis": {
            "vms_nuevas": len(vms_nuevas),
            "inicios_sesion": len(logins),
            "logouts": len(logouts),
            "vms_eliminadas": len(eliminadas),
            "cambios_infra": len(cambios_infra),
            "alertas": len(alertas),
            "seguridad": len(seguridad),
            "auditoria": len(auditoria),
        },
        "vms_nuevas": vms_nuevas[:50],
        "inicios_sesion": logins[:50],
        "logouts": logouts[:50],
        "vms_eliminadas": eliminadas[:50],
        "cambios_infra": cambios_infra[:50],
        "alertas": alertas[:50],
        "seguridad": seguridad[:50],
        "auditoria": auditoria[:50],
        "eventos_recientes": todos[:100],
        "todos": todos[:250],
        "stats_vivo": {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "total_eventos": len(todos),
            "total_ultimahora": total_ultimahora,
            "eventos_por_minuto": round(total_ultimahora / 60.0, 2),
            "ultimo_evento_hace_seg": ultimo_hace_seg,
            "ultimo_evento_hace_str": _hace_str(ultimo_hace_seg),
        },
    })


@bp_api.route("/snapshots")
def snapshots():
    snaps = (
        InventarioSnapshot.query
        .order_by(InventarioSnapshot.timestamp.desc())
        .limit(50)
        .all()
    )
    return jsonify([s.to_dict() for s in snaps])


# Prefijos de VMs internas de vSphere/Horizon (agentes/artefactos de plataforma, NO
# inventario de usuario/negocio) -- confirmado 2026-09-03: vCLS-* son agentes de vSphere
# Cluster Services (DRS), cp-parent-/cp-replica-/cp-template-* son VMs intermedias del
# proceso de clonado Instant Clone. 105 de 1068 maquinas activas (9.8%) caian como
# VM_ESTATICA normal antes de este fix, inflando el conteo real.
_PREFIJOS_INFRA_INTERNA = ("vcls-", "cp-parent-", "cp-replica-", "cp-template-")


@bp_api.route("/filtros/valores_distintos")
def filtros_valores_distintos_api():
    """Valores reales distintos hoy en la DB para los campos de filtro 'enum' que se
    completan desde Horizon/vCenter -- el picker (COLUMN_DEFINITIONS en
    SmartFilterToolbar.jsx) antes tenia estas opciones hardcodeadas y se desincronizaban de
    lo que la extracción realmente guarda. Bugs reales encontrados en la auditoría 2026-09-04:
    'estado_vcenter' ofrecía 'PoweredOn'/'PoweredOff'/'Suspended' pero la DB guarda
    'POWERED_ON'/'POWERED_OFF' (con guion bajo) -- el filtro daba 0 resultados siempre, en
    silencio (mismo patrón que otros filtros silenciosos ya corregidos este proyecto);
    'estado_horizon' solo ofrecía 4 valores de 8 reales (ALREADY_USED/DELETING/ERROR/
    MAINTENANCE/PROVISIONING_ERROR eran imposibles de buscar); 'tipo_provisionamiento'
    ofrecía TEMPLATE, que nunca está poblado hoy. Extendido 2026-09-04 (2da vuelta, a pedido
    del usuario tras reiniciar y notar que categoria_estatica -- RPA/Infraestructura
    Interna/etc, un badge calculado, no una columna -- seguía con su propia lista
    hardcodeada separada): ahora también cubre categoria_estatica y persistencia (calculados
    recorriendo las máquinas activas, misma función que arma el badge) y otros 3 campos de
    vocabulario fijo que Horizon/vCenter reportan (antes buscables solo como texto libre)."""
    campos_columna_simple = ["tipo", "tipo_provisionamiento", "estado_horizon", "estado_vcenter",
                              "estado_horizon_agente", "tools_status", "connection_state"]

    def _compute():
        resultado = {}
        for campo in campos_columna_simple:
            col = getattr(Maquina, campo)
            rows = (
                Maquina.query.filter(Maquina.activo == True, col.isnot(None), col != "")
                .with_entities(col).distinct().all()
            )
            resultado[campo] = sorted(r[0] for r in rows)
        rows_origen = (
            Maquina.query.filter(Maquina.activo == True, Maquina._origen_str.isnot(None), Maquina._origen_str != "")
            .with_entities(Maquina._origen_str).distinct().all()
        )
        resultado["origen"] = sorted(r[0] for r in rows_origen)

        # categoria_estatica y persistencia son propiedades calculadas (badge), no columnas
        # -- se recorren las máquinas relevantes con la MISMA función/property que usa el
        # badge real, para que el picker jamás pueda desincronizarse de lo que se ve en pantalla.
        master_names = _master_names_lower()
        estaticas = Maquina.query.filter_by(activo=True, tipo_provisionamiento="VM_ESTATICA").all()
        codigos = {_categoria_estatica_codigo(m.nombre, master_names) for m in estaticas}
        resultado["categoria_estatica"] = sorted(c for c in codigos if c)

        segmentos = {_TP_A_SEGMENTO[tp] for tp in resultado["tipo_provisionamiento"] if tp in _TP_A_SEGMENTO}
        segmentos |= {c for c in codigos if c}
        if "" in codigos:
            segmentos.add("estatica")
        resultado["segmentacion"] = sorted(segmentos)

        persistentes = Maquina.query.filter(
            Maquina.activo == True, Maquina.tipo_provisionamiento.in_(["VDI_POOL", "VM_ESTATICA"])
        ).all()
        valores_persistencia = {m.persistencia for m in persistentes}
        resultado["persistencia"] = sorted(v for v in valores_persistencia if v)

        return resultado

    return jsonify(cache_get_or_set("filtros:valores_distintos", 120, _compute))


def _categoria_infra_interna(nombre: str) -> str:
    n = (nombre or "").lower()
    if n.startswith("vcls-"): return "vcls"
    if n.startswith("cp-parent-"): return "cp_parent"
    if n.startswith("cp-replica-"): return "cp_replica"
    if n.startswith("cp-template-"): return "cp_template"
    return "otro"


def _master_names_lower() -> set[str]:
    return {m.nombre.lower() for m in Maquina.query.filter_by(tipo_provisionamiento="MASTER").all()}


def _categoria_estatica_codigo(nombre: str, master_names_lower: set[str]) -> str:
    """Código corto (matchea _cond_categoria_estatica y las opciones del filtro) de la
    sub-categoría de una VM_ESTATICA -- única fuente de verdad, antes duplicada entre acá
    y el badge de maquinas_api() (auditoría de filtros 2026-09-04: el picker de filtros
    tenía sus propias 4 opciones hardcodeadas por separado, podían desincronizarse de esta
    lógica igual que pasó con estado_vcenter)."""
    n = (nombre or "")
    if n.lower().startswith(_PREFIJOS_INFRA_INTERNA):
        return "infra"
    if "rpa" in n.lower():
        return "rpa"
    if n.lower() in master_names_lower:
        return "copia"
    if n.lower().startswith("vdi-"):
        return "huerfana"
    return ""


_CATEGORIA_ESTATICA_LABELS = {
    "infra": "Infraestructura Interna",
    "rpa": "RPA",
    "copia": "Copia (no activa)",
    "huerfana": "VDI Huérfana (sin pool Horizon)",
}

_TP_A_SEGMENTO = {"MASTER": "master", "TEMPLATE": "template", "VDI_POOL": "vdi_pool"}

# Etiquetas EXACTAS que ya usa getSegmentacionBadge() en InventarioPage.jsx -- "Segmentación"
# es lo que el usuario ve como UN solo concepto en la tabla (7 valores), aunque en la DB sea
# 2 campos separados (tipo_provisionamiento + categoria_estatica). Antes el filtro de
# "Segmentación" solo ofrecía los 3 valores crudos de tipo_provisionamiento (MASTER/VDI_POOL/
# VM_ESTATICA) -- RPA/Infra Interna/Copia/Huérfana, que sí se ven en la columna, no se podían
# buscar bajo ese nombre (auditoría de filtros 2026-09-04, 3ra vuelta). Este campo virtual
# "segmentacion" unifica los 7 en un solo filtro fiel a lo que se ve en pantalla.
_SEGMENTACION_LABELS = {
    "master": "MASTER", "template": "PLANTILLA", "vdi_pool": "VDI POOL", "estatica": "ESTÁTICA",
    "infra": "INFRA INTERNA", "rpa": "RPA", "copia": "COPIA (VIEJA)", "huerfana": "VDI HUÉRFANA",
}


def _segmentacion_codigo(tipo_prov: str, nombre: str, master_names_lower: set[str]) -> str:
    if tipo_prov == "VM_ESTATICA":
        return _categoria_estatica_codigo(nombre, master_names_lower) or "estatica"
    return _TP_A_SEGMENTO.get(tipo_prov, "")


@bp_api.route("/infraestructura/consumo_interno")
def infraestructura_consumo_interno_api():
    """Consumo real (CPU/RAM/Disco) de las VMs de plataforma excluidas del conteo de
    negocio: vCLS-* (agentes vSphere Cluster Services/DRS) y cp-parent/replica/template-*
    (VMs intermedias de Instant Clone) -- ver _PREFIJOS_INFRA_INTERNA y su exclusion en
    _get_current_machines. Invisibles para los KPIs de VDI/VM pero con costo de
    infraestructura real que hay que poder seguir (auditoria 2026-09-04): cp-replica y
    cp-template quedan siempre apagadas (0 CPU/RAM, solo ocupan datastore); cp-parent y
    vCLS pueden estar encendidas y sí consumen CPU/RAM real del host."""
    rows = Maquina.query.filter_by(activo=True, tipo_provisionamiento="VM_ESTATICA").filter(
        db.or_(*[Maquina.nombre.ilike(f"{p}%") for p in _PREFIJOS_INFRA_INTERNA])
    ).all()

    def _bucket_vacio():
        return {"count": 0, "encendidas": 0, "cpu_vcpus": 0, "ram_gb": 0.0, "disco_gb": 0.0}

    total = _bucket_vacio()
    por_categoria: dict[str, dict] = {}
    por_origen: dict[str, dict] = {}

    for m in rows:
        cat = _categoria_infra_interna(m.nombre)
        origen_key = (m.origen or "sin_origen").lower()
        is_on = (m.estado_vcenter or "").upper() in ("POWERED_ON", "POWEREDON")
        disco = m.disk_provisioned_gb or m.disk_used_gb or 0.0

        cat_bucket = por_categoria.setdefault(cat, _bucket_vacio())
        ori_bucket = por_origen.setdefault(origen_key, _bucket_vacio())

        for bucket in (total, cat_bucket, ori_bucket):
            bucket["count"] += 1
            bucket["disco_gb"] = round(bucket["disco_gb"] + disco, 2)
            if is_on:
                bucket["encendidas"] += 1
                bucket["cpu_vcpus"] += (m.cpu or 0)
                bucket["ram_gb"] = round(bucket["ram_gb"] + (m.ram_gb or 0.0), 2)

    return jsonify({
        "total": total,
        "por_categoria": por_categoria,
        "por_origen": por_origen,
    })


@bp_api.route("/maquinas")
def maquinas_api():
    """Búsqueda y paginación completa para tabla de inventario y selector de directorio."""
    page          = int(request.args.get("page", 1))
    per_page      = int(request.args.get("per_page", 50))
    tipo          = request.args.get("tipo", "").strip()
    origen        = request.args.get("origen", "").strip()
    empresa       = request.args.get("empresa", "").strip()
    pool          = request.args.get("pool", "").strip()
    estado_horizon= request.args.get("estado_horizon", "").strip()
    estado_vcenter= request.args.get("estado_vcenter", "").strip()
    servidor_id   = request.args.get("servidor_id", "").strip()
    buscar        = request.args.get("q", "").strip()

    q = Maquina.query.filter_by(activo=True)

    if tipo:
        q = q.filter(Maquina.tipo == tipo)
    if origen:
        q = q.filter(Maquina._origen_str.ilike(f"%{origen}%"))
    if empresa:
        q = q.filter(Maquina._empresa_str.ilike(f"%{empresa}%"))
    if pool:
        q = q.filter(Maquina._pool_str.ilike(f"%{pool}%"))
    if estado_horizon:
        eh_upper = estado_horizon.upper()
        if eh_upper == "CONNECTED":
            q = q.filter(db.or_(
                Maquina.estado_horizon.ilike("%CONNECTED%"),
                db.and_(Maquina.estado_vcenter.ilike("%POWERED_ON%"), Maquina.usuario_asignado != None, Maquina.usuario_asignado != "")
            ))
        elif eh_upper == "AVAILABLE":
            q = q.filter(db.or_(
                Maquina.estado_horizon.ilike("%AVAILABLE%"),
                db.and_(Maquina.estado_vcenter.ilike("%POWERED_ON%"), db.or_(Maquina.usuario_asignado == None, Maquina.usuario_asignado == ""))
            ))
        elif eh_upper == "DISCONNECTED":
            q = q.filter(db.or_(
                Maquina.estado_horizon.ilike("%DISCONNECTED%"),
                Maquina.estado_vcenter.ilike("%POWERED_OFF%")
            ))
        else:
            q = q.filter(Maquina.estado_horizon.ilike(f"%{estado_horizon}%"))
    if estado_vcenter:
        q = q.filter(Maquina.estado_vcenter.ilike(f"%{estado_vcenter}%"))
    if servidor_id:
        try:
            q = q.filter(Maquina.servidor_id == int(servidor_id))
        except ValueError:
            pass

    if buscar:
        like = f"%{buscar}%"
        q = q.filter(db.or_(
            Maquina.nombre.ilike(like),
            Maquina.usuario_asignado.ilike(like),
            Maquina._pool_str.ilike(like),
            Maquina.ip_principal.ilike(like),
            Maquina.dns.ilike(like),
        ))

    # Filtrado dinámico multi-regla global en Base de Datos (across all 1,112+ records)
    custom_filters_raw = request.args.get("custom_filters", "").strip()
    if custom_filters_raw:
        try:
            import json
            rules = json.loads(custom_filters_raw)
            if isinstance(rules, list):
                # Agrupado por campo (2026-09-02): antes cada regla se aplicaba con
                # .filter() encadenado 1 a 1 sin importar el campo -- eso hacia AND entre
                # TODO, incluso dos reglas del MISMO campo (ej. tipo_provisionamiento=
                # VDI_POOL Y =MASTER a la vez, imposible, devolvia vacio siempre). El
                # frontend directamente bloqueaba una segunda regla del mismo campo por
                # esto. Ahora: valores del mismo campo se combinan con OR, campos
                # distintos se siguen combinando con AND como siempre.
                def _cond_tipo(v): return Maquina.tipo == v
                def _cond_origen(v): return Maquina._origen_str.ilike(f"%{v}%")
                def _cond_empresa(v): return Maquina._empresa_str.ilike(f"%{v}%")
                def _cond_pool(v): return Maquina._pool_str.ilike(f"%{v}%")
                def _cond_tipo_prov(v): return Maquina.tipo_provisionamiento == v
                def _cond_estado_horizon(v): return Maquina.estado_horizon.ilike(f"%{v}%")
                def _cond_estado_vcenter(v): return Maquina.estado_vcenter.ilike(f"%{v}%")
                def _cond_servidor_id(v):
                    try:
                        return Maquina.servidor_id == int(v)
                    except ValueError:
                        return None
                def _cond_nombre(v): return Maquina.nombre.ilike(f"%{v}%")
                def _cond_usuario_asignado(v): return Maquina.usuario_asignado.ilike(f"%{v}%")
                def _cond_ip(v): return Maquina.ip_principal.ilike(f"%{v}%")
                def _cond_client_ip(v): return Maquina.client_ip.ilike(f"%{v}%")
                def _cond_client_name(v): return Maquina.client_name.ilike(f"%{v}%")
                def _cond_gateway_ip(v): return Maquina.gateway_ip.ilike(f"%{v}%")
                def _cond_gateway_name(v): return Maquina.gateway_name.ilike(f"%{v}%")
                def _cond_dns(v): return Maquina.dns.ilike(f"%{v}%")
                def _cond_vcenter_host(v): return Maquina.vcenter_host.ilike(f"%{v}%")
                def _cond_folder(v): return Maquina.folder.ilike(f"%{v}%")
                def _cond_so(v): return Maquina.so.ilike(f"%{v}%")
                def _cond_annotation(v): return Maquina.annotation.ilike(f"%{v}%")
                def _cond_resource_pool(v): return Maquina.resource_pool.ilike(f"%{v}%")
                def _cond_datastores(v): return Maquina.datastores.ilike(f"%{v}%")
                # Estos 8 eran columnas visibles/ocultables en la tabla (ALL_COLUMNS de
                # InventarioPage.jsx) pero nunca tuvieron condicion en el backend -- ni
                # siquiera estaban en el picker de filtros (gap preexistente, no de hoy,
                # encontrado al auditar por el pedido de "agregaste todo?" 2026-09-02).
                def _cond_estado_horizon_agente(v): return Maquina.estado_horizon_agente.ilike(f"%{v}%")
                def _cond_tools_status(v): return Maquina.tools_status.ilike(f"%{v}%")
                def _cond_estado(v): return Maquina.estado.ilike(f"%{v}%")
                def _cond_fecha_ultimo_ingreso(v): return Maquina.fecha_ultimo_ingreso.ilike(f"%{v}%")
                def _cond_hardware_version(v): return Maquina.hardware_version.ilike(f"%{v}%")
                def _cond_connection_state(v): return Maquina.connection_state.ilike(f"%{v}%")
                # cpu/ram_gb/disk_gb/cpu_usage_mhz/memory_usage_mb: YA estaban en el picker
                # de filtros (type: 'number') pero el backend nunca tenia un branch para
                # ellos -- se ignoraban en silencio, el filtro no hacia nada (bug
                # preexistente, mismo hallazgo de arriba). Match exacto (no rango >=/<=,
                # eso requeriria un selector de operador en el UI que no existe hoy).
                def _cond_cpu(v):
                    try:
                        return Maquina.cpu == int(v)
                    except ValueError:
                        return None
                def _cond_ram_gb(v):
                    try:
                        return Maquina.ram_gb == float(v)
                    except ValueError:
                        return None
                def _cond_disk_gb(v):
                    try:
                        return Maquina.disk_provisioned_gb == float(v)
                    except ValueError:
                        return None
                def _cond_cpu_usage_mhz(v):
                    try:
                        return Maquina.cpu_usage_mhz == int(v)
                    except ValueError:
                        return None
                def _cond_memory_usage_mb(v):
                    try:
                        return Maquina.memory_usage_mb == int(v)
                    except ValueError:
                        return None
                def _cond_maintenance_mode(v): return Maquina.maintenance_mode == (v.lower() == "true")
                def _cond_in_error_state(v): return Maquina.in_error_state == (v.lower() == "true")
                def _cond_persistencia(v):
                    vv = v.strip().lower()
                    if vv in ("persistente", "dedicated"):
                        pool_ids = db.session.query(Pool.id).filter(db.or_(Pool.user_assignment == None, ~Pool.user_assignment.ilike("floating")))
                        return db.and_(Maquina.tipo_provisionamiento == "VDI_POOL", Maquina.pool_id.in_(pool_ids))
                    if vv in ("no persistente", "floating"):
                        pool_ids = db.session.query(Pool.id).filter(Pool.user_assignment.ilike("floating"))
                        return db.and_(Maquina.tipo_provisionamiento == "VDI_POOL", Maquina.pool_id.in_(pool_ids))
                    if "estat" in vv:
                        return Maquina.tipo_provisionamiento == "VM_ESTATICA"
                    return None

                def _cond_master_o_snapshot(field_name, v):
                    # Master/snapshot viven en Pool, no en Maquina -- se resuelve primero
                    # qué pools matchean y se filtra Maquina por nombre de pool. Comparación
                    # en minúsculas: Pool.nombre viene del endpoint desktop-pools (case del
                    # display) mientras que Maquina._pool_str viene del campo "Pool" crudo
                    # del listado de máquinas -- mismos pools, casing distinto.
                    columna_pool = Pool.master_vm_actual if field_name == "master_vm_actual" else Pool.snapshot_actual
                    pool_nombres_lower = [p.nombre.lower() for p in Pool.query.filter(columna_pool.ilike(f"%{v}%")).all()]
                    return db.func.lower(Maquina._pool_str).in_(pool_nombres_lower) if pool_nombres_lower else db.false()

                def _cond_categoria_estatica(v):
                    # Misma logica que _categoria_estatica() (mas abajo, usada para el
                    # badge) traducida a condicion SQL para poder filtrar por ella.
                    vv = v.strip().lower()
                    masters_subq = db.session.query(db.func.lower(Maquina.nombre)).filter(Maquina.tipo_provisionamiento == "MASTER")
                    if "infra" in vv or "interna" in vv:
                        return db.and_(
                            Maquina.tipo_provisionamiento == "VM_ESTATICA",
                            db.or_(*[Maquina.nombre.ilike(f"{p}%") for p in _PREFIJOS_INFRA_INTERNA]),
                        )
                    if vv == "rpa":
                        return db.and_(Maquina.tipo_provisionamiento == "VM_ESTATICA", Maquina.nombre.ilike("%rpa%"))
                    if "copia" in vv:
                        return db.and_(
                            Maquina.tipo_provisionamiento == "VM_ESTATICA",
                            ~Maquina.nombre.ilike("%rpa%"),
                            db.func.lower(Maquina.nombre).in_(masters_subq),
                        )
                    if "huerf" in vv or "huérf" in vv:
                        return db.and_(
                            Maquina.tipo_provisionamiento == "VM_ESTATICA",
                            ~Maquina.nombre.ilike("%rpa%"),
                            ~db.func.lower(Maquina.nombre).in_(masters_subq),
                            Maquina.nombre.ilike("vdi-%"),
                        )
                    return None

                def _cond_segmentacion(v):
                    # Campo virtual que unifica tipo_provisionamiento + categoria_estatica en
                    # los mismos 7 valores que getSegmentacionBadge() pinta en la columna
                    # "Segmentación" de InventarioPage.jsx (auditoría de filtros 2026-09-04,
                    # 3ra vuelta -- el usuario esperaba poder buscar por RPA/Infra Interna/etc
                    # bajo el mismo filtro "Segmentación" que ve en la tabla, no en un campo
                    # separado con otro nombre).
                    vv = v.strip().lower()
                    if vv == "master": return Maquina.tipo_provisionamiento == "MASTER"
                    if vv in ("template", "plantilla"): return Maquina.tipo_provisionamiento == "TEMPLATE"
                    if vv in ("vdi_pool", "vdi pool"): return Maquina.tipo_provisionamiento == "VDI_POOL"
                    if vv == "estatica":
                        masters_subq = db.session.query(db.func.lower(Maquina.nombre)).filter(Maquina.tipo_provisionamiento == "MASTER")
                        return db.and_(
                            Maquina.tipo_provisionamiento == "VM_ESTATICA",
                            ~db.or_(*[Maquina.nombre.ilike(f"{p}%") for p in _PREFIJOS_INFRA_INTERNA]),
                            ~Maquina.nombre.ilike("%rpa%"),
                            ~db.func.lower(Maquina.nombre).in_(masters_subq),
                            ~Maquina.nombre.ilike("vdi-%"),
                        )
                    return _cond_categoria_estatica(v)

                def _cond_responsable(v):
                    ids_subq = (
                        db.session.query(MaquinaUsuarioDir.maquina_id)
                        .join(DirectorioUsuario, MaquinaUsuarioDir.directorio_usuario_id == DirectorioUsuario.id)
                        .filter(MaquinaUsuarioDir.tipo == "principal", MaquinaUsuarioDir.activo == True)
                        .filter(db.or_(DirectorioUsuario.nombre_completo.ilike(f"%{v}%"), DirectorioUsuario.username.ilike(f"%{v}%")))
                    )
                    return Maquina.id.in_(ids_subq)

                _SIMPLE_COND_BUILDERS = {
                    "tipo": _cond_tipo, "origen": _cond_origen, "empresa": _cond_empresa,
                    "pool": _cond_pool, "tipo_provisionamiento": _cond_tipo_prov,
                    "estado_horizon": _cond_estado_horizon, "estado_vcenter": _cond_estado_vcenter,
                    "servidor_id": _cond_servidor_id, "nombre": _cond_nombre,
                    "usuario_asignado": _cond_usuario_asignado, "ip": _cond_ip, "ip_principal": _cond_ip,
                    "client_ip": _cond_client_ip, "client_name": _cond_client_name,
                    "gateway_ip": _cond_gateway_ip, "gateway_name": _cond_gateway_name,
                    "dns": _cond_dns, "vcenter_host": _cond_vcenter_host, "folder": _cond_folder,
                    "so": _cond_so, "maintenance_mode": _cond_maintenance_mode,
                    "in_error_state": _cond_in_error_state,
                    "persistencia": _cond_persistencia, "categoria_estatica": _cond_categoria_estatica,
                    "segmentacion": _cond_segmentacion,
                    "responsable": _cond_responsable, "annotation": _cond_annotation,
                    "resource_pool": _cond_resource_pool, "datastores": _cond_datastores,
                    "estado_horizon_agente": _cond_estado_horizon_agente, "tools_status": _cond_tools_status,
                    "estado": _cond_estado, "fecha_ultimo_ingreso": _cond_fecha_ultimo_ingreso,
                    "hardware_version": _cond_hardware_version, "connection_state": _cond_connection_state,
                    "cpu": _cond_cpu, "ram_gb": _cond_ram_gb, "disk_gb": _cond_disk_gb,
                    "cpu_usage_mhz": _cond_cpu_usage_mhz, "memory_usage_mb": _cond_memory_usage_mb,
                }

                rules_by_field: dict[str, list[str]] = {}
                for rule in rules:
                    field = rule.get("field")
                    val = str(rule.get("value") or "").strip()
                    if not field or not val:
                        continue
                    rules_by_field.setdefault(field, []).append(val)

                for field, values in rules_by_field.items():
                    if field in ("master_vm_actual", "snapshot_actual"):
                        conds = [_cond_master_o_snapshot(field, v) for v in values]
                    else:
                        builder = _SIMPLE_COND_BUILDERS.get(field)
                        if not builder:
                            continue
                        conds = [builder(v) for v in values]
                    conds = [c for c in conds if c is not None]
                    if not conds:
                        continue
                    q = q.filter(db.or_(*conds) if len(conds) > 1 else conds[0])
        except Exception as e:
            # Antes: silencioso total -- un custom_filters_raw corrupto (JSON roto, o un
            # bug en cualquiera de los _cond_* de arriba) devolvía la lista SIN filtrar,
            # indistinguible en la UI de "no hay resultados que filtrar" (hallazgo de
            # calidad de código, corregido 2026-09-07).
            import logging
            logging.getLogger(__name__).warning(
                "custom_filters ignorado por error de parseo/evaluación (%s): %s",
                e, custom_filters_raw[:300],
            )

    # Búsqueda simple rápida para vinculaciones
    if request.args.get("simple") == "1":
        items = q.order_by(Maquina.nombre).limit(20).all()
        return jsonify([m.to_dict() for m in items])

    total = q.count()
    items = q.order_by(Maquina.nombre).offset((page - 1) * per_page).limit(per_page).all()

    # Anclar master/snapshot actual del Pool en cada fila (pedido: columnas de
    # inventario deben mostrar esta info, no solo el modal de trazabilidad).
    # Un solo query para todos los pools de la página en vez de N+1 por máquina.
    pool_nombres_pagina = {(m._pool_str or "").lower() for m in items if m._pool_str}
    imagen_por_pool = {}
    if pool_nombres_pagina:
        for p in Pool.query.filter(db.func.lower(Pool.nombre).in_(pool_nombres_pagina)).all():
            imagen_por_pool[p.nombre.lower()] = {
                "master_vm_actual": p.master_vm_actual or "",
                "snapshot_actual": p.snapshot_actual or "",
            }

    # Sub-categoria de VM_ESTATICA -- RPA/Copia(no activa)/VDI Huerfana/Infra Interna, ver
    # _categoria_estatica_codigo() (fuente única, también usada por /api/filtros/valores_distintos
    # y por _cond_categoria_estatica -- antes esta lógica estaba duplicada acá, podía
    # desincronizarse del picker de filtros, auditoría 2026-09-04).
    master_names_lower = _master_names_lower()

    def _categoria_estatica(nombre: str) -> str:
        codigo = _categoria_estatica_codigo(nombre, master_names_lower)
        return _CATEGORIA_ESTATICA_LABELS.get(codigo, "")

    # Responsable manual (MaquinaUsuarioDir tipo=principal) -- separado de usuario_asignado
    # (que es dinamico, viene de sesion Horizon activa y no aplica a VM_ESTATICA). Un solo
    # query para todas las maquinas de la pagina en vez de N+1 por fila.
    maquina_ids_pagina = [m.id for m in items]
    responsable_por_maquina = {}
    if maquina_ids_pagina:
        filas_resp = (
            db.session.query(MaquinaUsuarioDir, DirectorioUsuario)
            .join(DirectorioUsuario, MaquinaUsuarioDir.directorio_usuario_id == DirectorioUsuario.id)
            .filter(MaquinaUsuarioDir.maquina_id.in_(maquina_ids_pagina))
            .filter(MaquinaUsuarioDir.tipo == "principal")
            .filter(MaquinaUsuarioDir.activo == True)
            .all()
        )
        for mud, du in filas_resp:
            responsable_por_maquina[mud.maquina_id] = {
                "responsable": du.nombre_completo or du.username,
                "responsable_vinculo_id": mud.id,
                # username/email reales del Responsable -- getTeamsChatUrl() necesita esto
                # (no el nombre completo con espacios, que la funcion rechaza a proposito
                # para no armar un deep link de Teams invalido) para poder linkear igual
                # que usuario_asignado.
                "responsable_username": du.username,
                "responsable_email": du.email,
            }

    items_dict = []
    for m in items:
        d = m.to_dict()
        imagen = imagen_por_pool.get((m._pool_str or "").lower(), {})
        d["master_vm_actual"] = imagen.get("master_vm_actual", "")
        d["snapshot_actual"] = imagen.get("snapshot_actual", "")
        resp = responsable_por_maquina.get(m.id, {})
        d["responsable"] = resp.get("responsable", "")
        d["responsable_vinculo_id"] = resp.get("responsable_vinculo_id")
        d["responsable_username"] = resp.get("responsable_username", "")
        d["responsable_email"] = resp.get("responsable_email", "")
        d["categoria_estatica"] = _categoria_estatica(m.nombre) if m.tipo_provisionamiento == "VM_ESTATICA" else ""
        items_dict.append(d)

    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": items_dict,
    })



@bp_api.route("/maquinas/<int:mid>/trazabilidad")
def maquina_trazabilidad_api(mid: int):
    m = Maquina.query.get_or_404(mid)
    
    # Historial de rotación de usuarios
    rotaciones = (
        HistorialUsuarioVDI.query
        .filter_by(nombre_vm=m.nombre)
        .order_by(HistorialUsuarioVDI.detectado_en.desc())
        .all()
    )

    # Historial de cambios detectados (Deltas)
    cambios = (
        MaquinaHistorial.query
        .filter_by(maquina_id=m.id)
        .order_by(MaquinaHistorial.detectado_en.desc())
        .limit(100)
        .all()
    )

    # "Timeline de Snapshots": bug real encontrado 2026-09-07 -- Maquina es la tabla de
    # ESTADO ACTUAL (1 fila por VM, no crece por extracción, ver web/db.py), así que
    # Maquina.query.join(InventarioSnapshot).filter(Maquina.nombre==m.nombre) nunca podía
    # dar una evolución real en el tiempo: como mucho devolvía la propia fila de `m` (o
    # alguna otra VM con nombre idéntico, ver duplicados de golden image documentados en
    # CLAUDE.md) -- confirmado en vivo: para una VM con 94 snapshots reales de su servidor,
    # esta query devolvía 4 filas, ninguna de esas 94. El frontend (VmTimelineView.jsx)
    # solo usa este array para el contador "Snapshots Evaluados", no arma la línea de
    # tiempo visual con él (esa sale de `cambios`/`rotaciones`/`eventos`, esas sí reales).
    # Reemplazado por el conteo real de snapshots del servidor de esta VM desde que se
    # detectó por primera vez -- no hay historial de VALORES por snapshot (para eso está
    # `cambios`, delta real por campo), pero al menos el número deja de ser arbitrario.
    snapshots_reales = (
        InventarioSnapshot.query
        .filter(InventarioSnapshot.servidor_id == m.servidor_id)
        .filter(InventarioSnapshot.timestamp >= m.primera_deteccion)
        .order_by(InventarioSnapshot.timestamp.desc())
        .limit(50)
        .all()
    ) if m.primera_deteccion else []

    # Eventos y Tareas vCenter anclados
    from web.db import VMTareaEvento
    eventos_vc = (
        VMTareaEvento.query
        .filter_by(maquina_id=m.id)
        .order_by(VMTareaEvento.fecha.desc())
        .limit(200)
        .all()
    )

    # Eventos de auditoría Horizon (InfraEvento) -- no tienen maquina_id (son a nivel
    # Pool o de hostname de sesión, ver _persistir_audit_events_horizon), así que se
    # cruzan acá por Pool.nombre (vía el FK real Maquina.pool_id, no por texto libre)
    # y por el propio nombre de la VM (eventos de sesión tipo "detected user X inactive").
    # Esto es lo que hace aparecer Image Publish/Unpublish en la ficha de una VDI.
    eventos_horizon_pool = []
    pool_row = Pool.query.get(m.pool_id) if m.pool_id else None
    if m.pool_id or m.nombre:
        pool_nombre = pool_row.nombre if pool_row else None
        filtros_entidad = [InfraEvento.entidad_nombre.ilike(m.nombre)]
        if pool_nombre:
            filtros_entidad.append(InfraEvento.entidad_nombre.ilike(pool_nombre))
        eventos_horizon_pool = (
            InfraEvento.query
            .filter_by(tipo="horizon_audit")
            .filter(db.or_(*filtros_entidad))
            .order_by(InfraEvento.detectado_en.desc())
            .limit(100)
            .all()
        )

    from web.appvolumes_utils import apps_asignadas_para_maquina, actividad_reciente_para_maquina, writables_para_maquina

    return jsonify({
        "maquina": m.to_dict(),
        "rotaciones": [r.to_dict() for r in rotaciones],
        "cambios": [
            {
                "id": c.id,
                "campo": c.campo_modificado,
                "valor_anterior": c.valor_anterior,
                "valor_nuevo": c.valor_nuevo,
                "detectado_en": c.detectado_en.strftime("%d/%m/%Y %H:%M") if c.detectado_en else ""
            } for c in cambios
        ],
        "eventos": [
            {
                "id": e.id,
                "tipo": e.tipo,
                "nombre_evento": e.nombre_evento,
                "mensaje": e.mensaje,
                "usuario": e.usuario,
                "estado": e.estado,
                "fecha": e.fecha.strftime("%d/%m/%Y %H:%M") if e.fecha else ""
            } for e in eventos_vc
        ],
        "eventos_horizon": [
            {
                "id": e.id,
                "entidad": e.entidad_nombre,
                "tipo_evento": e.valor_nuevo,
                "mensaje": e.mensaje,
                "fecha": e.detectado_en.strftime("%d/%m/%Y %H:%M") if e.detectado_en else ""
            } for e in eventos_horizon_pool
        ],
        "pool_imagen": pool_row.to_dict() if pool_row else None,
        "timeline": [
            {
                "snapshot_id": s.id,
                "timestamp": s.timestamp.strftime("%d/%m/%Y %H:%M") if s.timestamp else "—",
                "total_vms_servidor": s.total_vms,
            } for s in snapshots_reales
        ],
        "appvolumes_apps": apps_asignadas_para_maquina(m),
        "appvolumes_actividad": actividad_reciente_para_maquina(m),
        "appvolumes_writables": writables_para_maquina(m),
    })



@bp_api.route("/reportes/generar", methods=["POST"])
def reportes_generar_api():
    from web.routes.reportes import _generar_excel
    import os
    data = request.get_json(silent=True) or request.form or {}
    tipo = data.get("tipo", "").strip()
    origen = data.get("origen", "").strip()
    servidor_id = str(data.get("servidor_id", "")).strip()

    try:
        filepath = _generar_excel(
            tipo_filter=tipo,
            origen_filter=origen,
            servidor_id=servidor_id
        )
        filename = os.path.basename(filepath)
        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": f"/api/reportes/descargar/{filename}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp_api.route("/reportes/descargar/<filename>")
def reportes_descargar_api(filename: str):
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reports_dir = os.path.join(base_dir, "reportes")
    if not os.path.exists(os.path.join(reports_dir, filename)):
        reports_dir = os.path.join(base_dir, "exports")
    return send_from_directory(reports_dir, filename, as_attachment=True)


@bp_api.route("/reportes/archivos")
def reportes_archivos_api():
    import os
    from datetime import datetime
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reports_dir = os.path.join(base_dir, "reportes")
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir, exist_ok=True)

    archivos = []
    for f in sorted(os.listdir(reports_dir), reverse=True):
        if f.endswith((".xlsx", ".csv", ".json")):
            p = os.path.join(reports_dir, f)
            st = os.stat(p)
            archivos.append({
                "nombre": f,
                "size_kb": round(st.st_size / 1024, 1),
                "fecha": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"),
                "download_url": f"/api/reportes/descargar/{f}"
            })
    return jsonify(archivos)



