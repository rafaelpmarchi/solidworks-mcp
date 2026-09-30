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
.venv\Scripts\pip install -e ".[dev]"
```

O `.mcp.json` do repo registra o servidor `solidworks` (`swmcp.exe`); para
instalar numa pasta autocontida em outra máquina, ver [INSTALAR.md](INSTALAR.md).

Os dumps reais usados em parte dos testes (`tests/fixtures`) são desenhos de
clientes e não estão no repositório; sem eles esses testes são pulados.

## Engenharia reversa (scan 3D → sólido)

Tools `mesh_*` transformam malha de scanner (Creality Raptor Pro, STL/OBJ/PLY
em mm) em geometria nativa: alinhamento, segmentação usinado × fundido, RANSAC
de primitivas, seções → sketch, freeform → STEP e mapa de desvio scan × CAD.
O processamento roda num motor em subprocesso com venv próprio — ver
[docs/engenharia-reversa.md](docs/engenharia-reversa.md) (instalação do venv
`engine/.venv` incluída).

## Estruturas soldadas (weldment)

`list_weldment_profiles` → `insert_structural_member` (sketch de linhas +
norma/tipo/tamanho) → `get_cut_list`; `insert_cut_list_table` põe a lista no
desenho. `normalize_tube_cut` refaz a boca de lobo como corte normal ao tubo
(laser de tubo), `check_body_interference` confere e `create_weldment_profile`
cria perfis novos (.SLDLFP) na biblioteca. File Locations do
SolidWorks: `get_file_locations`, `set_file_location`, `apply_kongz_library`.
Detalhes e armadilhas da API em
[docs/decisoes/0005-weldments.md](docs/decisoes/0005-weldments.md).

## Chapas com aberturas

`fillet_opening_corners(feature, raio)` arredonda de uma vez todos os cantos
das aberturas fechadas (furos, fendas, grelhas com aletas) da chapa de uma
feature, sem selecionar aresta por aresta; `preview=True` só lista os cantos
e `region_mm` limita a uma grelha. Ignora o que já está filetado. Armadilhas
da API em [docs/decisoes/0006-cantos-de-abertura.md](docs/decisoes/0006-cantos-de-abertura.md).

## Conferir e ajustar peça existente

`list_dimensions` dá as cotas com nome completo (`D1@Esboço10`) e tolerância;
`set_dimension_tolerance` aplica ajuste ISO (H7/f7), bilateral, simétrica etc.
`check_rebuild_errors` é o painel "O que está errado?" por API; `list_faces` e
`sketch_status` acham faces e entidades soltas por geometria. Para pôr chanfro,
filete ou alívio DIN 509 dentro do perfil torneado: `edit_sketch` +
`sketch_corner_chamfer` / `sketch_corner_fillet` / `sketch_undercut_din509`
pela coordenada do canto — as linhas são encurtadas, não recriadas, e as cotas
ficam. `set_circular_pattern_axis` e `rename_features` para o reparo e a
arrumação. Armadilhas da API em
[docs/decisoes/0009-conferencia-e-ajuste-de-peca.md](docs/decisoes/0009-conferencia-e-ajuste-de-peca.md).

## Bloco hidráulico e desenho de cliente em PDF

`port_hole` faz o pórtico G inteiro (rebaixo d2×a, broca da rosca, canal) numa
feature, começando fora da face — rebaixo que invade ressalto corta o ressalto;
`angled_channel` fura inclinado dentro de um plano de vista (`target_mm`);
`sketch_on_face` e `batch_holes` trabalham em coordenadas da peça. Depois de cada
lote, `validate_model` (reconstrução, esboços, corpos, massa do carimbo).
`dump_holes` lê a furação de uma peça de referência, `organize_tree` monta as
pastas por face, `copy_properties_from` traz material/propriedades e `view_face`
fotografa normal a uma face. `run_sw_script(scratch=True)` testa API numa peça
descartável. Para o PDF do cliente: `pdf_drawing_crop` (vista em PNG + mm por
pixel) e `pdf_compare_table` (comparativo de dois desenhos por cota). Decisões
em [docs/decisoes/0010-bloco-hidraulico-e-validacao.md](docs/decisoes/0010-bloco-hidraulico-e-validacao.md).

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
