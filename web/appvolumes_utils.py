"""
web/appvolumes_utils.py
Cruce en runtime entre el inventario de VMs/usuarios y los datos sincronizados
de App Volumes (appvolumes_asignaciones / appvolumes_actividad, ver comentario
en web/db.py sobre AppVolumesAsignacion/AppVolumesActividad).

AppVolumesAsignacion es estático (a qué entidad AD le corresponde un app/paquete)
y no expande membresía de grupos AD -- solo matchea entity_type=Computer contra
Maquina.nombre y entity_type=User contra el usuario limpio (sin dominio\\ ni @upn).
AppVolumesActividad es el log de eventos (Attach/Assign/Login) y da el link real
VM+usuario+app mientras dura la sesión.
"""
from web.db import (
    db, AppVolumesAsignacion, AppVolumesActividad, AppVolumesAplicacion, AppVolumesPaquete,
    AppVolumesWritable, Maquina, DirectorioUsuario, Servidor,
)
from web.security_utils import normalizar_username as _limpiar_usuario


def _servidor_badge_map() -> dict:
    """id de Servidor -> badge corto de origen (última palabra del nombre, ej.
    'AppVolumes DT' -> 'DT', 'AppVolumes MZ' -> 'MZ')."""
    return {
        s.id: (s.nombre.split()[-1] if s.nombre else str(s.id))
        for s in Servidor.query.filter_by(tipo="appvolumes").all()
    }


def _enriquecer_asignaciones(asignaciones):
    app_ids = {a.aplicacion_id for a in asignaciones if a.aplicacion_id}
    pkg_ids = {a.paquete_id for a in asignaciones if a.paquete_id}
    apps_map = (
        {a.id: a.nombre for a in AppVolumesAplicacion.query.filter(AppVolumesAplicacion.id.in_(app_ids)).all()}
        if app_ids else {}
    )
    pkgs_map = (
        {p.id: p.nombre for p in AppVolumesPaquete.query.filter(AppVolumesPaquete.id.in_(pkg_ids)).all()}
        if pkg_ids else {}
    )
    badges = _servidor_badge_map()

    # La misma app/paquete asignado a la misma entidad desde varios App Volumes Manager
    # (DT/MZ, cada uno con su propio catálogo independiente) es la misma asignación
    # lógica para el usuario -- se fusiona en una sola fila con badges de origen en vez
    # de listarla duplicada una vez por servidor.
    agrupado = {}
    orden = []
    for a in asignaciones:
        d = a.to_dict()
        d["aplicacion_nombre"] = apps_map.get(a.aplicacion_id) or ""
        d["paquete_nombre"] = pkgs_map.get(a.paquete_id) or ""
        clave = (d["entity_type"], d["entity_name"], d["aplicacion_nombre"] or d["paquete_nombre"])
        badge = badges.get(a.servidor_id, "")

        if clave not in agrupado:
            d["servidores"] = [badge] if badge else []
            agrupado[clave] = d
            orden.append(clave)
        elif badge and badge not in agrupado[clave]["servidores"]:
            agrupado[clave]["servidores"].append(badge)

    return [agrupado[k] for k in orden]


def apps_asignadas_para_maquina(maquina) -> list:
    """Apps/paquetes asignados (estático) a esta VM: por entity_type=Computer
    contra el nombre de la VM, o entity_type=User contra su usuario_asignado
    actual. No expande grupos AD."""
    nombre_vm = (maquina.nombre or "").strip()
    usuario = _limpiar_usuario(maquina.usuario_asignado)

    filtros = []
    if nombre_vm:
        # Las entidades Computer vienen de AD con "$" final (cuenta de equipo, ej.
        # "VDI-015-TYONP$") -- Maquina.nombre no lo tiene, hay que matchear ambas formas.
        filtros.append(db.and_(
            AppVolumesAsignacion.entity_type == "Computer",
            db.or_(
                AppVolumesAsignacion.entity_name.ilike(nombre_vm),
                AppVolumesAsignacion.entity_name.ilike(f"{nombre_vm}$"),
            ),
        ))
    if usuario:
        filtros.append(db.and_(
            AppVolumesAsignacion.entity_type == "User",
            db.or_(
                AppVolumesAsignacion.entity_name.ilike(f"%\\{usuario}"),
                AppVolumesAsignacion.entity_name.ilike(usuario),
                AppVolumesAsignacion.entity_upn.ilike(f"{usuario}@%"),
            ),
        ))
    if not filtros:
        return []

    asignaciones = (
        AppVolumesAsignacion.query
        .filter(AppVolumesAsignacion.activo == True)
        .filter(db.or_(*filtros))
        .all()
    )
    return _enriquecer_asignaciones(asignaciones)


