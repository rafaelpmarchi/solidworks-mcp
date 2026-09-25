# ADR 0008 — Referências de montagem: mates pela geometria, réplica e substituição

**Data:** 2026-09-25 · **Status:** Aceito

## Contexto

Na prateleira, o usuário montou um porta-etiqueta num rasgo da bandeja com 4
mates e pediu para colocá-lo nos outros 3 rasgos **seguindo as mesmas
referências**, não fixo por coordenada. Foi feito por `run_sw_script`: ler os
mates do original, achar as entidades correspondentes do rasgo vizinho e
refazer os mates. Na mesma sessão uma bandeja foi trocada por outro arquivo
(`ReplaceComponents2`). O usuário pediu que tudo isso fosse para o MCP.

## Decisão

`com/wrappers/assembly_refs.py` + tools em `tools/assembly.py`:

- `list_mates(component)`: tipo, alinhamento, flip, valor e entidades (kind,
  ponto, direção, raio) em coordenadas da montagem.
- `select_component_entity(component, kind, point_mm, direction?, radius_mm?)`:
  face plana/cilíndrica, aresta reta/circular, vértice ou plano de referência,
  achados pela geometria e selecionados pelo objeto.
- `add_mate(..., alignment)`: closest / aligned / anti_aligned.
- `replicate_component(source, offsets_mm)`: cópia com a rotação do original,
  transladada, e cada mate refeito nas entidades deslocadas pelo mesmo offset;
  confere `moved_mm == 0` (se os mates movem a cópia, a referência pegou a
  entidade errada).
- `replace_component(component, new_path, all_instances)` e `mate_errors()`.
- `component_transform(component)`.

A matemática (inversa da transformada, casamento de plano/reta/eixo) fica em
`domain/placement.py` e `domain/entity_match.py`, testada sem SolidWorks.

## Aprendizados técnicos (SW2023 SP5 PT-BR, medidos ao vivo)

- `IMateEntity2.EntityParams` traz um ponto **qualquer** do plano/reta
  infinitos — a ponta de um rasgo veio com y = 450, 50 mm fora da face. Achar a
  entidade de volta é teste geométrico (a face está NO plano), e quando várias
  estão no mesmo plano (pontas de dois rasgos alinhados) desempata a mais
  perto de um ponto de referência (centro da cópia).
- Corpos de `IComponent2.GetBodies3` estão em coordenadas da **peça**, mas
  suas faces/arestas selecionam no contexto da montagem (`IEntity.Select4`):
  leva-se o ponto da montagem para a peça antes de comparar.
- `IAssemblyDoc.AddComponent5(x, y, z)` põe o **centro da caixa** do
  componente em (x, y, z), não a origem da peça. `insert_component` agora
  sempre reposiciona pela origem (é o que a tool promete).
- Face com direção sem raio casava o **cilindro** do pino quando o ponto
  estava no eixo: cilindro/círculo só entram quando `radius_mm` é informado.
- `AddMate5` devolve `(mate, swAddMateError)`: 1 = ok, 5 = montagem
  sobredefinida (foi o sintoma do item acima), 3 = alinhamento incorreto.
- `GetBodies3` pelo pywin32 às vezes devolve `(corpos, tipos)`.
