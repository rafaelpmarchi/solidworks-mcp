# Registra o add-in Claude no SolidWorks (rodar como ADMINISTRADOR).
$ErrorActionPreference = "Stop"
$dll = Join-Path $PSScriptRoot "bin\Release\SwClaudeAddin.dll"
if (-not (Test-Path $dll)) { throw "Compile antes: dotnet build -c Release (esperado: $dll)" }
$regasm = "$env:windir\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"
& $regasm $dll /codebase
Write-Host "Add-in registrado. Abra o SolidWorks -> Ferramentas -> Suplementos -> 'Claude'."