def apps_asignadas_para_usuario(directorio_usuario) -> list:
    """Apps/paquetes asignados (estático) directamente a este usuario (entity_type=User).
    No expande membresía de grupos AD."""
    # AD real puede tener el logon name (username) y el sAMAccountName (pre-Windows 2000)
    # como strings distintos -- matchear contra ambos si el segundo ya se verificó y
    # quedó guardado (ver Verificar AD / core/ad_client.py).
    candidatos = {
        _limpiar_usuario(directorio_usuario.username),
        _limpiar_usuario(directorio_usuario.sam_account_name),
    } - {""}
    if not candidatos:
        return []

    condiciones = []
    for usuario in candidatos:
        condiciones.extend([
            AppVolumesAsignacion.entity_name.ilike(f"%\\{usuario}"),
            AppVolumesAsignacion.entity_name.ilike(usuario),
            AppVolumesAsignacion.entity_upn.ilike(f"{usuario}@%"),
        ])

    asignaciones = (
        AppVolumesAsignacion.query
        .filter(AppVolumesAsignacion.activo == True)
        .filter(AppVolumesAsignacion.entity_type == "User")
        .filter(db.or_(*condiciones))
        .all()
    )
    return _enriquecer_asignaciones(asignaciones)


def writables_para_maquina(maquina) -> dict:
    """Writable Volumes (perfil/datos persistentes de App Volumes) atados a esta VM --
    por 'attached_to' (montado ahí ahora mismo) o por el usuario_asignado actual. Pedido
    2026-08-13: cruzar esto contra las alertas de disco -- es común que un usuario tenga
    más de un writable (perfil + varios volúmenes de datos, o uno viejo sin desasignar)
    inflando el disco real más de lo que el ficha muestra a simple vista.

    Devuelve {"items": [...], "total_gb": float, "cantidad": int} -- total_gb es la suma
    de size_gb de todos los writables encontrados, la señal concreta de "cuánto de tu
    disco es en realidad perfil/datos de usuario, no la imagen base"."""
    nombre_vm = (maquina.nombre or "").strip()
    usuario = _limpiar_usuario(maquina.usuario_asignado)

    filtros = []
    if nombre_vm:
        filtros.append(AppVolumesWritable.attached_to.ilike(nombre_vm))
    if usuario:
        # entity_name ya viene limpio (sin "DOMINIO\\") desde core/appvolumes_rest.py --
        # confirmado en vivo 2026-08-13, no hace falta variante con backslash acá.
        filtros.append(db.and_(
            AppVolumesWritable.entity_type == "User",
            AppVolumesWritable.entity_name.ilike(usuario),
        ))
    if not filtros:
        return {"items": [], "total_gb": 0.0, "cantidad": 0}

    writables = (
        AppVolumesWritable.query
        .filter(AppVolumesWritable.activo == True)
        .filter(db.or_(*filtros))
        .all()
    )
    items = [w.to_dict() for w in writables]
    total_gb = round(sum(w.size_mb or 0 for w in writables) / 1024, 2)
    return {"items": items, "total_gb": total_gb, "cantidad": len(items)}


def actividad_reciente_para_maquina(maquina, limit: int = 20) -> list:
    """Eventos recientes de App Volumes (Attach/Assign/Login) donde esta VM aparece
    como source o target -- el único link real 'en vivo' VM+usuario+app."""
    nombre_vm = (maquina.nombre or "").strip()
    if not nombre_vm:
        return []
    eventos = (
        AppVolumesActividad.query
        .filter(db.or_(
            AppVolumesActividad.target_name.ilike(nombre_vm),
            AppVolumesActividad.source_name.ilike(nombre_vm),
        ))
        .order_by(AppVolumesActividad.event_time.desc())
        .limit(limit)
        .all()
    )
    return [e.to_dict() for e in eventos]


# confianza="alta": lo verificamos afirmativamente (existió acá y quedó marcado inactivo/
# decomisionado). confianza="baja": simplemente no está en nuestras tablas locales -- que
# no esté en DirectorioUsuario NO prueba que no exista en AD real (esa tabla se arma de
# gente que usó una VDI alguna vez, no es un sync completo de AD; App Volumes también
# gestiona PCs físicas cuyos usuarios pueden no haber tocado nunca una VDI). No depurar
# a ciegas por "baja" sin confirmar contra AD/inventario real primero.
_MOTIVOS_HUERFANA = {
    "vm_decomisionada": {"label": "VM decomisionada (verificado)", "confianza": "alta"},
    "usuario_inactivo": {"label": "Usuario inactivo/fuera de AD (verificado)", "confianza": "alta"},
    "vm_no_encontrada": {"label": "VM sin rastro en el inventario (no confirmado)", "confianza": "baja"},
    "usuario_no_encontrado": {"label": "Usuario sin rastro en el Directorio (no confirmado)", "confianza": "baja"},
}


