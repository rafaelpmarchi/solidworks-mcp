# Remove o registro do add-in Claude (rodar como ADMINISTRADOR).
$ErrorActionPreference = "Stop"
$dll = Join-Path $PSScriptRoot "bin\Release\SwClaudeAddin.dll"
$regasm = "$env:windir\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"
& $regasm $dll /unregister
Write-Host "Add-in removido."
