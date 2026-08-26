# Wrapper: roda o registro e grava log ao lado (para diagnóstico).
$log = Join-Path $PSScriptRoot "register.log"
try {
    $dll = Join-Path $PSScriptRoot "bin\Release\SwClaudeAddin.dll"
    if (-not (Test-Path $dll)) { throw "DLL nao encontrada: $dll" }
    $regasm = "$env:windir\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"
    $out = & $regasm $dll /codebase 2>&1 | Out-String
    "EXIT=$LASTEXITCODE`n$out" | Set-Content -Path $log -Encoding utf8
    exit $LASTEXITCODE
} catch {
    "ERRO: $($_.Exception.Message)" | Set-Content -Path $log -Encoding utf8
    exit 9
}
