# solidworks-mcp — instalação para compartilhar

Servidor MCP que deixa o Claude Code (ou qualquer cliente MCP) operar o
SolidWorks pela API COM: ler e revisar desenhos, modelar, montar, weldments
(perfis, membros, lista de corte, corte normal ao tubo para laser), exportar,
tirar screenshot e configurar File Locations.

## Requisitos

- Windows 10/11 com **SolidWorks 2023** instalado (2022–2024 provavelmente
  funcionam; a instalação padrão em `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS`
  é esperada para o typelib `sldworks.tlb` e `swconst.tlb`).
- **Python 3.13 ou 3.14** (64 bits): https://www.python.org/downloads/windows/
  — marque "Add python.exe to PATH".
- **Claude Code**: https://claude.com/claude-code (ou outro cliente MCP).
- Não precisa de licença extra: o servidor usa a instância do SolidWorks que
  estiver aberta (ou abre uma, visível).

## Instalação em 3 passos

1. Descompacte o zip numa pasta sem acentos, por exemplo `C:\mcp\solidworks-mcp`.
2. Abra o PowerShell **nessa pasta** e rode:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\instalar.ps1
   ```

   O script cria o `.venv`, instala o pacote e os testes, roda os testes
   unitários (não precisam do SolidWorks) e imprime o caminho do executável
   `swmcp.exe`.

3. Registre no Claude Code (o script já mostra o comando pronto):

   ```powershell
   claude mcp add solidworks -- C:\mcp\solidworks-mcp\.venv\Scripts\swmcp.exe
   ```

   Ou, por projeto, crie um `.mcp.json` na pasta onde você usa o Claude Code:

   ```json
   {
     "mcpServers": {
       "solidworks": { "command": "C:/mcp/solidworks-mcp/.venv/Scripts/swmcp.exe" }
     }
   }
   ```

Abra o Claude Code e peça, por exemplo: *"qual o status do SolidWorks?"* —
a tool `sw_status` deve responder com a versão e os documentos abertos.

## Primeiro uso

- Na primeira chamada o `pywin32` gera os módulos do typelib do SolidWorks
  (`makepy`), o que leva alguns segundos e acontece uma vez só.
- O SolidWorks fica sempre visível; nada é salvo em disco sem a tool
  `save_document`/`save_document_as`.
- Logs em `logs\` dentro da pasta (nível via `SWMCP_LOG_LEVEL`).

## Opcional

- **Engenharia reversa (tools `mesh_*`)**: precisa de um motor de geometria
  separado — ver `docs/engenharia-reversa.md` (venv em `engine\.venv` ou WSL).
  Sem ele, todas as outras tools funcionam normalmente.
- **Add-in de chat dentro do SolidWorks** (`addin\`): exige .NET SDK e uma
  chave da API Anthropic — ver README.md.
- **Biblioteca de templates/perfis compartilhada**: a tool
  `set_file_location` / `apply_kongz_library` aponta o SolidWorks para as
  pastas da sua biblioteca.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `não foi possível iniciar o SolidWorks` | SolidWorks não instalado ou COM bloqueado; abra o SolidWorks antes |
| `interface ... não existe no typelib` | Caminho do `sldworks.tlb` diferente — ajuste `SLDWORKS_TLB` em `src/swmcp/com/session.py` |
| Tool nova não aparece | Reinicie o Claude Code (o servidor MCP é iniciado por sessão) |
| `pywin32` falha ao instalar | Python 32 bits ou muito novo; use Python 3.13 64 bits |
