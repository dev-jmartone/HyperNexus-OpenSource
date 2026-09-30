"""
scripts/limpiar_vdi_huerfanas_duplicadas.py
Desactiva filas VM_ESTATICA "fantasma" en `maquinas` que en realidad son el MISMO
objeto de vCenter que una VDI_POOL activa (mismo external_id, mismo origen, distinto
servidor_id) -- residuo de un fallo de matching Horizon<->vCenter puntual (coincide con
el reordenamiento de pools Horizon a la convención "-MZ" ya documentado en CLAUDE.md)
que ya no ocurre hoy (ver fix en _extraer_vcenter_cred, web/routes/inventario.py,
2026-09-08) pero cuya fila vieja nunca se limpiaba sola. Reportado por el usuario: VDIs
reales (vdi-*) apareciendo etiquetadas como "VM" en Inventario VDI.

No borra filas -- las desactiva (activo=False), igual que cualquier VM que deja de
aparecer en una extracción real, para no perder historial/auditoría asociado a ese id.

Uso:
    python scripts/limpiar_vdi_huerfanas_duplicadas.py            # dry-run, no escribe nada
    python scripts/limpiar_vdi_huerfanas_duplicadas.py --aplicar  # ejecuta (hace backup de la DB antes)
"""
import sys
import os
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import db, Maquina, registrar_auditoria


def _backup_db():
    origen = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "inventario.db")
    if not os.path.exists(origen):
        print(f"AVISO: no se encontró {origen} para respaldar -- ¿INVENTARIO_DB_PATH apunta a otro lado?")
        return None
    destino = origen + f".backup_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy2(origen, destino)
    print(f"Backup de la DB: {destino}")
    return destino


def run(aplicar: bool):
    app = create_app()
    with app.app_context():
        fantasmas = Maquina.query.filter(
            Maquina.activo == True,
            Maquina.tipo_provisionamiento == "VM_ESTATICA",
            Maquina.external_id.isnot(None),
            Maquina.external_id != "",
        ).all()

        a_desactivar = []
        for f in fantasmas:
            real = Maquina.query.filter(
                Maquina._origen_str == f._origen_str,
                Maquina.external_id == f.external_id,
                Maquina.servidor_id != f.servidor_id,
                Maquina.activo == True,
                Maquina.tipo_provisionamiento == "VDI_POOL",
            ).first()
            if real:
                a_desactivar.append((f, real))

        print(f"{len(a_desactivar)} filas VM_ESTATICA fantasma encontradas (mismo external_id que una VDI_POOL activa real).\n")
        for f, real in a_desactivar:
            print(f"  id={f.id:>5}  {f.nombre:<30} origen={f.origen:<5} ext_id={f.external_id:<12} -> real id={real.id} ({real.pool})")

        if aplicar:
            _backup_db()
            for f, _real in a_desactivar:
                f.activo = False
            registrar_auditoria(
                accion="limpiar_vdi_huerfanas_duplicadas",
                detalle=f"{len(a_desactivar)} filas VM_ESTATICA desactivadas por ser duplicado de una VDI_POOL real (mismo external_id)",
            )
            db.session.commit()
            print(f"\nAplicado: {len(a_desactivar)} filas desactivadas y confirmado.")
        else:
            print("\nDRY-RUN -- no se escribió nada. Correr con --aplicar para ejecutar de verdad.")


if __name__ == "__main__":
    run(aplicar="--aplicar" in sys.argv)
