# ADR 0007 — Chapa metálica, furo de folga, esboço sempre amarrado e montagem girada

**Data:** 2026-09-25 · **Status:** Aceito

## Contexto

A prateleira 1900×1000×400 (cantoneira 40×40 e bandeja em U, chapa 2,65,
furos M6 em pares) foi modelada numa sessão quase toda por `run_sw_script`,
porque o MCP não tinha flange-base, não fazia furo de folga com ajuste nem
vários furos numa feature, deixava esboço azul e não girava componente. O
usuário pediu que o resultado virasse ferramenta e que **esboço nenhum fique
sub-definido** — regra da Gromar, não preferência da sessão.

## Decisão

- `fully_define_sketch(sketch_name?)` (`com/wrappers/sketch_define.py`):
  cotagem genérica — relação H/V nas linhas, âncora na origem, comprimento
  de linha, diâmetro de círculo, pontos soltos alinhados em coluna/linha e
  cotados em cadeia (plano em `domain/sketch_layout.py`, puro e testado),
  e por fim cota de cada ponto até a origem. Cota/relação que sobredefine é
  desfeita na hora (`EditUndo2`).
- A regra vale por padrão: `extrude`, `revolve`, `sheet_metal_base_flange` e
  `hole_wizard` amarram o esboço sozinhos (`fully_define=True`) e devolvem
  `sketch_definition.fully_defined`.
- `sheet_metal_base_flange` (`com/wrappers/sheetmetal.py`): perfil aberto
  (L, U) ou fechado, espessura, raio (padrão = espessura) e fator K.
- `hole_wizard(hole_type='clearance', fit=close|normal|loose)` com os Ø da
  tabela `ScrewClearances` da própria biblioteca do SolidWorks;
  `model_positions_mm` para vários furos por feature em coordenadas da peça.
- `insert_component(..., rotation_deg, fixed)` e `set_component_transform`,
  com a matemática do `IMathTransform` em `domain/placement.py`.
- `linear_pattern` tenta o sentido oposto da aresta antes de desistir.

## Aprendizados técnicos (SW2023 SP5 PT-BR, medidos ao vivo)

- `IFeatureManager.InsertSheetMetalBaseFlange2` (19 args) devolve `None`
  com qualquer combinação; `InsertSheetMetalBaseFlange` (16 args, com
  `ICustomBendAllowance` K) funciona. O lado da espessura depende do sentido
  em que o perfil foi desenhado — a tool devolve a caixa do corpo.
- `HoleWizard5(swWzdHole, swStandardISO, swStandardISOScrewClearances, "M6",
  …, Diameter=Ø do ajuste)` sai pela norma com o Ø pedido (6,4 = fino) —
  ao contrário do furo roscado Ansi Metric, que cai em Ø25,4.
- O esboço de posição do furo tem eixos próprios: na face Z=0 da cantoneira o
  X do esboço é −X da peça. `ISketch.ModelToSketchTransform.ArrayData`
  aplicado como vetor-linha converte certo; `IMathPoint.MultiplyTransform`
  devolveu coordenadas erradas.
- O sub-esboço de posição se reconhece por "tem pontos e nenhum segmento";
  "tem um ponto" deixa de valer quando o furo ganha o segundo ponto.
- `IMathUtility.CreateTransform` com lista Python pura cria **identidade**
  sem erro — o componente "não se mexe". Precisa de
  `VARIANT(VT_ARRAY|VT_R8, …)`. Componente fixo também ignora
  `Transform2`: liberar, posicionar e fixar de novo.
- `FeatureLinearPattern4/5` devolve `None` quando as cópias caem fora da peça
  (aresta apontando para baixo do pé da coluna); o sentido da aresta é
  arbitrário, então a tool refaz a seleção e tenta invertido.
- `ISketchLine` precisa de `cast_to(…, "ISketchSegment")` para `Select4`.

## Consequências

Esboços antigos, feitos antes desta regra, continuam azuis até alguém chamar
`fully_define_sketch` neles. A cotagem automática cobre perfis de linhas,
círculos e pontos; arco parcial e spline ficam pela etapa "cada ponto até a
origem", que pode não fechar — por isso o campo `fully_defined` precisa ser
conferido.
