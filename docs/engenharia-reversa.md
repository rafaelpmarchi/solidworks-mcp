# Engenharia reversa: scan 3D → sólido no SolidWorks

Alternativa caseira ao QuickSurface (€1100/ano) para o fluxo da Gromar:
peças automotivas fundidas escaneadas com o **Creality Raptor Pro**.

## Arquitetura

```
Creality Scan (fusão dos passes, exporta PLY/STL em mm)
        │
        ▼
engine/swengine  ─ MOTOR de geometria (venv 3.13 próprio, subprocesso)
  trimesh + numpy/scipy + OpenCascade (build123d)      │ JSON via stdio,
  a malha NUNCA passa pelo MCP — só caminhos           │ malha só em disco
        │
        ▼
src/swmcp/tools/mesh.py  ─ tools MCP mesh_* no servidor solidworks
        │
        ▼
SolidWorks Standard (COM): planos, eixos, sketches, features nativas
```

Por que subprocesso: Open3D não tem wheel para Python 3.13/3.14 (venv do MCP),
malha de milhões de triângulos não pode transitar por JSON, e crash do motor
não derruba o servidor. `fast-simplification` empacou em ~30 % de redução
nesta build, então a decimação é por agrupamento em grade (numpy puro).

## Add-in "Scan 3D" (estilo QuickSurface/Mesh2Surface)

Add-in PRÓPRIO em `addin-scan/`, calcado na UI do
Mesh2Surface (screenshots do usuário + docs oficiais):

- **Fluxo nativo (2026-08-27)**: os botões do ribbon abrem **PropertyManager
  nativo à esquerda** (✓/✗ e campos, como qualquer comando do SolidWorks —
  `addin-scan/Pmp.cs`), executam no backend HTTP (`Backend.cs`) e mostram o
  resultado em diálogo do SW (estilo "Mesh Information" do M2S). Ações sem
  parâmetro (Importar/Exportar/Info/Inverter/Simetria) rodam direto. Os
  comandos atuam na malha toda (`region={"active": true}` só usa máscara se
  alguma tiver sido salva via MCP).
- **Aba "Scan 3D" no CommandManager** com os comandos na ordem do original:
  Importar scan · Exportar · Decimar · Info da malha · Inverter normais ·
  Seleção de malha · Alinhar por referências · Plano de simetria · Primitivas ·
  Superfície automática · Seção transversal · Comparar. A aba é recriada a
  cada carga (a restaurada do registro fica fantasma no SW 2023) e nasce
  selecionada; no 1º documento de cada tipo o add-in devolve a seleção para
  a primeira aba nativa (Recursos/Montagem) via `ICommandTab.Active`.
- Backend subido com ShellExecute (não herda handles do SW — herdando, um
  backend órfão travava o diário `swxJRNL` do próximo SW) e encerrado com
  `taskkill /T` (o python do venv é lançador de outro processo).
- Conflito conhecido (2026-09-28): Mavito ERP + PDM + 3DEXPERIENCE
  Marketplace carregando juntos na inicialização derrubam o SW 2023 ao abrir;
  qualquer dois deles funcionam. Manter o Marketplace desligado.
- **Sem taskpane (2026-09-28)**: o painel lateral com viewer three.js foi
  removido a pedido do usuário. O backend `python -m swmcp.chat` continua
  (rotas diretas sem LLM em `src/swmcp/chat/panel.py`), subido pelo add-in a
  partir de `solidworks-mcp\.venv`.
- Registro (admin): `cd addin-scan; dotnet build -c Release;`
  depois `powershell -ExecutionPolicy Bypass -File .\register.ps1` como admin.

Estado compartilhado: `%TEMP%/swengine/state.json` — o add-in, o chat e o MCP
enxergam a mesma malha ativa.

Paridade adicional (guiada pela brochura QS2026 e pelo Helpfile em docs/):
- **Fit Surface com extensão**: `extend_mm` no freeform estende a superfície
  além da região para servir de ferramenta de recorte (trim).
- **Reconhecimento de formas 2D** nas seções: círculo, retângulo, slot e
  polígono regular viram entidades NATIVAS no sketch (círculo de verdade,
  slot de verdade), não linhas soltas.
- **Fit restrito** (`constraint_axis`): trava a normal do plano ou o eixo do
  cilindro em X/Y/Z — os botões Vertical/Horizontal do Mesh2Surface.
- **Desvio Passa/Falha** (`pass_fail_tol_mm`): verde dentro de ±tol, gradiente
  até 5×tol, e % dentro da tolerância no resultado.

## Fluxo típico (via chat/Claude)

