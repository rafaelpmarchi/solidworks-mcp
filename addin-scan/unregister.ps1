# Remove o registro do add-in Scan 3D. Auto-eleva (UAC) se necessario.
$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
$admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $admin) {
    Write-Host "Elevando (confirme no UAC)..."
    $argumentos = @("-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
    $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList $argumentos
    exit $p.ExitCode
}

$dll = Join-Path $PSScriptRoot "bin\Release\SwScanAddin.dll"
$regasm = "$env:windir\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"
& $regasm $dll /unregister
Write-Host "Add-in Scan 3D removido do registro."
Start-Sleep 3
exit $LASTEXITCODE
