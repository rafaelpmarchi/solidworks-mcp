# ADR 0009 — Conferir e ajustar peça existente: cotas, tolerâncias, canto do perfil e reparo

**Data:** 2026-09-29 · **Status:** Aceito

## Contexto

Conferência de um cilindro hidráulico (Siemens 3-50200-92309-00D) contra o
desenho: quatro divergências achadas e corrigidas, depois chanfro, R1, dois
alívios DIN 509 e 16 tolerâncias aplicadas, tudo por `run_sw_script`. Cada
etapa exigiu redescobrir a API — e três coisas deram errado no caminho:
tolerância aplicada na cota errada (nome curto `D1` repetido entre esboços),
a caixa "Modificar" travando a API ao criar cota, e a edição do perfil
deixando o eixo de um padrão circular e o plano de um furo perdidos. O
usuário pediu que virasse tudo tool.

## Decisão

`com/wrappers/dimensions.py`, `inspect.py`, `sketch_edit.py`, `repair.py` +
`domain/undercut.py` (geometria pura, testada sem SW) + tools em
`tools/inspect_edit.py`:

- `list_dimensions(feature?)`: nome COMPLETO (`D1@Esboço10`), valor, unidade,
  diametral, dirigida, tolerância atual. O esboço absorvido por uma feature é
  sub-feature e as cotas dele aparecem na feature pai — pedir qualquer um dos
  dois nomes devolve as mesmas cotas.
- `set_dimension_tolerance(nome, tipo, fit, upper, lower, show_as_diameter)`.
- `check_rebuild_errors`, `list_faces(kind, diameter)`, `sketch_status`
  (segmentos e pontos sub-definidos, com coordenadas).
- `sketch_corner_chamfer/fillet(corner)`: chanfro/filete do próprio esboço,
  achando o canto pela coordenada.
- `sketch_undercut_din509(corner, r, t, f?, ângulo)`: alívio forma E dentro
  do perfil; linhas originais encurtadas, não recriadas; cotado (R, t, f,
  ângulo) e com tangências; `lost_dimensions` diz o que se perdeu.
- `set_circular_pattern_axis(feature, face_at)`, `rename_features(dict)`.
- `ComCallError` passa a herdar de `ToolError`: o motivo chega ao modelo em
  vez de "Error executing tool X".
- `hole_wizard`: volume removido MENOR que o esperado vira aviso (furo que
  cruza galeria existente), não erro. `select_face_at` ganhou `mark`.

## Aprendizados técnicos (SW2023 SP5 PT-BR, medidos ao vivo)

- `swTolFIT` = 7 (mesmo valor de `swTolMETRIC`) só grava a classe e deixa
  min/max em 0. O "Ajuste" da UI, com desvios calculados, é
  `swTolFITWITHTOL` = 8. `SetFitValues(furo, eixo)`: maiúscula no primeiro,
  minúscula no segundo; trocar deixa 0/0 sem erro. `GetFitValues` não existe
  no typelib: são `GetHoleFitValue`/`GetShaftFitValue`.
- Cota radial de perfil de revolução: `IDisplayDimension.Diametric = True`
  antes do ajuste, senão H7 é calculado sobre o raio.
- Simétrica: a API guarda só o máximo (`GetMinValue2` devolve 0).
- `DrivenState` fica em `IDimension` (não em `IDisplayDimension`): 1 =
  dirigida, 2 = dirigente.
- `SplitOpenSegment` deixa a identidade (e as cotas) com o pedaço que contém
  o ponto INICIAL da linha. Canto no fim → dividir e apagar o pedaço do canto
  preserva tudo; canto no início → mover o ponto com `SetCoords`, depois de a
  outra linha já ter sido encurtada (até então o ponto é compartilhado).
- `SketchTrim` opção 3 apaga ora um lado, ora o outro, conforme o ponto
  clicado coincide ou não com uma interseção — imprevisível, não usar.
- Segmentos criados com `AddToDB=True` em coordenadas exatamente iguais às
  pontas existentes são fundidos (um único `ISketchPoint`): não precisa de
  relação coincidente.
- `CreateArc` com direção +1 dá o arco curto ou o longo conforme a
  orientação do canto: conferir `GetLength` < π·r e refazer com −1.
- `SketchAddConstraints` é de `IModelDoc2`, não do `SketchManager`.
- `CreateChamfer`: `swSketchChamfer_DistanceEqual` = 2, `DistanceDistance` = 1.
  `CreateFillet` usa `swConstrainedCornerKeepGeometry` (1); a constante
  `swConstrainedCornerAction_UseDefaultBehavior` que `sketch_fillet` usava não
  existe no enum (corrigido).
- Editar uma linha do perfil (dividir/recriar) troca a identidade das faces
  geradas por ela: eixo de padrão circular e plano de esboço de furo ficam
  perdidos. `ICircularPatternFeatureData.Axis` religa o padrão; trocar o
  plano de um esboço existente não tem API pública — o furo se refaz com
  `hole_wizard`.
- `AddDimension2` abre a caixa "Modificar" se `swInputDimValOnCreate` (10)
  estiver ligado e a API trava até alguém fechar: desligar antes, restaurar
  no `finally` (padrão já de `dimensioning.py`, agora também em `sketch_edit`).
- O tamanho de furo simples na biblioteca Ansi Metric chama-se `Ø12.0`
  (com o símbolo); `12.0` é recusado por `HoleWizard5`.
