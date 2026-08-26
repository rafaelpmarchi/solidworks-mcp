# Plano de Execução — MVP (Fases 0–2)

**Base:** `docs/ESPECIFICACAO.md` · **Data:** 2026-08-26 · **Status:** Proposto

## Definição do MVP

O MVP entrega **revisão automática de um desenho real da Gromar**: o Claude Code conecta ao SolidWorks aberto, extrai o dump completo de um `.SLDDRW` (O1) e produz um relatório de revisão com achados verificáveis (O2). Cobre RF-01 a RF-05, todo em modo **somente-leitura** — nenhuma tool de escrita entra no MVP (mitiga R5 por construção).

**Fora do MVP:** criação de desenho (RF-06/07), exportação (RF-08), lote (RF-09), integração ERP (O5).

**Critério de sucesso do MVP:** rodar `review_drawing` sobre o SLDDRW cobaia e obter um relatório com ≥1 achado verdadeiro conhecido pelo projetista e zero falso "está tudo certo", com o dump conferido manualmente contra a tela.

---

## Etapa 0 — Bootstrap do projeto (½ dia)

Sem dependências externas. Pode começar imediatamente.

- [ ] `pyproject.toml` com `uv`; deps: `mcp`, `pydantic`, `pywin32`, `pyyaml`, `pytest` (dev)
- [ ] Esqueleto de diretórios conforme §4.3 da especificação (`src/swmcp/`, `tests/`, `reference/`)
- [ ] `git init`, primeiro commit, `README.md` mínimo (como instalar e registrar o MCP no Claude Code)
- [ ] **Smoke test R1:** `pywin32` no Python 3.14 default → se qualquer instabilidade, fixar 3.13 (`py -V:3.13`) e registrar ADR
- [ ] Logging básico configurado (arquivo rotativo, RNF-08)

**Gate:** `uv sync` limpo + `pytest` roda (mesmo vazio) + decisão de versão do Python registrada em `docs/decisoes/`.

## Etapa 1 — Fundação COM (Fase 0 da spec) (2–4 dias)

Coração do risco técnico. Não depende do arquivo cobaia.

Ordem de construção (cada item testável antes do próximo):

1. `com/worker.py` — STA thread + fila + futures (RNF-02). Testável sem SolidWorks (worker executa callables genéricos).
2. `com/invoke.py` — wrapper fail-fast: captura `com_error`, traduz HRESULT, anexa método+args (RNF-01). Teste unitário com COM fake que falha.
3. `com/session.py` — `GetActiveObject` → fallback para abrir instância; versão, edição (R6), docs abertos; reconexão sob demanda (RNF-07).
4. `com/units.py` — m→mm, rad→graus, único ponto de conversão (RNF-03). Teste unitário puro.
5. `com/constants.py` — constantes com nome e fonte (a partir de `reference/constantes-api.md`).
6. `server.py` + `tools/connection.py` — tool `sw_status` de ponta a ponta no MCP.

**Gate (aceite da Fase 0):** Claude Code conecta e lê versão + docs abertos do SolidWorks real; matar o SW no meio da operação produz erro claro e a próxima chamada reconecta. Edição/licença registrada em ADR (R6).

## Etapa 2 — Leitura (Fase 1 da spec) (4–7 dias)

