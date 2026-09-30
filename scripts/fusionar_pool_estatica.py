"""
scripts/fusionar_pool_estatica.py
Fusiona el pool sintético "Sin Pool (vCenter)" (creado por web/routes/inventario.py
para VMs de vCenter sin correspondencia en ningún Desktop Pool de Horizon) dentro de
"Estática" -- misma categoría real, dos filas separadas por un bug ya corregido en
código (ver _POOLS_SIN_ASIGNAR en web/kpi_utils.py, que sí reconocía ambas formas
para clasificación pero nunca las unificaba en la tabla `pools`).

También borra pools huérfanas sin VMs ni autorizaciones:
  - "POOL-DESKTOPS": datos de prueba de scripts/test_redesign.py que quedaron en la DB real.
  - "Sin Pool (vCenter REST)": generada por una función muerta ya eliminada del código
    (_extraer_vcenter_rest_completo, nunca la llamaba el pipeline real).
  - "TEST-POOL-OBSOLETE": sin referencia en código, sin auditoría, sin VMs ni autorizaciones.

Uso:
    python scripts/fusionar_pool_estatica.py            # dry-run, no escribe nada
    python scripts/fusionar_pool_estatica.py --aplicar   # ejecuta
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import db, Pool, Maquina, registrar_auditoria

POOLS_A_BORRAR_SIEMPRE = ["POOL-DESKTOPS", "Sin Pool (vCenter REST)", "TEST-POOL-OBSOLETE"]


def run(aplicar: bool):
    app = create_app()
    with app.app_context():
        origen = Pool.query.filter_by(nombre="Sin Pool (vCenter)").first()
        destino = Pool.query.filter_by(nombre="Estática").first()

        if not origen:
            print("No existe pool 'Sin Pool (vCenter)' -- nada que fusionar.")
        elif not destino:
            print("No existe pool 'Estática' -- no se puede fusionar, abortando fusión (se procesan igual los borrados de abajo).")
        else:
            maquinas = Maquina.query.filter_by(pool_id=origen.id).all()
            print(f"Fusionando '{origen.nombre}' (id={origen.id}, {len(maquinas)} VMs) -> "
                  f"'{destino.nombre}' (id={destino.id})")
            for m in maquinas:
                if aplicar:
                    m.pool_id = destino.id
                    m._pool_str = "Estática"
            if aplicar:
                db.session.delete(origen)

        print()
        for nombre in POOLS_A_BORRAR_SIEMPRE:
            p = Pool.query.filter_by(nombre=nombre).first()
            if not p:
                print(f"'{nombre}': no existe, nada que hacer.")
                continue
            n_vms = Maquina.query.filter_by(pool_id=p.id).count()
            if n_vms:
                print(f"'{nombre}' (id={p.id}): TIENE {n_vms} VMs asignadas -- NO se borra, revisar a mano.")
                continue
            print(f"'{nombre}' (id={p.id}): 0 VMs -- {'borrando' if aplicar else 'se borraría'}.")
            if aplicar:
                db.session.delete(p)

        if aplicar:
            registrar_auditoria(
                accion="fusionar_limpiar_pools_sinteticas",
                detalle="Sin Pool (vCenter) -> Estática; borradas POOL-DESKTOPS, "
                        "Sin Pool (vCenter REST), TEST-POOL-OBSOLETE (0 VMs)",
            )
            db.session.commit()
            print("\nAplicado y confirmado.")
        else:
            print("\nDRY-RUN -- no se escribió nada. Correr con --aplicar para ejecutar de verdad.")


if __name__ == "__main__":
    run(aplicar="--aplicar" in sys.argv)
