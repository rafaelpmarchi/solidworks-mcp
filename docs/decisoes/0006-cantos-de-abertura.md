# ADR 0006 — Filete em todos os cantos das aberturas de uma chapa

**Data:** 2026-09-21 · **Status:** Aceito

## Contexto

Gabinete em chapa com grelhas de ventilação (círculo com aletas) e fendas.
O pedido "raio de 2 mm nas aberturas" exigia selecionar dezenas de arestas
por coordenada (`select_entity` EDGE + `fillet_selected`), e `SelectByID2`
por coordenada em aresta de 2 mm falhava em silêncio. Feito à mão numa
sessão (76 arestas em 3 features), virou tool.

## Decisão

`fillet_opening_corners(feature_name, radius_mm, region_mm?, include_outer,
preview)` em `tools/create.py`; wrapper em `com/wrappers/modeling.py`;
escolha das arestas em `domain/corners.py` (puro, testado sem SolidWorks).

Algoritmo: nas faces planas da feature, pega os contornos internos (loops
não externos = aberturas fechadas), visita os vértices deles e, de cada
vértice, as arestas que chegam (`IVertex.GetEdges`). Fica quem é reta,
paralela à normal da chapa (atravessa a espessura) e **não tangente** — as
duas faces vizinhas têm normais diferentes no ponto médio. Isso descarta a
costura de furo redondo e as bordas de filete já existente, logo chamar
duas vezes não duplica nada. Uma feature de filete por chamada, via
`FeatureFillet3` com as arestas em marca 1.

## Aprendizados técnicos (SW2023 SP5 PT-BR, medidos ao vivo)

- **Selecionar aresta**: `IEntity.Select4(True, ISelectData{Mark=1})` no
  objeto é determinístico; `SelectByID2("", "EDGE", x, y, z)` no ponto
  médio de uma aresta de 2 mm devolveu False sem erro.
- **Editar filete existente é perigoso**: `ISimpleFilletFeatureData2`
  (`AccessSelections` → `Edges = [...]` → `ModifyDefinition`) lançou
  0x80010105 e deixou a feature com raio 0 e erro de reconstrução. Para
  acrescentar arestas, apagar e recriar o filete.
- **`GetErrorCode2` do filete**: código 13 (`swFeatureErrorFilletNoEdge`)
  com flag de aviso = o SolidWorks criou a feature descartando arestas —
  aconteceu com a barra central da grelha, que era um corpo separado
  (`Ressalto-extrusão3[2]`) só encostando no círculo pelas pontas.
  `GetFaces` do filete devolve menos faces que arestas pedidas.
- **Reta ou arco**: `IEdge.GetCurve().IsLine()` respondeu 0x80010108
  (objeto desconectado) em parte das arestas vindas de `IVertex.GetEdges`;
  `IEdge.GetCurveParams3().CurveType == LINE_TYPE (3001)` é estável.
- **Normal numa face qualquer**: `ISurface.EvaluateAtPoint(x, y, z)`
  devolve `[nx, ny, nz, ...]`; o sinal depende de `FaceInSurfaceSense`, por
  isso a comparação de tangência usa o módulo do produto escalar.
- **Usuário editando ao mesmo tempo**: qualquer rebuild do usuário no meio
  da varredura invalida faces/arestas (0x80010108) e a chamada fica lenta.
  Não é defeito do código — repetir quando o modelo estiver parado.
- Filete R2 nas fendas de 4 mm de altura fechou as pontas em semicírculo
  sem erro (os dois quartos de círculo consomem a face da ponta inteira).
