# Registra o add-in Scan 3D no SolidWorks. Auto-eleva (UAC) se necessario.
$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
$admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $admin) {
    Write-Host "Elevando (confirme no UAC)..."
    $argumentos = @("-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
    $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList $argumentos
    if ($p.ExitCode -eq 0) { Write-Host "Add-in registrado com sucesso." }
    else { Write-Host "Falhou (codigo $($p.ExitCode)). Veja a janela elevada." }
    exit $p.ExitCode
}

$dll = Join-Path $PSScriptRoot "bin\Release\SwScanAddin.dll"
if (-not (Test-Path $dll)) { throw "Compile antes: dotnet build -c Release (esperado: $dll)" }
$regasm = "$env:windir\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"
& $regasm $dll /codebase
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: RegAsm retornou $LASTEXITCODE - add-in NAO registrado."
    Start-Sleep 8
    exit $LASTEXITCODE
}
Write-Host "Add-in registrado. SolidWorks > Ferramentas > Suplementos > marque Scan 3D."
Start-Sleep 3
exit 0