1. `mesh_import(path)` — PLY/STL/OBJ do scanner (mm). Só lê, não toca no SW.
2. `mesh_decimate(200000)` — se o scan vier pesado.
3. `mesh_align("pca")` ou `mesh_align("plane_to_xy", region=...)` — assenta a
   face usinada de referência em Z=0. **Tudo que vem depois sai neste sistema
   de coordenadas.** Se já existe um CAD da peça (conferência, retrabalho,
   variante), use `mesh_align("to_cad")`: exporta um STL temporário do
   documento aberto e registra o scan nele (PCA dos dois + 48 candidatos de
   rotação + ICP ponto-a-plano, ~15 s para 300 k faces). A malha passa a
   viver no sistema do desenho e `mesh_deviation_map` usa esse STL como
   referência padrão. Confira `registro.inlier_fraction` (fração do scan a
   menos de `inlier_mm` do CAD): baixo demais = peça diferente do modelo ou
   mínimo local — nesse caso passe `region` com só as faces usinadas.
   `mesh_align("to_reference", reference_stl=...)` faz o mesmo contra
   qualquer STL. A seção que passa pelo eixo de uma peça de revolução sai
   como curvas ABERTAS (scan nunca é estanque) — `mesh_section_to_sketch`
   desenha as abertas também.
4. `mesh_segment()` — separa regiões lisas (usinadas) da superfície bruta de
   fundição pela variação das normais. Cada região ganha um label.
5. `mesh_fit_primitive(kind="auto", region={"labels": {"value": N}})` —
   RANSAC + refino de plano/cilindro/esfera/cone. Retorna parâmetros em mm/°,
   `inlier_fraction` e `rms_mm`.
6. Materializar no SW:
   - `mesh_primitive_to_sw(primitive)` — plano vira plano de referência
     offset; cilindro vira sketch com círculo pronto para extrudar.
   - `mesh_section_to_sketch(axis, position_mm)` — contorno da seção desenhado
     no sketch ativo (linhas/arcos onde fecha na tolerância, spline no resto).
     Para a região orgânica: várias seções + loft.
   - `mesh_freeform_to_step(out_step, region=...)` — parede/nervura freeform
     vira superfície B-spline em STEP (importar no SW). Só para região tipo
     "altura sobre um plano"; se dobrar, dividir em patches.
7. Modelar normalmente (extrude/revolve/loft) e exportar STL do modelo
   (`export_document`).
8. `mesh_deviation_map(reference_stl=...)` — PNG com 4 vistas: vermelho =
   scan acima do CAD, azul = abaixo, **cinza = sem dado** (lacuna de scan não
   é interpolada — buraco de scan é informação, não zero). O mapa NÃO alinha:
   scan e STL precisam estar no mesmo sistema — é o que `to_cad` garante.

## Peça de revolução (disco, flange, cubo, polia)

Aprendido na aranha de disco de freio (scan de UM lado, 02/10/2026), onde o
PCA deixou o eixo 3,6 mm fora do furo e o perfil/furos saíram de scripts:

1. `mesh_align(mode="axis")` — eixo pela geometria das normais (toda reta
   normal de uma superfície de revolução corta o eixo; Pottmann & Randrup,
   mínimos quadrados robustos). Normais por PCA local (a normal de uma face
   de scan erra graus — a 70 mm do eixo isso é 2-3 mm). Furos fora do centro e
   orelhas viram outliers. Na aranha: 0,08 mm do centro do furo e 0,07° do
   eixo. `z_origin="min"` deixa a peça em Z ≥ 0.
2. `mesh_revolve_profile` — (r, z) de pontos densos; só entram células vistas
   em ≥ `min_coverage` da volta (furos e paredes de orelha ficam fora). Onde
   duas superfícies se ALTERNAM na volta (topo da orelha × aba entre orelhas,
   ~50 % cada) a escolha é global por nível de z — coluna a coluna misturava
   os dois e a curva fazia desvio. Saída: polilinha de CANTOS VIVOS (retas
   reajustadas e intersectadas), `fillets` com o raio estimado em cada canto
   (δ = R(1 − sen θ/2), só pontos com normal entre as das duas retas), e
   rms. Scan de um lado só sai ABERTO: `thickness_mm` fecha com parede de
   espessura constante (estimativa). `draw=True` desenha perfil + linha de
   centro num esboço que contém o eixo (`fillets=True` põe as concordâncias
   no esboço — desligado: o SW caiu na cotagem do revolve com elas, ver ADR
   0011; filete as arestas depois).
3. `mesh_detect_holes` — vazios fechados vistos ao longo do eixo; Ø pelo
   ajuste nas PAREDES (o raster erra ~0,4 mm); vazio sem parede é lacuna de
   scan (adesivo de alvo). Grupos por Ø+raio e só por raio, com o padrão
   angular (posições, passo, ângulo inicial, quais faltam). Na aranha: 12 em
   Ø83 a 30° (5×Ø9,07 + 7×Ø14,0), 15×Ø4,36 em Ø173 a 24°, 3×Ø4,8 em Ø98.
   `draw=True` desenha os furos no esboço ativo (perpendicular ao eixo).
4. `mesh_apply_to_sw` — o estado guarda a transformação acumulada desde o
   `mesh_import`; esta tool a aplica ao corpo de malha do SolidWorks (Mover/
   Copiar corpo: giro X, Y, Z e translação — o 1º ângulo da API gira em Z e
   o 3º em X, medido) para scan e modelo viverem no mesmo sistema.
