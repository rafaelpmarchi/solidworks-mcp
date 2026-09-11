# Instala o solidworks-mcp numa pasta autocontida (venv próprio) e mostra
# como registrar no Claude Code. Rodar na pasta do pacote:
#   powershell -ExecutionPolicy Bypass -File .\instalar.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "== solidworks-mcp: instalação em $root" -ForegroundColor Cyan

# 1) Python 3.13+ (64 bits)
$py = $null
foreach ($cand in @("py -3.14", "py -3.13", "python")) {
    try {
        $v = & cmd /c "$cand -c `"import sys;print(sys.version_info[0]*100+sys.version_info[1], sys.maxsize>2**32)`"" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) {
            $parts = $v.Trim().Split(" ")
            if ([int]$parts[0] -ge 313 -and $parts[1] -eq "True") { $py = $cand; break }
        }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.13+ (64 bits) não encontrado. Instale em https://www.python.org/downloads/windows/ e rode de novo." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $py"

# 2) venv + pacote
if (-not (Test-Path ".venv")) {
    & cmd /c "$py -m venv .venv"
    if ($LASTEXITCODE -ne 0) { throw "falha ao criar o .venv" }
}
$pip = Join-Path $root ".venv\Scripts\pip.exe"
& $pip install --upgrade pip | Out-Null
& $pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "falha ao instalar o pacote" }

# 3) testes unitários (sem SolidWorks)
$python = Join-Path $root ".venv\Scripts\python.exe"
& $python -m pytest tests/unit -q
if ($LASTEXITCODE -ne 0) { Write-Host "Testes falharam — veja acima." -ForegroundColor Yellow }

# 4) como registrar
$exe = Join-Path $root ".venv\Scripts\swmcp.exe"
Write-Host ""
Write-Host "== Pronto. Registre no Claude Code com:" -ForegroundColor Green
Write-Host "   claude mcp add solidworks -- `"$exe`""
Write-Host ""
Write-Host "ou num .mcp.json do projeto:"
Write-Host ('   {"mcpServers":{"solidworks":{"command":"' + ($exe -replace "\\", "/") + '"}}}')
Write-Host ""
Write-Host "Depois abra o Claude Code (com o SolidWorks aberto) e pergunte: 'qual o status do SolidWorks?'"
