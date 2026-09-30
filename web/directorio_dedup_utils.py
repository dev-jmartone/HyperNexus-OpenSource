"""
web/directorio_dedup_utils.py
Utilidades para la detección y fusión segura de usuarios duplicados en DirectorioUsuario.
Identifica cuentas pertenecientes a la misma persona real mediante consulta en vivo a Active Directory.
"""
import os
import difflib
from typing import Optional, List, Dict, Tuple, Any
from web.db import db, DirectorioUsuario, MaquinaUsuarioDir, registrar_auditoria
from core.ad_client import ADClient


def es_candidato_duplicado(u1: DirectorioUsuario, u2: DirectorioUsuario) -> bool:
    """
    Filtra preliminarmente si dos filas DirectorioUsuario son sospechosas de ser la misma persona,
    evitando consultar AD para todas las combinaciones de la base de datos.
    """
    if u1.id == u2.id:
        return False

    # 1. Mismo nombre completo (normalizado)
    n1 = (u1.nombre_completo or "").strip().lower()
    n2 = (u2.nombre_completo or "").strip().lower()
    if n1 and n2 and n1 == n2:
        return True

    # 2. Mismo email (normalizado)
    e1 = (u1.email or "").strip().lower()
    e2 = (u2.email or "").strip().lower()
    if e1 and e2 and e1 == e2:
        return True

    # 3. Usernames y sam_account_names coincidentes o parecidos
    un1 = (u1.username or "").strip().lower()
    un2 = (u2.username or "").strip().lower()
    sam1 = (u1.sam_account_name or "").strip().lower()
    sam2 = (u2.sam_account_name or "").strip().lower()

    if sam1 and sam2 and sam1 == sam2:
        return True
    if sam1 and sam1 == un2:
        return True
    if sam2 and sam2 == un1:
        return True

    if un1 and un2:
        if un1 == un2:
            return True
        if (len(un1) >= 3 and un1 in un2) or (len(un2) >= 3 and un2 in un1):
            return True
        if difflib.SequenceMatcher(None, un1, un2).ratio() >= 0.75:
            return True

    return False


def filtrar_candidatos_duplicados() -> List[Tuple[DirectorioUsuario, DirectorioUsuario]]:
    """
    Retorna pares sospechosos de DirectorioUsuario (u1, u2) con u1.id < u2.id.
    """
    usuarios = DirectorioUsuario.query.order_by(DirectorioUsuario.id.asc()).all()
    candidatos = []
    n = len(usuarios)
    for i in range(n):
        for j in range(i + 1, n):
            u1 = usuarios[i]
            u2 = usuarios[j]
            if es_candidato_duplicado(u1, u2):
                candidatos.append((u1, u2))
    return candidatos


def elegir_canonico(
    u1: DirectorioUsuario,
    u2: DirectorioUsuario,
    info1: Optional[Dict[str, Any]] = None,
    info2: Optional[Dict[str, Any]] = None,
) -> Tuple[DirectorioUsuario, DirectorioUsuario]:
    """
    Determina cuál de los dos usuarios debe conservarse como canónico y cuál debe ser absorbido.
    Preferir la fila con sam_account_name poblado, activo_ad=True, coincidencia con sAMAccountName real de AD,
    más campos completos y vinculaciones activas.
    """
    ad_sam = None
    if info1 and info1.get("sam_account_name"):
        ad_sam = info1["sam_account_name"].strip().lower()
    elif info2 and info2.get("sam_account_name"):
        ad_sam = info2["sam_account_name"].strip().lower()

    def _puntuar(u: DirectorioUsuario, info: Optional[Dict[str, Any]]) -> int:
        score = 0
        un = (u.username or "").strip().lower()

        # Si el username local coincide exactamente con el sAMAccountName real de AD
        if ad_sam and un == ad_sam:
            score += 50

        # sam_account_name poblado localmente
        if (u.sam_account_name or "").strip():
            score += 20

        # activo en AD
        if u.activo_ad:
            score += 10

        # Cantidad de campos completos
        campos = [u.nombre_completo, u.email, u.departamento, u.empresa, u.telefono, u.notas]
        score += sum(1 for c in campos if (c or "").strip())

        # Vinculaciones con VMs
        vinculos_count = MaquinaUsuarioDir.query.filter_by(directorio_usuario_id=u.id).count()
        score += vinculos_count * 5

        return score

    p1 = _puntuar(u1, info1)
    p2 = _puntuar(u2, info2)

    if p1 > p2:
        return u1, u2
    elif p2 > p1:
        return u2, u1
    else:
        # Desempate: preferir la fila más reciente (ID mayor)
        if u1.id >= u2.id:
            return u1, u2
        else:
            return u2, u1


