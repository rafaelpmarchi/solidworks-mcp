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

## Testes

```powershell
.venv\Scripts\python -m pytest              # unitários (não precisam de SolidWorks)
.venv\Scripts\python -m pytest tests/integration -m integration   # exigem SolidWorks aberto
```

## Estrutura

- `src/swmcp/com/` — única camada que toca win32com (STA worker, invoke fail-fast, unidades)
- `src/swmcp/domain/` + `review/` — Python puro, testável com fixtures JSON
- `src/swmcp/services/` — casos de uso (ler desenho, revisar…)
- `src/swmcp/tools/` + `server.py` — tools MCP