5. `mesh_deviation_map(reference_stl="active_doc", bodies=[...])` — mede o
   documento aberto sem realinhar. O STL agora sai nas coordenadas da peça
   (o padrão do SW translada para o octante positivo — eram ~90 mm de erro
   silencioso), em mm e fino.
6. `surface_from_faces` — se o pedido é SUPERFÍCIE: modele o sólido auxiliar
   e copie as faces voltadas para o scanner (offset 0).

Cuidados: malha de milhões de triângulos VISÍVEL no documento deixa cada
chamada de API lenta (minutos) — `set_body_visibility` antes de modelar.
Importar STL no SolidWorks como superfície leva ~10 min para 300 k faces e
abre o diálogo "Novo documento" se não houver template padrão marcado.

## Regiões (sem picking gráfico)

As tools aceitam `region` em JSON — ver `engine/swengine/region.py`:

```json
{"box": {"min": [0,0,0], "max": [50,50,10]}}
{"axis_range": {"axis": "z", "min": 80}}
{"seed": {"point": [10,20,5], "radius": 15}}
{"labels": {"value": 3}}            ← rótulo do mesh_segment
```

Combinações fazem interseção (E lógico).

## Critérios de aceite (validar com peça real)

- Faces usinadas (flange, mancal, furo): desvio < **0,1 mm** no mapa.
- Superfície bruta de fundição: desvio < **1 mm** (tolerância de fundição).
- Peça escaneada com spray revelador se for escura/oleosa; face brilhante
  reflete e vira lacuna.

## Backends do motor

A ponte MCP escolhe sozinha (forçável com `SWMCP_ENGINE_BACKEND=wsl|windows`):

| Backend | Onde roda | Open3D | Quando usa |
|---|---|---|---|
| **wsl** (preferido) | Ubuntu 24.04/WSL2, Python 3.12 isolado em `~/.swengine-env` | ✅ (decimação quadric) | se o ambiente WSL existir |
| **windows** | `engine/.venv` (Python 3.13) | ❌ (decimação por grade) | fallback |
| **docker** | `engine/Dockerfile` | ✅ | manual — Docker não está instalado nesta máquina |

Só o motor de geometria vai para Linux/container; o SolidWorks/COM fica
obrigatoriamente no Windows. Caminhos `C:\...` são traduzidos para `/mnt/c/...`
automaticamente pela ponte.

### Instalação — WSL (preferido)

Feita em 2026-08-27 sem sudo: venv `--without-pip` + get-pip, e as libs de
sistema (libgomp/libGL) extraídas de .debs em `~/.swengine-libs` (o launcher
`engine/wsl-run.sh` exporta o `LD_LIBRARY_PATH`). Para refazer do zero:

```bash
python3 -m venv --without-pip ~/.swengine-env
curl -sSL https://bootstrap.pypa.io/get-pip.py | ~/.swengine-env/bin/python
~/.swengine-env/bin/pip install open3d trimesh numpy scipy matplotlib rtree pillow networkx build123d pytest
mkdir -p ~/.swengine-libs && cd /tmp
for p in libgomp1 libgl1 libglx0 libglvnd0 libopengl0 libegl1 libx11-6 libxcb1 libxau6 libxdmcp6; do apt-get download $p; done
for d in *.deb; do dpkg -x $d ~/.swengine-libs; done
```

(com sudo é só `sudo apt install python3-venv libgomp1 libgl1` e pular a extração)

### Instalação — venv Windows (fallback)

```powershell
cd engine
py -3.13 -m venv .venv
.venv\Scripts\pip install trimesh numpy scipy matplotlib fast-simplification rtree pillow networkx build123d pytest
.venv\Scripts\python -m pytest tests   # 20 testes, sem SolidWorks
```

### Container Docker (quando instalar o Docker)

O Docker não está nesta máquina (instalar exige admin). Com ele instalado:

```powershell
docker build -t swengine engine/
# malhas entram/saem por volume em /work:
Get-Content args.json | docker run -i --rm -v C:\Temp\swengine:/work swengine fit
```

A ponte MCP ainda não fala com o backend docker — hoje ela usa WSL, que dá o
mesmo isolamento (kernel Linux + Python próprio). Se um dia rodar o motor em
outro servidor, o container é o caminho.

## Limites conhecidos

- `mesh_primitive_to_sw` só materializa plano/cilindro alinhados a X/Y/Z
  (±3°) — caso oblíquo: alinhe a malha antes, ou use `run_sw_script`.
- Freeform: patch único aberto, sem continuidade G1/G2 entre patches, sem
  qualidade classe A. Para carcaça inteira orgânica, QuickSurface ainda ganha.
- Segmentação depende do limiar (`smooth_threshold_deg`, padrão 8°): fundição
  jateada fina pode parecer "lisa" — ajuste para 5-6° nesses casos.
