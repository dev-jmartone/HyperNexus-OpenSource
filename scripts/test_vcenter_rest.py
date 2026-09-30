"""
scripts/test_vcenter_rest.py
Diagnóstico de conectividad y prueba de lectura ligera REST API vSphere 6.7/7.0/8.0.
Trae exactamente 1 solo dato por servidor de forma 100% segura (Solo Lectura).
"""
import os
import sys
import json
import ssl
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import create_app
from web.db import Servidor

def probar_rest_servidor(servidor, sample_user="administrator", sample_pwd="", sample_dom="CORP"):
    print(f"\n=======================================================")
    print(f"[TEST] PRUEBA DIAGNOSTICA REST API (Solo Lectura - 1 Registro)")
    print(f"Servidor: {servidor.nombre} ({servidor.host}) | Tipo: {servidor.tipo}")
    print(f"=======================================================")

    user = servidor.usuario or sample_user
    pwd = servidor.password or sample_pwd
    dom = servidor.dominio or sample_dom

    user_formats = []
    if dom:
        user_formats.append(f"{dom}\\{user}")
        user_formats.append(f"{user}@{dom}.local")
    user_formats.append(user)

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Endpoint 1: Auth vSphere 7.0/8.0 (/api/session) o vSphere 6.7 (/rest/com/vmware/cis/session)
    session_id = None
    auth_header = None
    api_flavor = ""

    for u_fmt in user_formats:
        if session_id:
            break
        print(f"1. Probando autenticacion REST... User: '{u_fmt}'")
        try:
            url_sess = f"https://{servidor.host}/api/session"
            req = urllib.request.Request(url_sess, method="POST")
            import base64
            creds = base64.b64encode(f"{u_fmt}:{pwd}".encode("utf-8")).decode("ascii")
            req.add_header("Authorization", f"Basic {creds}")

            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                token = json.loads(resp.read().decode("utf-8"))
                session_id = token if isinstance(token, str) else token.get("value")
                auth_header = {"vmware-api-session-id": session_id}
                api_flavor = "vSphere 7.0+ REST API (/api/vcenter/vm)"
                print(f"   [OK] Sesion creada exitosamente en /api/session! Token: {session_id[:12]}...")
                break
        except Exception as e1:
            try:
                url_sess = f"https://{servidor.host}/rest/com/vmware/cis/session"
                req = urllib.request.Request(url_sess, method="POST")
                import base64
                creds = base64.b64encode(f"{u_fmt}:{pwd}".encode("utf-8")).decode("ascii")
                req.add_header("Authorization", f"Basic {creds}")
                with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    session_id = data.get("value")
                    auth_header = {"vmware-api-session-id": session_id}
                    api_flavor = "vSphere 6.7 REST API (/rest/vcenter/vm)"
                    print(f"   [OK] Sesion creada exitosamente en /rest/com/vmware/cis/session! Token: {session_id[:12]}...")
                    break
            except Exception as e2:
                print(f"   [WARN] '{u_fmt}' falló en REST: v7 ({e1}) | v6.7 ({e2})")

    if not session_id:
        print(f"   [ERROR] No se pudo autenticar en endpoints REST de {servidor.host}")
        return

    # Endpoint 2: Traer 1 sola VM (Solo Lectura)
    if session_id:
        print(f"2. Solicitando 1 sola VM de prueba ({api_flavor})...")
        try:
            if "7.0+" in api_flavor:
                url_vm = f"https://{servidor.host}/api/vcenter/vm"
            else:
                url_vm = f"https://{servidor.host}/rest/vcenter/vm"
            
            req = urllib.request.Request(url_vm)
            req.add_header("vmware-api-session-id", session_id)
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                vms_data = json.loads(resp.read().decode("utf-8"))
                vm_list = vms_data.get("value") if isinstance(vms_data, dict) else vms_data
                
                if isinstance(vm_list, list) and len(vm_list) > 0:
                    sample_vm = vm_list[0]
                    print(f"   [EXITO TOTAL REST API]")
                    print(f"   Total VMs disponibles: {len(vm_list)}")
                    print(f"   Muestra de 1 VM recibida: {json.dumps(sample_vm, indent=2)}")
                else:
                    print(f"   [WARN] Respuesta recibida sin lista de VMs: {vms_data}")
        except Exception as e_vm:
            print(f"   [ERROR] Al consultar 1 VM: {e_vm}")


def main():
    app = create_app()
    with app.app_context():
        srvs = Servidor.query.filter_by(activo=True).all()
        vc_srvs = [s for s in srvs if s.tipo == "vcenter"]
        print(f"Iniciando prueba REST API de solo lectura en {len(vc_srvs)} servidores vCenter...")
        for s in vc_srvs:
            probar_rest_servidor(s)

if __name__ == "__main__":
    main()
