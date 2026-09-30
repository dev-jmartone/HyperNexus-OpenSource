"""
web/granja_utils.py
Cruces derivados de la Granja RDS (Farms, Aplicaciones Publicadas, RDS Servers) con
Directorio (AD) y con las VDI-VMs existentes de cada usuario. Sin tablas propias -- todo
se calcula al consultar, mismo criterio que las métricas de /pools/detalladas en
web/routes/api.py.
"""
from web.db import (
    db, Farm, AplicacionPublicada, AplicacionEntitlement,
    Pool, PoolEntitlement, Maquina, DirectorioUsuario,
)
from web.appvolumes_utils import _limpiar_usuario


def _matchear_directorio(usuario_o_grupo: str, es_grupo: bool) -> dict | None:
    """Busca el usuario_o_grupo de un entitlement contra DirectorioUsuario (username o
    sam_account_name, normalizado igual que apps_asignadas_para_usuario en
    appvolumes_utils.py). None si es grupo (no tiene sentido matchear un grupo AD como
    persona) o si no matchea -- el caller decide cómo marcar "no encontrado"."""
    if es_grupo:
        return None
    usuario = _limpiar_usuario(usuario_o_grupo)
    if not usuario:
        return None
    u = DirectorioUsuario.query.filter(
        db.or_(
            DirectorioUsuario.username.ilike(usuario),
            DirectorioUsuario.sam_account_name.ilike(usuario),
        )
    ).first()
    if not u:
        return None
    return {
        "id": u.id,
        "nombre_completo": u.nombre_completo or "",
        "email": u.email or "",
        "departamento": u.departamento or "",
        "activo_ad": u.activo_ad,
    }


def enriquecer_entitlements_con_directorio(entitlements: list) -> list:
    """Recibe una lista de dicts con 'usuario_o_grupo'/'es_grupo' (PoolEntitlement.to_dict()
    o AplicacionEntitlement.to_dict()) y les agrega 'directorio' (match o None)."""
    out = []
    for e in entitlements:
        item = dict(e)
        item["directorio"] = _matchear_directorio(e.get("usuario_o_grupo", ""), e.get("es_grupo", False))
        out.append(item)
    return out


def autorizados_por_farm(farm: Farm) -> list:
    """Rollup de 'quién está autorizado' para una Farm: Horizon no tiene entitlements a
    nivel Farm (solo por Application Pool y por el Pool RDS enlazado, si existe) -- se
    deriva uniendo ambas fuentes y dedupeando por (usuario_o_grupo, es_grupo)."""
    vistos = {}
    for aplicacion in farm.aplicaciones:
        if not aplicacion.activo:
            continue
        for ent in aplicacion.entitlements:
            key = (ent.usuario_o_grupo.lower(), ent.es_grupo)
            if key not in vistos:
                d = ent.to_dict()
                d["origen_recurso"] = f"App: {aplicacion.nombre}"
                vistos[key] = d

    pool_rds = Pool.query.filter_by(farm_id=farm.id, activo=True).first()
    if pool_rds:
        for ent in PoolEntitlement.query.filter_by(pool_id=pool_rds.id).all():
            key = (ent.usuario_o_grupo.lower(), ent.es_grupo)
            if key not in vistos:
                d = ent.to_dict()
                d["origen_recurso"] = f"Pool RDS: {pool_rds.nombre}"
                vistos[key] = d

    return enriquecer_entitlements_con_directorio(list(vistos.values()))


def autorizaciones_granja_para_usuario(directorio_usuario) -> dict:
    """Cruce por usuario: sus autorizaciones de Granja (Apps) más las VDI-VMs que YA
    tiene asignadas (Maquina.usuario_asignado), sin llamada nueva a Horizon -- mismo
    criterio que apps_asignadas_para_usuario en appvolumes_utils.py (App Volumes)."""
    candidatos = {
        _limpiar_usuario(directorio_usuario.username),
        _limpiar_usuario(directorio_usuario.sam_account_name),
    } - {""}
    if not candidatos:
        return {"aplicaciones": [], "vdi_vms": []}

    apps_ent = AplicacionEntitlement.query.filter(
        AplicacionEntitlement.usuario_o_grupo.in_(candidatos),
        AplicacionEntitlement.es_grupo == False,
    ).all()

    aplicaciones = []
    for ent in apps_ent:
        app_db = AplicacionPublicada.query.get(ent.aplicacion_id) if ent.aplicacion_id else None
        aplicaciones.append({
            "aplicacion_nombre": ent.aplicacion_nombre,
            "farm_nombre": app_db.farm.nombre if (app_db and app_db.farm) else "",
            "tipo_entitlement": ent.tipo_entitlement,
            "origen": ent.origen or "",
        })

    vdi_vms_map = {}
    for candidato in candidatos:
        for m in Maquina.query.filter(Maquina.usuario_asignado.ilike(candidato), Maquina.activo == True).all():
            vdi_vms_map[m.id] = m.to_dict()

    return {"aplicaciones": aplicaciones, "vdi_vms": list(vdi_vms_map.values())}
