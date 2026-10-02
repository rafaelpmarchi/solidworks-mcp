# ADR 0011 — Peça de revolução escaneada, corpos e STL nas coordenadas da peça

**Data:** 2026-10-02 · **Status:** Aceito

## Contexto

Engenharia reversa de uma aranha de disco de freio (scan Creality de UM lado,
2,5 M triângulos, Ø181 × 34 mm) até uma superfície no SolidWorks. Saiu, mas
quase tudo por fora das tools:

- `mesh_align("pca")` deixou o eixo 3,6 mm fora do furo central; o cilindro
  restrito pegou 2,8 % de inliers. O eixo saiu de ajuste de círculo à mão.
- Perfil (r, z) e furos (Ø, PCD, passo) saíram de scripts numpy no scratchpad.
- Levar a malha do SW para o sistema alinhado exigiu Mover/Copiar corpo com a
  ordem dos ângulos descoberta por tentativa (o 1º gira em Z, o 3º em X).
- O STL exportado pelo SW vinha transladado para o octante positivo e o
  `mesh_deviation_map` precisou de recentralização à mão.
- `AddDimension` por `run_sw_script` abriu o diálogo "Modificar" e travou a
  chamada COM por minutos (12 diálogos).
- `_merge_coincident_points` contava a mesma ponta duas vezes (fim de uma
  linha = início da próxima) e rodava as 200 voltas em todo
  `sketch_polyline` fechado.
- Corte em esboço no plano de cima com a peça abaixo: `reverse_direction`
  tem sentido oposto no corte e no ressalto; o corte simplesmente falhava.
- 30 furos com `sketch_circle` um a um; malha visível deixando a API lenta;
  a superfície final saiu de Superfície equidistante 0 por script.

## Decisão

- **Motor** (`engine/swengine/revolution.py`): `fit_axis` (complexo linear
  das retas normais, IRLS de Cauchy, normais por PCA local), `revolve_profile`
  (cobertura angular por célula, conflito de superfícies alternadas decidido
  por nível de z, MST + Douglas-Peucker, retas reajustadas, raio por canto,
  fechamento por espessura com limpeza de trecho invertido) e `detect_holes`
  (raster + ajuste nas paredes + padrão angular). `align` ganha `mode="axis"`.
- **Estado** guarda `transform` (original → malha ativa), composto a cada
  alinhamento e zerado no import; `mesh_apply_to_sw` aplica ao corpo do SW.
- **Tools novas**: `mesh_revolve_profile`, `mesh_detect_holes`,
  `mesh_apply_to_sw`, `list_bodies`, `set_body_visibility`,
  `set_reference_visibility`, `surface_from_faces`, `export_stl`,
  `sketch_circles`; `mesh_deviation_map(reference_stl="active_doc", bodies)`.
- **STL** de `save_as`/`export_document` sai nas coordenadas da peça, em mm e
  fino (preferências trocadas e restauradas na exportação).
- **`run_sw_script`** e `add_sketch_dimension` rodam com
  `swInputDimValOnCreate` desligado (`no_dimension_prompt`).
- **`extrude`**: corte recusado é refeito para o outro lado
  (`reverse_direction_used` + aviso).
- **`_merge_coincident_points`** lê `GetSketchPoints2` e para se a
  coincidência não reduz os pontos.

## Consequências

- Na aranha: eixo a 0,08 mm/0,07° do medido no furo; perfil com rms
  0,02-0,03 mm; furos com Ø ±0,05 e padrões 12×30°, 15×24°, 3×120°.
- O raio de concordância é ESTIMATIVA (a mesma quina deu R2,0 e R3,3 em
  duas decimações); o fechamento por espessura de scan de um lado é palpite —
  as duas saídas avisam.
- Onde a orelha cobre ~50 % da volta, o "perfil base" pode sair pelo topo da
  orelha (anel + rasgos) ou pela aba (disco + orelhas): os dois são modelos
  válidos; a escolha segue a cobertura somada.
- **Pendente — queda do SolidWorks.** Validando o fluxo ao vivo, o SW caiu
  (APPCRASH SLDWORKS.exe em mfc140u.dll, 0xc0000005, 14:49:38) DENTRO da
  cotagem automática que o revolve chama (`_define_active(revolution=True)`)
  sobre um perfil de eixo VERTICAL com 3 concordâncias de esboço
  (CreateFillet). Antes disso, no mesmo tipo de esboço, o 1º FeatureRevolve2
  logo após a cotagem voltou None e o 2º saiu (daí a nova tentativa em
  `revolve`, não validada dentro da mesma chamada). Por isso
  `mesh_revolve_profile(draw=True)` desenha cantos vivos por padrão
  (`fillets=False`). Reproduzir num SW sem documentos do usuário abertos
  antes de religar. Mais cedo, no mesmo dia, outra instância fechou
  (sem evento de falha) logo após importar um STL de 300 k faces como
  superfície: não importar STL pesado com trabalho não salvo aberto.
- Testes: `engine/tests/test_revolution.py` (7, sintéticos),
  `tests/integration/test_bodies_real.py` (7, SW ao vivo), unitários de
  composição de transformação, Euler e direção radial.
