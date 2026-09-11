# ADR 0005 — Estruturas soldadas (weldments) via MCP

**Data:** 2026-09-11 · **Status:** Aceito

## Contexto

A Gromar projeta quadros e estruturas em tubo/perfil no SolidWorks. O MCP já
modelava sólidos genéricos, mas não sabia criar membros estruturais nem ler a
lista de corte — que é o que vai para o corte de serra e para o orçamento.

## Decisão

Tools novas em `tools/weldment.py` (wrapper `com/wrappers/weldment.py`,
domínio puro em `domain/weldment.py`):

- `list_weldment_profiles(standard?, type?)` — catálogo das pastas de perfil
  (preferência do usuário + `data\weldment profiles` da instalação); com
  filtro devolve os tamanhos.
- `insert_weldment_feature()` — marca a peça como weldment (idempotente).
- `insert_structural_member(standard, type, size, sketch, segments?, corner,
  connected, angle_deg, mirror, gap_mm)` — um grupo por chamada.
- `get_cut_list(update)` — itens com quantidade, comprimento, ângulos,
  material e todas as propriedades sob chave canônica em inglês.
- `insert_cut_list_table(view, x_mm, y_mm, template?)` — tabela no desenho.

`sw_status` passou a esconder os `.sldlfp` (perfis) que o SolidWorks abre
sozinho em segundo plano; só reporta `library_documents_hidden`.

## Aprendizados técnicos (SW2023 SP5 PT-BR, medidos ao vivo)

- `IStructuralMemberGroup.Segments` e o `Groups` de
  `InsertStructuralWeldment5` exigem `VARIANT(VT_ARRAY|VT_DISPATCH, [_oleobj_])`;
  lista Python de proxies gen_py faz o método devolver `None` sem erro.
- `ConnectedSegmentsOption=0` devolve `None`; usar `swConnectedSegments_SimpleCut`
  (1) ou `CopedCut` (2).
- `CornerTreatmentType` do grupo **não** segue `swCornerTreatmentTrim_e`. Num L
  de tubo 20×20 (300 + 200 mm), lendo a lista de corte: 0 e 1 → miter
  (45°/45°, 310 + 210); 2 → End Butt1 (1º inteiro 310, 2º aparado 190);
  3 → End Butt2 (1º aparado 290, 2º inteiro 210).
- Sem a feature Weldment (`WeldmentFeature`, "Soldagem") os corpos não viram
  `CutListFolder` — o wrapper a insere antes do membro.
- Tamanhos de perfil configurado = configurações do `.sldlfp`;
  `ISldWorks::GetConfigurationNames(path)` lê sem abrir.
- Propriedades da lista de corte vêm localizadas (COMPRIMENTO, ÂNGULO1,
  Descrição); a chave canônica está na fórmula `"LENGTH@@@…"`. MATERIAL aponta
  para `SW-Material`.
- `IPartDoc.FeatureByName` não existe em `IModelDoc2`; a busca é iterando
  `FirstFeature/GetNextFeature`.

## Corte normal ao tubo (laser) — receita que funcionou via API (2026-09-11)

Ideia do vídeo "Normalized Tube Cut" (Hawk Ridge): superfície regrada normal à
aresta interna da boca de lobo → Substituir face → apagar corpo de superfície.
Feito numa peça derivada, para não mexer na peça de origem:

1. `IPartDoc.InsertPart3(caminho, swInsertPartImportSolids, "")` numa peça nova
   (referência externa; `SaveToFile3` criou o arquivo mas sem corpo) e
   `InsertDeleteBody2(False)` nos corpos que não interessam.
2. Contorno = junção das arestas interna e externa da boca (em cada ângulo,
   o x mais recuado); só a interna deixa ~28 mm³ de interferência.
3. `InsertRuledSurfaceFromEdge2` devolve feature com erro 51 e some da árvore
   em TODOS os cenários testados (até tubo simples) — não usar. Substituto:
   amostrar a aresta interna da boca (`ICurve.GetTessPts`), projetar
   radialmente para r = 6 e r = 13 mm, duas splines em 3D sketch
   (`CreateSpline2` com VARIANT VT_R8) e `InsertLoftRefSurface2` = a mesma
   superfície radial.
