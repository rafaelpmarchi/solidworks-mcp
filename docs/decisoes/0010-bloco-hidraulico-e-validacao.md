# ADR 0010 — Bloco hidráulico: pórtico, canal inclinado, validação e desenho em PDF

**Data:** 2026-09-30 · **Status:** Aceito

## Contexto

Modelagem do cilindro Siemens 3-50200-92000-00D (bloco 250×250×333, 60 furos,
~100 kg) a partir do PDF do cliente, no padrão Gromar do 3-50200-92309 (perfil
torneado + fresa do quadrado + pastas de furos por face). Quase tudo foi
`run_sw_script`, e o que deu errado virou lista de lições:

- **Rebaixo customizado do assistente não funciona no SW2023.** Legado
  (`swCounterBoredDrilled`) ignora Ø/profundidade do rebaixo e sai furo
  simples; avançado (`swWzdCounterBore`) sai na norma em polegada
  (50,8 × 31,75); `ModifyDefinition` não altera. Os pórticos saíram como dois
  furos (canal + rebaixo plano).
- **Furo feito a partir da face do bloco deixa aba** quando o rebaixo invade
  um ressalto de interface de válvula (0,5 mm) — o usuário achou na tela.
- **Furo que termina exatamente na parede de outro** (66 mm num Ø118 de raio
  59) dá `swFeatureError` 51, e a massa medida com ele em erro parecia certa
  (100,03 kg) — a feature em erro não cortava nada.
- Canais Ø7 inclinados (10°, 7,5°, 12,5°) exigiram plano auxiliar + corte
  por revolução, tudo à mão.
- `SelectByID2` com o ponto em cima da face falha; `MathUtility.CreatePoint`
  com lista Python corrompe as coordenadas (precisa VARIANT);
  `ReorderFeature` devolve False mesmo movendo.
- `revolve` com perfil de eixo vertical (Z = eixo, esboço no Plano superior)
  gerou 40 cotas "diâmetro" absurdas em 3 minutos e ficou sub-definido.
- `hole_wizard` tentava a norma a cada furo, o SW ignorava, e refazia pelo
  legado: ~15 s por furo.
- Testes de API por tentativa-e-erro criaram e apagaram features na peça que o
  usuário estava vendo ("está dando bastante erro, não dá pra validar antes?").
- Ler o PDF A0 da Siemens: extração vetorial não serviu (linhas picadas, só
  hachura); o que funcionou foi renderizar cada vista a 200-300 dpi e medir
  pela escala da vista.

## Decisão

- `domain/ports.py` (puro, testado): tabela G1/8..G3/4 (d2/b/t da tabela
  Siemens "ähnlich DIN EN ISO 1179-1", broca e Ø menor ISO 228), meio-perfil
  do pórtico (rebaixo + broca da rosca + canal + ponta 118°) começando 5 mm
  FORA da face, escolha do plano base que contém o eixo, direção por ângulo.
- `com/wrappers/channels.py`: `revolved_axis_cut` (plano paralelo auxiliar
  escondido e nomeado, esboço amarrado, volume removido e erro conferidos —
  falhou, desfaz tudo), `port_hole`, `angled_channel` (com `target_mm` passa
  1,5 mm além do destino), `sketch_on_face` (coordenadas da peça, recusa ponto
  fora do plano), `batch_holes` (redesenho desligado, relatório por item).
- `validate.py`: `validate_model` (reconstrução + esboços + corpos + massa do
  carimbo; massa marcada como não confiável com feature em erro) e
  `dump_holes` (furação de uma peça de referência em coordenadas da peça).
- `repair.organize_tree`: renomeia, reordena conferindo a ordem real e cria as
  pastas; `edit.copy_properties_from`; `output.view_face`.
- `run_sw_script`: helpers (`feature`, `tree_order`, `select_face`,
  `ray_select`, `to_sketch`, `to_model`, `darr`) e `scratch=True` (peça
  descartável, documento do usuário intacto).
- `hole_wizard` lembra, por sessão, a norma/tipo em que o assistente já
  ignorou o tamanho e vai direto pelo legado.
- `fully_dimension_profile` recusa perfil fora da convenção (eixo horizontal
  em y=0) antes de mexer; `revolve` cai no `fully_define_sketch` geral.
- `services/pdf_drawing.py` + `tools/pdf.py`: `pdf_drawing_info`,
  `pdf_drawing_crop` (PNG da vista + mm por pixel pela escala) e
  `pdf_compare_table` (tabela A3 com recorte vetorial por cota). PyMuPDF
  entra como dependência.

### Adendo (mesmo dia): edição do perfil torneado

A correção do U1 (canal Ø200,8/Ø180,8 × 4 com R1,6) e do chanfro do Ø110 no
perfil do 92000, por script, bateu em: arco de entrada saindo como arco MAIOR
(+10 000 mm³ onde a conta dava +816 — pego só pela conta de Pappus), linha
"grudando" no arco pela inferência, `SetCoords` bloqueado por cota, e cotagens
repetidas acumulando 209 relações até o esboço ficar sub/sobredefinido sem
explicação. Viraram tools:

- `domain/undercut.relief_groove` + `profile_edit.sketch_relief_groove`: o
  canal U1 no canto, linhas encurtadas, arcos curtos conferidos, cotado.
- `profile_edit.sketch_redefine`: apaga TODAS as cotas (pelo nome completo) e
  relações, põe só relações de forma (H/V; tangência só onde a geometria é
  tangente de fato — nunca o arco de entrada com a parede) e cota uma vez.
- `remove_sketch_chamfer` / `move_sketch_chamfer` (pontas exatas; troca as
  distâncias se o SolidWorks as aplicar ao contrário).
- `domain/profile` + `profile_volume`: volume teórico do perfil com arcos e
  lista de arcos maiores que meia volta.
- `sketch_arc` confere o comprimento e refaz no outro sentido (arco curto).
- `fillet_circular_edges`, `set_hole_depth` (desfaz se der erro),
  `replace_hole_with_channel` (canal no lugar do furo na árvore).
- `validate_model` avisa esboço com cotas demais para as entidades.

Teste ao vivo: `tests/integration/test_profile_edit_real.py`.

## Consequências

- Pórtico sai numa feature de corte por revolução, não "Furo" do assistente:
  a árvore fica com o nome do pórtico, mas sem os dados de furo do assistente
  (tabela de furos do desenho não os enxerga). Aceito: o assistente não
  consegue fazer a geometria certa nesta instalação.
- Canal inclinado só dentro de um plano de vista (perpendicular a um plano
  base) — é o caso de todo bloco que vimos; oblíquo nos três dá erro claro.
- Teste de integração `tests/integration/test_machining_real.py` cobre tudo
  em peças descartáveis.
