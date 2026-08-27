# solidworks-mcp

Servidor MCP em Python que expõe o SolidWorks (via COM) como ferramentas para o
Claude Code: leitura, revisão e criação assistida de desenhos 2D. Ver
[docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md) e
[docs/PLANO-MVP.md](docs/PLANO-MVP.md).

Requer Windows com SolidWorks instalado (a aplicação fica aberta e visível; o agente
trabalha ao lado).

## Instalação

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
```

## Registrar no Claude Code

```powershell
claude mcp add solidworks -- C:\Users\peron\Documents\Github\solidworks\.venv\Scripts\python.exe -m swmcp.server
```

## Engenharia reversa (scan 3D → sólido)

Tools `mesh_*` transformam malha de scanner (Creality Raptor Pro, STL/OBJ/PLY
em mm) em geometria nativa: alinhamento, segmentação usinado × fundido, RANSAC
de primitivas, seções → sketch, freeform → STEP e mapa de desvio scan × CAD.
O processamento roda num motor em subprocesso com venv próprio — ver
[docs/engenharia-reversa.md](docs/engenharia-reversa.md) (instalação do venv
`engine/.venv` incluída).

## Testes

```powershell
.venv\Scripts\python -m pytest              # unitários (não precisam de SolidWorks)
.venv\Scripts\python -m pytest tests/integration -m integration   # exigem SolidWorks aberto
```

## Chat dentro do SolidWorks (add-in)

O add-in `addin/` cria um taskpane "Claude" dentro do SolidWorks com um chat
que usa as mesmas ferramentas (status, dump, revisão) direto na API Anthropic.

```powershell
cd addin
dotnet build -c Release
# como administrador:
powershell -ExecutionPolicy Bypass -File .\register.ps1
```

Depois: SolidWorks → Ferramentas → Suplementos → **Claude**. O backend
(`python -m swmcp.chat`, porta local 8765) é iniciado automaticamente pelo
add-in. Credencial: variável de ambiente `ANTHROPIC_API_KEY` (ou perfil
`ant auth login`).

## Estrutura

- `src/swmcp/com/` — única camada que toca win32com (STA worker, invoke fail-fast, unidades)
- `src/swmcp/domain/` + `review/` — Python puro, testável com fixtures JSON
- `src/swmcp/services/` — casos de uso (ler desenho, revisar…)
- `src/swmcp/tools/` + `server.py` — tools MCP