def detectar_duplicados_confirmados_ad(ad_client: Optional[ADClient] = None) -> List[Dict[str, Any]]:
    """
    Consulta en vivo a Active Directory para confirmar qué pares de usuarios candidatos
    son efectivamente la misma persona real (mismo sAMAccountName Y mismo email en AD).
    """
    candidatos = filtrar_candidatos_duplicados()
    if not candidatos:
        return []

    # Recolectar usernames/sams para la consulta masiva en AD
    usernames_set = set()
    for u1, u2 in candidatos:
        if u1.username:
            usernames_set.add(u1.username)
        if u1.sam_account_name:
            usernames_set.add(u1.sam_account_name)
        if u2.username:
            usernames_set.add(u2.username)
        if u2.sam_account_name:
            usernames_set.add(u2.sam_account_name)

    if not ad_client:
        ad_client = ADClient(domain=os.environ.get("AD_DOMAIN", "corp.local"))

    try:
        res_ad = ad_client.verificar_usuarios(list(usernames_set))
    except Exception:
        res_ad = {}

    confirmados = []
    pares_vistos = set()

    for u1, u2 in candidatos:
        # Obtener info AD de cada usuario
        info1 = res_ad.get((u1.username or "").lower()) or res_ad.get((u1.sam_account_name or "").lower())
        info2 = res_ad.get((u2.username or "").lower()) or res_ad.get((u2.sam_account_name or "").lower())

        if not info1 or not info2:
            continue

        if not info1.get("encontrado_ad") or not info2.get("encontrado_ad"):
            continue

        sam1 = (info1.get("sam_account_name") or "").strip().lower()
        sam2 = (info2.get("sam_account_name") or "").strip().lower()
        email1 = (info1.get("email") or "").strip().lower()
        email2 = (info2.get("email") or "").strip().lower()

        # Confirmación estricta contra AD: mismo sAMAccountName Y mismo Email real
        if sam1 and sam2 and sam1 == sam2 and email1 and email2 and email1 == email2:
            canonico, absorbido = elegir_canonico(u1, u2, info1, info2)

            # Evitar registrar la misma pareja invertida
            pair_key = tuple(sorted([canonico.id, absorbido.id]))
            if pair_key in pares_vistos:
                continue
            pares_vistos.add(pair_key)

            vms_canonico = MaquinaUsuarioDir.query.filter_by(directorio_usuario_id=canonico.id).count()
            vms_absorbido = MaquinaUsuarioDir.query.filter_by(directorio_usuario_id=absorbido.id).count()

            item = {
                "pair_id": f"{canonico.id}_{absorbido.id}",
                "nombre_persona": info1.get("nombre_completo") or canonico.nombre_completo or absorbido.nombre_completo or "",
                "ad_sam_account_name": info1.get("sam_account_name") or "",
                "ad_email": info1.get("email") or "",
                "resumen": f"{canonico.nombre_completo or canonico.username}: {absorbido.username} -> {canonico.username}",
                "canonico": {
                    **canonico.to_dict(),
                    "vms_count": vms_canonico,
                },
                "absorbido": {
                    **absorbido.to_dict(),
                    "vms_count": vms_absorbido,
                },
            }
            confirmados.append(item)

    return confirmados


def fusionar_directorio_usuarios(
    canonico_id: int,
    absorbido_id: int,
    user_id: Optional[int] = None,
    username_req: Optional[str] = None,
    ip: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ejecuta la fusión de un par de usuarios en DirectorioUsuario:
    1. Re-apunta las relaciones MaquinaUsuarioDir evitando duplicar vínculos.
    2. Copia a la fila canónica campos vacíos que tenga la fila absorbida.
    3. Elimina la fila absorbida.
    4. Registra la acción en la tabla de auditoría.
    """
    if canonico_id == absorbido_id:
        return {"ok": False, "error": "Los IDs de usuario canónico y absorbido deben ser distintos."}

    canonico = DirectorioUsuario.query.get(canonico_id)
    absorbido = DirectorioUsuario.query.get(absorbido_id)

    if not canonico or not absorbido:
        return {"ok": False, "error": "Uno o ambos usuarios no existen en la base de datos."}

    username_canonico = canonico.username
    username_absorbido = absorbido.username

    # 1. Re-apuntar vinculaciones M:M (MaquinaUsuarioDir)
    vinculos_absorbido = MaquinaUsuarioDir.query.filter_by(directorio_usuario_id=absorbido.id).all()
    repointed_count = 0
    deleted_links_count = 0

    for vinc in vinculos_absorbido:
        # Verificar si la máquina ya está vinculada al usuario canónico
        existente = MaquinaUsuarioDir.query.filter_by(
            maquina_id=vinc.maquina_id, directorio_usuario_id=canonico.id
        ).first()

        if existente:
            # Eliminar vínculo duplicado
            db.session.delete(vinc)
            deleted_links_count += 1
        else:
            # Re-apuntar vínculo al usuario canónico
            vinc.directorio_usuario_id = canonico.id
            repointed_count += 1

    # 2. Copiar campos incompletos desde la fila absorbida a la canónica
    campos_a_copiar = ["sam_account_name", "nombre_completo", "email", "departamento", "empresa", "telefono", "notas"]
    copiados = []
    for campo in campos_a_copiar:
        val_absorbido = getattr(absorbido, campo)
        val_canonico = getattr(canonico, campo)

        if val_absorbido and not val_canonico:
            setattr(canonico, campo, val_absorbido)
            copiados.append(campo)

    if absorbido.activo_ad and not canonico.activo_ad:
        canonico.activo_ad = True

    # 3. Eliminar la fila absorbida
    db.session.delete(absorbido)

    # 4. Registrar auditoría
    detalle_auditoria = (
        f"Fusionado usuario ID {absorbido_id} ('{username_absorbido}') dentro de "
        f"ID {canonico_id} ('{username_canonico}'). "
        f"Vínculos re-apuntados: {repointed_count}, vínculos duplicados eliminados: {deleted_links_count}."
    )
    if copiados:
        detalle_auditoria += f" Campos copiados: {', '.join(copiados)}."

    registrar_auditoria(
        accion="fusionar_directorio_usuario",
        recurso="DirectorioUsuario",
        recurso_id=canonico.id,
        detalle=detalle_auditoria,
        usuario_id=user_id,
        username=username_req,
        ip=ip,
        resultado="exito",
    )

    db.session.commit()

    return {
        "ok": True,
        "canonico_id": canonico.id,
        "absorbido_id": absorbido_id,
        "mensaje": f"Fusión exitosa: '{username_absorbido}' (ID {absorbido_id}) fue absorbido por '{username_canonico}' (ID {canonico.id}).",
        "vinculos_reapuntados": repointed_count,
        "campos_copiados": copiados,
    }