**Pré-requisito:** caminho do SLDDRW cobaia (pendência #1) e versão do SW confirmada (pendência #2 — a detecção da Etapa 1 resolve).

1. `domain/drawing.py` + `domain/model.py` — DTOs frozen (DrawingDump, Sheet, View, Dimension, Annotation, TitleBlock…). Primeiro, porque define o contrato de tudo que vem depois.
2. `com/wrappers/document.py` — abrir/ativar/fechar sem salvar (RF-02, RNF-04) + tools `sw_open_document`/`sw_close_document`.
3. `com/wrappers/drawing.py` + `dimension.py` + `annotation.py` — enumeração incremental, nesta ordem de valor:
   - folhas e vistas → cotas + tolerâncias → notas/legenda/propriedades → GD&T, acabamento, solda → tabelas
   - Tudo que não for reconhecido vai para `unrecognized[]` com tipo bruto (R4) — nunca omitir.
4. `services/drawing_reader.py` atrás de `ports.py` (Protocol) + tool `get_drawing_dump`.
5. `com/wrappers/` p/ modelo 3D + tool `get_model_properties` (RF-04): propriedades, material, massa.
6. **Fixture real:** salvar o dump do cobaia (anonimizado se preciso) em `tests/fixtures/` — vira insumo direto da Etapa 3.

**Gate (aceite da Fase 1):** verificação manual assistida — dump JSON confere item a item com o desenho na tela (cotas, tolerâncias, notas, legenda). `unrecognized[]` vazio ou com itens explicados. Leitura comprovadamente não altera o arquivo (timestamp/estado "salvo" intactos, RNF-04).

## Etapa 3 — Revisão (Fase 2 da spec) (3–5 dias)

**Pré-requisito:** fixture da Etapa 2 + regras levantadas com o projetista (pendência #3 — **iniciar esse levantamento já durante a Etapa 1**, é o caminho crítico não-técnico).

1. `domain/findings.py` — Finding, Severity, Report.
2. `review/engine.py` — registro por decorator, `(DrawingDump, Config) -> list[Finding]`. Python puro, zero COM.
3. `review/gromar.yaml` + primeiras regras, sugestão de ordem por valor/simplicidade:
   - campos obrigatórios de legenda preenchidos (material, código, revisão, escala)
   - cota sem tolerância em superfície marcada como crítica/inspeção
   - GD&T sem datum referenciado
   - nota de solda incompleta (padrão Gromar)
   - material da legenda ≠ material do modelo 3D
4. Testes unitários de cada regra com fixtures JSON (RNF-06) — incluindo casos onde a regra **não** deve disparar.
5. `services/` + tool `review_drawing(path?, ruleset='gromar')` — dump + engine → Report; síntese em prosa fica com o agente, não com o código.

**Gate (aceite da Fase 2 = aceite do MVP):** relatório sobre o desenho real com ≥1 achado verdadeiro conhecido e zero falso "ok"; todas as regras com testes de fixture passando; demo com o projetista validando os achados.

---

## Sequência e paralelismo

```
Etapa 0 ──► Etapa 1 (COM) ──► Etapa 2 (Leitura) ──► Etapa 3 (Revisão)
                 │                                        ▲
                 └── em paralelo: levantar regras Gromar ─┘
                     com o projetista (pendência #3)
```

Estimativa total: **~2 a 3 semanas** de trabalho efetivo, dominada pela Etapa 2 (a superfície da API de leitura é grande e cada tipo de anotação é um caso).

## Riscos ativos no MVP (da spec §7)

| Risco | Onde é tratado no plano |
|---|---|
| R1 pywin32/Python 3.14 | Smoke test na Etapa 0, fallback 3.13 |
| R3 versão SW não confirmada | Detecção na Etapa 1 (session.py); wrappers centralizam métodos versionados |
| R4 anotação não mapeada | `unrecognized[]` obrigatório desde o primeiro wrapper de leitura |
| R6 edição/licença sem recurso | Verificação e ADR na Etapa 1 |
| R2 sessão longa instável | Fora do caminho crítico do MVP (sem lote); reconexão da Etapa 1 é suficiente |

## Pendências que destravam o plano

1. **Caminho do `.SLDDRW` cobaia** — bloqueia o gate da Etapa 2 (o desenvolvimento até lá não bloqueia).
2. **Versão/edição do SolidWorks** — resolvida automaticamente pela detecção na Etapa 1, salvo objeção.
3. **Regras de revisão com o projetista** — bloqueia a Etapa 3; iniciar levantamento durante a Etapa 1.
