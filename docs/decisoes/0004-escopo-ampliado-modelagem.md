# ADR 0004 — Escopo ampliado: modelagem e escrita via MCP

**Data:** 2026-08-26 · **Status:** Aceito

## Contexto

A especificação original listava "modelagem 3D generativa" como não-objetivo.
O usuário pediu explicitamente o oposto: "quero que seja possível fazer tudo
que eu posso fazer no SolidWorks" pelo chat/MCP.

## Decisão

O servidor MCP passa a expor escrita ampla, mantendo as salvaguardas RNF-05:

- **Modelagem**: new_document, sketch (linha, círculo, retângulo, arco,
  polígono), extrude/corte, revolve, filete, chanfro, casca, plano de
  referência, seleção por nome/coordenada, rebuild.
- **Edição**: propriedades customizadas, material, valor de cota, suprimir/
  apagar feature, configurações.
- **Montagem**: inserir componente, mates básicos.
- **Desenho 2D**: create_drawing_from_model com vistas padrão + importação de
  cotas (Fase 3 do roadmap, antecipada).
- **Saída**: save/save_as/export (PDF, STEP, DXF, DWG, STL, PNG...),
  screenshot (o agente confere visualmente o que modelou).

Salvaguardas: nada é salvo em disco sem save explícito; sobrescrever exige
overwrite=True; apagar feature documentado como destrutivo (agente deve
confirmar com o usuário); documentos novos ficam abertos e não salvos.

## Aprendizados técnicos (SW2023 PT-BR)

- `app` precisa de cast explícito a ISldWorks (gen_py) — byref volta em tupla.
- Cast ISketch→IFeature resolve dispid errado; nome do sketch via
  FeatureByPositionReverse(0).
- FeatureFillet3 tem 14 argumentos (7 escalares + 7 arrays None).
- Vistas nomeadas são localizadas ("*Frontal", "*Isométrica") — candidatos
  EN/PT por vista.
- Constantes de enum vêm do swconst.tlb via makepy (`swconst()`), não de
  valores chutados.
