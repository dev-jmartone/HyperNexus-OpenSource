"""
core/ad_client.py
Módulo de consulta y verificación de usuarios directamente en Active Directory (AD).
Utiliza PowerShell / Get-ADUser con fallbacks para obtener:
- Estado de cuenta (Enabled / Bloqueado / Existe en AD)
- Nombre completo (DisplayName)
- Email (Mail / UserPrincipalName)
- Empresa (Company)
- Departamento (Department)
- Teléfono (TelephoneNumber / mobile)
"""
import json
import os
import subprocess
import sys
import uuid


class ADClient:
    """Cliente para consultas masivas e individuales a Active Directory."""

    def __init__(self, domain: str = None, log_callback=None):
        self.domain = domain or os.environ.get("AD_DOMAIN", "corp.local")
        self._log = log_callback or (lambda msg: print(msg, flush=True))

    def log(self, msg: str):
        self._log(msg)

    def verificar_usuarios(self, usernames: list[str]) -> dict[str, dict]:
        """
        Consulta una lista de usernames en Active Directory en lotes.
        Returns:
            dict mapping username (lower) -> info dict
        """
        if not usernames:
            return {}

        usernames_clean = [u.strip() for u in usernames if u and u.strip()]
        if not usernames_clean:
            return {}

        if os.environ.get("DEMO_MODE", "0") == "1":
            self.log(f"[AD Client Demo] Verificando {len(usernames_clean)} usuarios en Active Directory simulado ({self.domain})...")
            resultados_demo = {}
            for u in usernames_clean:
                clean_name = u.replace(".", " ").title()
                val = {
                    "encontrado_ad": True,
                    "sam_account_name": u,
                    "nombre_completo": clean_name,
                    "email": f"{u}@{self.domain}",
                    "empresa": "Acme Corp",
                    "departamento": "Technology & Ops",
                    "telefono": "+1-555-0142",
                    "activo_ad": True,
                }
                resultados_demo[u.lower()] = val
                resultados_demo[u.lower().split("@")[0]] = val
            return resultados_demo

        self.log(f"[AD Client] Consultando {len(usernames_clean)} usuarios en Active Directory ({self.domain})...")

        script_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
        )
        os.makedirs(script_dir, exist_ok=True)

        # Dividir en lotes de 100 para evitar límites de comando en PowerShell
        chunk_size = 100
        resultados_totales = {}

        for i in range(0, len(usernames_clean), chunk_size):
            chunk = usernames_clean[i:i + chunk_size]

            # Nombres de archivo únicos por lote (evita pisarse si dos verificaciones
            # corren en paralelo) y con sufijo aleatorio impredecible.
            token = uuid.uuid4().hex
            script_path = os.path.join(script_dir, f"_ad_query_{token}.ps1")
            json_path = os.path.join(script_dir, f"_ad_query_{token}.json")

            # Los usernames NUNCA se interpolan en el texto del script — antes iban
            # embebidos crudos dentro de un string PowerShell de comillas simples
            # ($rawInput = '{json.dumps(chunk)}'), y como JSON no escapa comillas
            # simples, un username con ' rompía el string y el resto se ejecutaba como
            # código PowerShell arbitrario (RCE). Ahora se escriben a un archivo JSON
            # aparte y el script SOLO lee ese archivo — los usernames nunca forman
            # parte del texto del script en sí, así que no hay contexto que romper.
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(chunk, f, ensure_ascii=False)

            ps_script = f"""
$Domain = '{self.domain}'
$rawInput = Get-Content -Raw -Path '{json_path}' -Encoding UTF8
$usernames = ConvertFrom-Json $rawInput

$results = @()

foreach ($u in $usernames) {{
    $cleanU = $u.Trim()
    if ($cleanU -like "*\\*") {{
        $cleanU = $cleanU.Split("\\")[-1]
    }}
    if ($cleanU -like "*@*") {{
        $cleanU = $cleanU.Split("@")[0]
    }}

    $adUser = $null
    try {{
        $adUser = Get-ADUser -Filter "samAccountName -eq '$cleanU'" -Server $Domain -Properties DisplayName, Mail, Company, Department, TelephoneNumber, Enabled -ErrorAction SilentlyContinue
    }} catch {{}}

    if (-not $adUser) {{
        try {{
            $adUser = Get-ADUser -Filter "UserPrincipalName -like '$cleanU*'" -Server $Domain -Properties DisplayName, Mail, Company, Department, TelephoneNumber, Enabled -ErrorAction SilentlyContinue | Select-Object -First 1
        }} catch {{}}
    }}

    if (-not $adUser) {{
        try {{
            $adUser = Get-ADUser -Filter "Name -like '*$cleanU*'" -Server $Domain -Properties DisplayName, Mail, Company, Department, TelephoneNumber, Enabled -ErrorAction SilentlyContinue | Select-Object -First 1
        }} catch {{}}
    }}

    if ($adUser) {{
        $mail = $adUser.Mail
        if (-not $mail) {{ $mail = $adUser.UserPrincipalName }}

        $phone = $adUser.TelephoneNumber
        if (-not $phone) {{ $phone = "" }}

        $results += [PSCustomObject]@{{
            SearchTerm     = $u
            EncontradoEnAD = $true
            SamAccountName = $adUser.SamAccountName
            DisplayName    = $adUser.DisplayName
            Mail           = $mail
            Company        = $adUser.Company
            Department     = $adUser.Department
            Telephone      = $phone
            Enabled        = [bool]$adUser.Enabled
        }}
    }} else {{
        $results += [PSCustomObject]@{{
            SearchTerm     = $u
            EncontradoEnAD = $false
            SamAccountName = $u
            DisplayName    = $null
            Mail           = $null
            Company        = $null
            Department     = $null
            Telephone      = $null
            Enabled        = $false
        }}
    }}
}}

$results | ConvertTo-Json -Depth 5 -Compress
"""
            with open(script_path, "w", encoding="utf-8-sig") as f:
                f.write(ps_script)

            cmd = [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", script_path
            ]

            try:
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
                if res.stdout.strip():
                    raw = res.stdout.strip()
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            parsed = [parsed]
                        for item in parsed:
                            st = item.get("SearchTerm", "").lower()
                            sam = item.get("SamAccountName", "").lower()
                            val = {
                                "encontrado_ad": item.get("EncontradoEnAD", False),
                                "sam_account_name": item.get("SamAccountName", ""),
                                "nombre_completo": item.get("DisplayName") or "",
                                "email": item.get("Mail") or "",
                                "empresa": item.get("Company") or "",
                                "departamento": item.get("Department") or "",
                                "telefono": str(item.get("Telephone") or "").strip(),
                                "activo_ad": bool(item.get("Enabled", False)),
                            }
                            resultados_totales[st] = val
                            if sam:
                                resultados_totales[sam] = val
                    except json.JSONDecodeError as e:
                        self.log(f"[AD Client Error] Error al parsear JSON de PowerShell: {e}")
            except Exception as e:
                self.log(f"[AD Client Error] Excepción al ejecutar consulta AD: {e}")
                if os.environ.get("DEMO_MODE", "0") == "1":
                    for u in chunk:
                        clean_name = u.replace(".", " ").title()
                        val = {
                            "encontrado_ad": True,
                            "sam_account_name": u,
                            "nombre_completo": clean_name,
                            "email": f"{u}@{self.domain}",
                            "empresa": "Acme Corp",
                            "departamento": "Technology & Ops",
                            "telefono": "+1-555-0142",
                            "activo_ad": True,
                        }
                        resultados_totales[u.lower()] = val
                        resultados_totales[u.lower().split("@")[0]] = val
            finally:
                for tmp_path in (script_path, json_path):
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass

        self.log(f"[AD Client] Consulta completada. {sum(1 for v in resultados_totales.values() if v.get('encontrado_ad'))} usuarios verificados en AD.")
        return resultados_totales
