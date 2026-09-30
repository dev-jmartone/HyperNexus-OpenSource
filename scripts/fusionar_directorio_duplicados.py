"""
scripts/fusionar_directorio_duplicados.py
Fusiona duplicados en directorio_usuarios causados por un bug ya corregido en
core/horizon_rest.py: cuando Horizon no devolvía login_name/UPN para un SID, se
usaba display_name ("Jose David Martone Aguais") como Maquina.usuario_asignado,
que terminaba creando un DirectorioUsuario con el nombre completo como username
en vez del login real -- duplicando a la persona junto con su fila correcta.

Empareja por email: si una fila con espacio en el username tiene email
"aluque@dominio.com" y existe otra fila con username="aluque", son la misma
persona. Copia a la fila "limpia" (username real, sin espacio) los campos que
le falten, migra sus vínculos MaquinaUsuarioDir, y borra la fila con nombre
completo como username.

No toca los casos ambiguos (sin email, o email sin fila limpia correspondiente)
-- esos se listan aparte para revisión manual.

Uso:
    python scripts/fusionar_directorio_duplicados.py            # dry-run, no escribe nada
    python scripts/fusionar_directorio_duplicados.py --aplicar  # ejecuta la fusión
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import db, DirectorioUsuario, MaquinaUsuarioDir, registrar_auditoria

CAMPOS_A_COMPLETAR = ["nombre_completo", "email", "empresa", "departamento", "telefono"]


def run(aplicar: bool):
    app = create_app()
    with app.app_context():
        todos = DirectorioUsuario.query.all()
        por_username_lower = {}
        for u in todos:
            por_username_lower.setdefault(u.username.strip().lower(), []).append(u)

        con_espacio = [u for u in todos if " " in u.username.strip()]

        pares = []          # (sucio, limpio) -- fusión segura
        sin_match = []       # tiene email pero no hay fila limpia correspondiente
        sin_email = []       # no tiene email, no se puede resolver automáticamente
        ambiguos = []        # el email matchea más de una fila limpia (no debería pasar, defensivo)

        for u in con_espacio:
            email = (u.email or "").strip()
            if not email or "@" not in email:
                sin_email.append(u)
                continue
            local = email.split("@")[0].strip().lower()
            if not local:
                sin_email.append(u)
                continue
            candidatos = [c for c in por_username_lower.get(local, []) if c.id != u.id]
            if not candidatos:
                sin_match.append(u)
            elif len(candidatos) > 1:
                ambiguos.append((u, candidatos))
            else:
                pares.append((u, candidatos[0]))

        print(f"Total directorio_usuarios: {len(todos)}")
        print(f"Filas con espacio en username (nombre completo usado como login): {len(con_espacio)}")
        print(f"  -> fusionables automáticamente por email: {len(pares)}")
        print(f"  -> con email pero SIN fila limpia (única fuente de esa persona, no se tocan): {len(sin_match)}")
        print(f"  -> sin email (no resoluble automáticamente, no se tocan): {len(sin_email)}")
        print(f"  -> ambiguos (email matchea >1 fila limpia, revisar a mano): {len(ambiguos)}")
        print()

        vinculos_migrados = 0
        vinculos_saltados = 0

        for sucio, limpio in pares:
            campos_copiados = []
            for campo in CAMPOS_A_COMPLETAR:
                val_limpio = getattr(limpio, campo)
                val_sucio = getattr(sucio, campo)
                if (not val_limpio or (isinstance(val_limpio, str) and not val_limpio.strip()) or val_limpio == "—") and val_sucio:
                    campos_copiados.append(f"{campo}={val_sucio!r}")
                    if aplicar:
                        setattr(limpio, campo, val_sucio)

            vinculos = MaquinaUsuarioDir.query.filter_by(directorio_usuario_id=sucio.id).all()
            for v in vinculos:
                existente = MaquinaUsuarioDir.query.filter_by(
                    maquina_id=v.maquina_id, directorio_usuario_id=limpio.id
                ).first()
                if existente:
                    vinculos_saltados += 1
                    if aplicar:
                        db.session.delete(v)
                else:
                    vinculos_migrados += 1
                    if aplicar:
                        v.directorio_usuario_id = limpio.id

            print(f"[{'APLICADO' if aplicar else 'dry-run'}] '{sucio.username}' (id={sucio.id}) -> "
                  f"'{limpio.username}' (id={limpio.id}) | copia: {', '.join(campos_copiados) or 'nada nuevo'} "
                  f"| vínculos a migrar: {len(vinculos)}")

            if aplicar:
                db.session.delete(sucio)

        if aplicar:
            registrar_auditoria(
                accion="fusionar_directorio_duplicados",
                detalle=f"pares_fusionados={len(pares)}, vinculos_migrados={vinculos_migrados}, "
                        f"vinculos_ya_existentes_descartados={vinculos_saltados}",
            )
            db.session.commit()
            print(f"\nAplicado: {len(pares)} pares fusionados, {vinculos_migrados} vínculos migrados, "
                  f"{vinculos_saltados} vínculos duplicados descartados.")
        else:
            print(f"\nDRY-RUN -- no se escribió nada. {vinculos_migrados} vínculos se migrarían, "
                  f"{vinculos_saltados} ya existen en destino y se descartarían.")
            print("Correr con --aplicar para ejecutar de verdad.")

        if sin_match:
            print(f"\n--- {len(sin_match)} filas con email pero sin par limpio (revisar si el login real ya se sincronizó) ---")
            for u in sin_match[:30]:
                print(f"  id={u.id} username={u.username!r} email={u.email!r} empresa={u.empresa!r}")
            if len(sin_match) > 30:
                print(f"  ... y {len(sin_match) - 30} más")

        if sin_email:
            print(f"\n--- {len(sin_email)} filas sin email, sin forma automática de resolver ---")
            for u in sin_email[:30]:
                print(f"  id={u.id} username={u.username!r} empresa={u.empresa!r}")
            if len(sin_email) > 30:
                print(f"  ... y {len(sin_email) - 30} más")

        if ambiguos:
            print(f"\n--- {len(ambiguos)} casos ambiguos (revisar a mano) ---")
            for u, cands in ambiguos:
                print(f"  id={u.id} username={u.username!r} -> candidatos: {[(c.id, c.username) for c in cands]}")


if __name__ == "__main__":
    run(aplicar="--aplicar" in sys.argv)
