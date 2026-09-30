
param (
    [string]$UserLogonName   # Ej: usuario@dominio
)

try {
    $ErrorActionPreference = "Stop"
    trap {
        Write-Host "`n[!] Ocurrio un error inesperado:`n$_" -ForegroundColor Red
        Write-Host "`nPresione cualquier tecla para salir..."
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        break
    }

    $Host.UI.RawUI.WindowTitle = "Consulta Estado de Usuario de Active Directory"

    if ([string]::IsNullOrWhiteSpace($UserLogonName)) {
        Write-Host "========== ESTADO DE USUARIO ==========" -ForegroundColor Cyan
        $UserLogonName = Read-Host "Ingrese el nombre de inicio de sesion (UPN - ej: usuario@dominio)"
        
        if ([string]::IsNullOrWhiteSpace($UserLogonName)) {
            return
        }
    }
    $Domain = if ($env:AD_DOMAIN) { $env:AD_DOMAIN } else { "corp.local" }

# =============================
# Obtener usuario por UPN
# =============================
function Get-ADUserByUPN {
    param (
        [string]$UPN
    )

    return Get-ADUser -Filter "UserPrincipalName -eq '$UPN'" `
        -Server $Domain `
        -Properties DisplayName, Description, Enabled,
                    LockedOut,
                    AccountExpirationDate, PasswordLastSet,
                    PasswordNeverExpires, PasswordNotRequired,
                    CannotChangePassword, LastLogonDate, MemberOf
}

# =============================
# Información de contraseña
# =============================
function Get-PasswordInfo {
    param (
        [Microsoft.ActiveDirectory.Management.ADUser]$User
    )

    if ($User.PasswordNeverExpires) {
        return @{
            Expires        = "Nunca"
            Changeable     = "Nunca"
            StatusReadable = "Nunca expira"
            Color          = "Neutral"
        }
    }

    try {
        $policy = Get-ADUserResultantPasswordPolicy -Identity $User -Server $Domain
    } catch {
        $policy = $null
    }

    if (-not $policy) {
        try {
            $policy = Get-ADDefaultDomainPasswordPolicy -Server $Domain
        } catch {
            $policy = $null
        }
    }

    if ($policy -and $User.PasswordLastSet) {

        $expires  = $User.PasswordLastSet + $policy.MaxPasswordAge
        $change   = $User.PasswordLastSet + $policy.MinPasswordAge
        $daysDiff = [math]::Floor(($expires - (Get-Date)).TotalDays)

        if ($daysDiff -lt 0) {
            $status = "Vencida hace $([math]::Abs($daysDiff)) días"
            $color  = "Red"
        }
        elseif ($daysDiff -eq 0) {
            $status = "Vence hoy"
            $color  = "Red"
        }
        elseif ($daysDiff -le 7) {
            $status = "Vigente – vence en $daysDiff días"
            $color  = "Yellow"
        }
        else {
            $status = "Vigente – vence en $daysDiff días"
            $color  = "Green"
        }

        return @{
            Expires        = $expires
            Changeable     = $change
            StatusReadable = $status
            Color          = $color
        }
    }

    return @{
        Expires        = "Según política de dominio"
        Changeable     = "Según política de dominio"
        StatusReadable = "Según política de dominio"
        Color          = "Neutral"
    }
}

# =============================
# Construir objeto diagnóstico
# =============================
function Get-UserDiagnosticTable {
    param (
        [Microsoft.ActiveDirectory.Management.ADUser]$User
    )

    $pwd = Get-PasswordInfo -User $User

    $groupsText = ($User.MemberOf |
        ForEach-Object { ($_ -split ',')[0] -replace 'CN=', '' } |
        Sort-Object) -join '; '

    return @{
        Table = [PSCustomObject]@{
            "Usuario (samAccountName)"        	= $User.SamAccountName
            "Nombre de inicio de sesión (UPN)"	= $User.UserPrincipalName
            "Cuenta activa"                  	= if ($User.Enabled) { "Sí" } else { "No" }
            "Cuenta bloqueada"               	= if ($User.LockedOut) { "Sí" } else { "No" }
            "Estado contraseña"              	= $pwd.StatusReadable
            "Contraseña expira"              	= $pwd.Expires
            "Contraseña modificable"         	= $pwd.Changeable
            "Último inicio de sesión"        	= $User.LastLogonDate
            "Cuenta expira"                  	= if ($User.AccountExpirationDate) { $User.AccountExpirationDate } else { "Nunca" }
            "Puede cambiar contraseña"       	= if ($User.CannotChangePassword) { "No" } else { "Sí" }
            "Contraseña requerida"           	= if ($User.PasswordNotRequired) { "No" } else { "Sí" }
            "Grupos"                         	= $groupsText
        }
        PwdColor     = $pwd.Color
        LockedColor  = if ($User.LockedOut) { "Red" } else { "Green" }
    }
}

# =============================
# Mostrar resultado en consola
# =============================
function Show-UserDiagnostic {
    param (
        [pscustomobject]$Table,
        [string]$PwdColor,
        [string]$LockedColor
    )

    foreach ($prop in $Table.PSObject.Properties) {

        if ($prop.Name -eq "Estado contraseña") {
            Write-Host ("{0,-30} : {1}" -f $prop.Name, $prop.Value) -ForegroundColor $PwdColor
        }
        elseif ($prop.Name -eq "Cuenta bloqueada") {
            Write-Host ("{0,-30} : {1}" -f $prop.Name, $prop.Value) -ForegroundColor $LockedColor
        }
        else {
            Write-Host ("{0,-30} : {1}" -f $prop.Name, $prop.Value)
        }
    }
}

# =============================
# Ejecución principal
# =============================

$user = Get-ADUserByUPN -UPN $UserLogonName

if (-not $user) {
    Write-Host "`n[X] Usuario no encontrado" -ForegroundColor Red
    Write-Host "El nombre de inicio de sesión ingresado no existe en Active Directory."
    Write-Host "Formato esperado: usuario@dominio`n"
}
else {
    $result = Get-UserDiagnosticTable -User $user
    Show-UserDiagnostic `
        -Table $result.Table `
        -PwdColor $result.PwdColor `
        -LockedColor $result.LockedColor
}

    Write-Host "`nPresione cualquier tecla para salir..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

} finally {
    # Auto-borrado del script (.ps1) y su launcher (.vbs) obligatorio, siempre se ejecuta
    if ($PSCommandPath) { Remove-Item -Path $PSCommandPath -Force -ErrorAction SilentlyContinue }
    Remove-Item -Path "C:\run_estado.vbs" -Force -ErrorAction SilentlyContinue
}