def asignaciones_huerfanas() -> list:
    """Asignaciones activas de App Volumes cuya entidad (VM o usuario) ya no existe o
    está inactiva -- assignments que siguen vivos en el App Volumes Manager real pero
    apuntan a algo dado de baja acá, candidatos a depurar manualmente en el Admin UI
    (esta app no borra nada del lado de App Volumes, solo lo señala)."""
    asignaciones = (
        AppVolumesAsignacion.query
        .filter(AppVolumesAsignacion.activo == True)
        .filter(AppVolumesAsignacion.entity_type.in_(("User", "Computer")))
        .all()
    )
    if not asignaciones:
        return []

    maquinas_por_nombre = {m.nombre.lower(): m for m in Maquina.query.all() if m.nombre}
    # Indexado por username Y sam_account_name -- AD real puede tener ambos como strings
    # distintos (ver comentario en el modelo DirectorioUsuario), matchear por cualquiera.
    usuarios_por_nombre = {}
    for u in DirectorioUsuario.query.all():
        if u.username:
            usuarios_por_nombre[u.username.lower()] = u
        if u.sam_account_name:
            usuarios_por_nombre.setdefault(u.sam_account_name.lower(), u)
    badges = _servidor_badge_map()

    app_ids = {a.aplicacion_id for a in asignaciones if a.aplicacion_id}
    pkg_ids = {a.paquete_id for a in asignaciones if a.paquete_id}
    apps_map = (
        {a.id: a.nombre for a in AppVolumesAplicacion.query.filter(AppVolumesAplicacion.id.in_(app_ids)).all()}
        if app_ids else {}
    )
    pkgs_map = (
        {p.id: p.nombre for p in AppVolumesPaquete.query.filter(AppVolumesPaquete.id.in_(pkg_ids)).all()}
        if pkg_ids else {}
    )

    # Misma fusión que _enriquecer_asignaciones: la misma entidad+app huérfana reportada
    # por DT y por MZ a la vez es un solo problema a depurar, no dos filas -- se fusiona
    # con badges de origen y se conserva el updated_at más reciente entre las fusionadas.
    agrupado = {}
    orden = []
    for a in asignaciones:
        motivo = None
        if a.entity_type == "Computer":
            # Cuenta de equipo AD trae "$" final (ej. "VDI-015-TYONP$"), Maquina.nombre no.
            nombre_limpio = a.entity_name[:-1] if a.entity_name.endswith("$") else a.entity_name
            m = maquinas_por_nombre.get(nombre_limpio.lower())
            if not m:
                motivo = "vm_no_encontrada"
            elif not m.activo:
                motivo = "vm_decomisionada"
        elif a.entity_type == "User":
            u = usuarios_por_nombre.get(a.entity_name.lower())
            if not u:
                motivo = "usuario_no_encontrado"
            elif not u.activo_ad:
                motivo = "usuario_inactivo"

        if not motivo:
            continue

        aplicacion_nombre = apps_map.get(a.aplicacion_id) or ""
        paquete_nombre = pkgs_map.get(a.paquete_id) or ""
        clave = (a.entity_type, a.entity_name, aplicacion_nombre or paquete_nombre, motivo)
        badge = badges.get(a.servidor_id, "")

        if clave not in agrupado:
            agrupado[clave] = {
                "id": a.id,
                "servidores": [badge] if badge else [],
                "entity_type": a.entity_type,
                "entity_name": a.entity_name,
                "aplicacion_nombre": aplicacion_nombre,
                "paquete_nombre": paquete_nombre,
                "delivery": a.delivery or "",
                "motivo": motivo,
                "motivo_label": _MOTIVOS_HUERFANA[motivo]["label"],
                "confianza": _MOTIVOS_HUERFANA[motivo]["confianza"],
                "updated_at": a.updated_at.strftime("%d/%m/%Y %H:%M") if a.updated_at else "",
                "_updated_raw": a.updated_at,
            }
            orden.append(clave)
        else:
            item = agrupado[clave]
            if badge and badge not in item["servidores"]:
                item["servidores"].append(badge)
            if a.updated_at and (item["_updated_raw"] is None or a.updated_at > item["_updated_raw"]):
                item["updated_at"] = a.updated_at.strftime("%d/%m/%Y %H:%M")
                item["_updated_raw"] = a.updated_at

    resultado = [agrupado[k] for k in orden]
    for r in resultado:
        r.pop("_updated_raw", None)
    resultado.sort(key=lambda r: r["updated_at"], reverse=True)
    return resultado


def usuarios_no_resueltos() -> list:
    """Usernames únicos de App Volumes (entity_type=User) que no matchean ningún
    DirectorioUsuario local -- candidatos para verificar contra AD real antes de
    asumir que son basura para depurar (ver nota de confianza en _MOTIVOS_HUERFANA)."""
    vistos = set()
    resultado = []
    for h in asignaciones_huerfanas():
        if h["entity_type"] == "User" and h["motivo"] == "usuario_no_encontrado" and h["entity_name"] not in vistos:
            vistos.add(h["entity_name"])
            resultado.append(h["entity_name"])
    return resultado


def actividad_reciente_para_usuario(directorio_usuario, limit: int = 20) -> list:
    """Eventos recientes de App Volumes donde este usuario aparece como source."""
    usuario = _limpiar_usuario(directorio_usuario.username)
    if not usuario:
        return []
    eventos = (
        AppVolumesActividad.query
        .filter(AppVolumesActividad.source_name.ilike(f"%{usuario}%"))
        .order_by(AppVolumesActividad.event_time.desc())
        .limit(limit)
        .all()
    )
    return [e.to_dict() for e in eventos]
