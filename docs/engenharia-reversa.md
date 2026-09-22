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

Add-in PRÓPRIO em `addin-scan/` (separado do add-in Claude), calcado na UI do
Mesh2Surface (screenshots do usuário + docs oficiais):

- **Fluxo nativo (2026-08-27)**: os botões do ribbon abrem **PropertyManager
  nativo à esquerda** (✓/✗ e campos, como qualquer comando do SolidWorks —
  `addin-scan/Pmp.cs`), executam no backend HTTP (`Backend.cs`) e mostram o
  resultado em diálogo do SW (estilo "Mesh Information" do M2S). Ações sem
  parâmetro (Importar/Exportar/Info/Inverter/Simetria) rodam direto. A
  "região ativa" dos comandos é a seleção pintada no viewer do painel
  (`region={"active": true}` → máscara), ou a malha toda.
- **Aba "Scan 3D" no CommandManager** com os comandos na ordem do original:
  Importar scan · Exportar · Decimar · Info da malha · Inverter normais ·
  Seleção de malha · Alinhar por referências · Plano de simetria · Primitivas ·
  Superfície automática · Seção transversal · Comparar. Cada botão abre o
  grupo correspondente no painel.
- **Taskpane claro** (tema PropertyManager) servido por `python -m swmcp.chat`
  na rota `/scan` (`src/swmcp/chat/web/scan.html`); rotas diretas sem LLM em
  `src/swmcp/chat/panel.py`. Região selecionada na lista vale para primitivas,
  freeform e assentamento.
- Registro (admin): `cd addin-scan; dotnet build -c Release;`
  depois `powershell -ExecutionPolicy Bypass -File .\register.ps1` como admin.
- O add-in Claude (`addin/`) voltou a ser só o chat.

Estado compartilhado: `%TEMP%/swengine/state.json` — o painel, o chat e o MCP
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

### Visualizador 3D no painel (fases 2-5 do plano de paridade)

O painel tem um viewer three.js (servido localmente, `web/viewer.js` +
`web/vendor/`) com a malha decimada (~80k faces, binário compacto via
`viewerpack`). Ferramentas na toolbar do viewer:

- 🔄 órbita · 🖌 **pincel** de seleção (⌫ remove) · ✨ **varinha mágica**
  (expansão por ângulo de normal; o slider é raio do pincel em mm E
  sensibilidade da varinha em graus) · ✏ **3D sketch** sobre o scan
- ✔ transforma a seleção pintada em **região** (máscara na malha cheia via
  `savemask`) — a partir daí primitivas/freeform/desvio/assentamento usam a
  seleção em vez da lista de regiões
- ⭱ envia as curvas do 3D sketch como **sketch 3D nativo** no SolidWorks
  (`sketch_3d_splines`, spline por curva, pontos grudados na malha)
- **Editar superfície** (grupo freeform): abre a grade de controle da
  B-spline no viewer — arrastar os pontos azuis recalcula a superfície em
  tempo real com colorização por tolerância (verde dentro, gradiente até 5×);
  "Gravar STEP" reconstrói via OpenCascade (`freeform_step`).
- **Desenrolar**: cilindro/cone exatos (costura configurável) ou LSCM para
  dupla curvatura com % de distorção; "→ Sketch de corte" desenha o contorno
  planificado no sketch ativo.

Limitação honesta restante vs QuickSurface: a interação 3D acontece no
viewer do PAINEL, não no viewport do SolidWorks (isso exigiria renderização
OpenGL dentro do SW); e o freeform editável é 1 patch por vez, sem
bridge/merge de arestas nem continuidade G2 multi-patch.

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