4. `IModelDoc2.InsertFeatureReplaceFace()` com a face-alvo marca 1 e a FACE
   da superfície marca 2 (corpo de superfície não serve; marcas trocadas
   criam feature vazia sem erro).
5. `InsertDeleteBody2(False)` no corpo de superfície.

Outros fatos medidos: `InsertWrapFeature2` exige sketch marca 4 e face marca 1,
e o sketch precisa estar inteiro dentro da face (borda coincidente é aceita);
`InsertBends` (v1) funciona onde `InsertBends2` não cria nada, mas a
planificação falha (erro 51) num tubo com boca de lobo; feature com erro 51
é removida sozinha da árvore na reconstrução.

A receita virou a tool `normalize_tube_cut(body, check_against)` (wrapper
`weldment.normalize_tube_cut`; geometria pura em `domain.combine_outlines`).
Validada na Peça1 de teste: interferência com o outro tubo = 0 mm³. Aresta
aberta amostra-se com `ICurve.GetTessPts` entre os vértices — avaliar por
`GetCurveParams2` devolve trecho errado (30 mm) em curva de interseção
aberta; aresta fechada avalia-se por parâmetro. Identidade de faces via
ponteiro IUnknown (`IModelDocExtension.IsSame` não existe no typelib).

## Perfis novos (`create_weldment_profile`)

Perfil `.SLDLFP` criado do zero pela API: peça nova, sketch no Plano frontal
centrado na origem (círculos ou retângulo com cantos de raio 2×parede),
ponto na origem, propriedade `Description`, sketch selecionado e `SaveAs3`
com extensão `.sldlfp` — o SolidWorks monta sozinho a estrutura de Lib Feat
Part (Referências / Dimensões / Recurso de biblioteca). Layout de saída é o
legado da KONGZ: `<norma>\<tipo>\<tamanho>.SLDLFP`. Para perfis desse
layout o `ConfigurationName` de `InsertStructuralWeldment5` tem de ser ""
(vazio) — o nome da configuração ("Default"/"Valor predeterminado") faz o
método devolver None. Arquivos `~$*.SLDLFP` são locks e ficam fora do
catálogo. `InsertSketch` pode responder 0x80010105 logo após trocar de
documento e ainda assim ter executado: `modeling._insert_sketch_retry`
confere o estado antes de repetir.

## File Locations

`get_file_locations` / `set_file_location` / `apply_kongz_library` (wrapper
`settings.py`). File Locations respondem por `Get/SetUserPreferenceStringValue`
(lista separada por ';'); a variante `StringListValue` devolve "" e não grava
(medido no SW2023). O registro (`HKCU\...\ExtReferences`) só é atualizado
quando o SolidWorks fecha. Biblioteca KONGZ: `<raiz>\CAD\KONGZ_SolidWorks_Library\`
{`KONGZ_templates`, `sheetformat`, `data\weldment profiles`}.

Instância órfã: quando o usuário fecha a janela do SolidWorks, o processo
continua vivo (invisível) enquanto o servidor segurar a referência COM, e
`GetActiveObject` continua devolvendo esse órfão — configurações feitas nele
nunca chegam ao registro. `session.py` agora enumera a ROT
(`SolidWorks_PID_<n>`) e prefere a instância visível, trocando de instância
quando a atual fica invisível.

## Pendência conhecida

`SaveAs3` de uma peça **criada pela API com membro estrutural** devolve
`errors=1` (swGenericSaveError) e deixa um arquivo de 0 bytes travado pelo
processo — reproduzido com perfil da instalação e com cópia em pasta do
usuário, com e sem `Silent`, via `SaveAs3`/`SaveAs4`. Exportar a mesma peça para STEP funciona; peça só com a feature
Weldment salva normalmente, e a tabela de lista de corte foi validada num
desenho gerado a partir de peça salva pela UI. Investigar antes de depender
de "modelar quadro → salvar → desenho" sem passar pela UI.
