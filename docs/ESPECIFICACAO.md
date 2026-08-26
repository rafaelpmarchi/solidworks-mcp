# SolidWorks MCP Server — Especificação do Projeto

**Projeto:** `solidworks-mcp` (nome de trabalho)
**Data:** 2026-08-26 · **Status:** Rascunho aprovado para início
**Contexto:** Gromar — usinagem e solda (Stellite/TP7000) para componentes de turbina. Desenhos 2D são o documento de contrato com a fábrica; erro de cota/tolerância vira refugo caro.

---

## 1. Visão

Um servidor MCP em Python que expõe o SolidWorks (via COM) como ferramentas para o Claude Code, permitindo que o agente **leia, revise e crie desenhos 2D** com julgamento — não apenas macros gravadas. O SolidWorks permanece aberto e visível na máquina do usuário; o agente trabalha ao lado, nunca escondido.

**Decisão de origem:** partir do zero. Os projetos open-source avaliados (`jianzhichun/solidworks-mcp-server` e similares) foram descartados como base de código por três defeitos estruturais:

1. Ponte COM do Node (`winax`) falha em métodos com 13+ parâmetros — e a API de desenho do SolidWorks é feita desses métodos (admitido no próprio README do projeto).
2. 69 chamadas COM com optional-chaining (`method?.()`) que silenciam falha e retornam `success: true` sem executar nada.
3. Zero testes cobrindo desenho.

Deles aproveitamos apenas **conhecimento**: tabela de constantes da API e templates VBA como referência de chamadas (guardados em `reference/`, fora do código de produção).

## 2. Objetivos

| # | Objetivo | Resultado mensurável |
|---|---|---|
| O1 | **Leitura completa de desenho** — folhas, vistas, cotas, tolerâncias, anotações, notas, legendas, propriedades customizadas de um `.SLDDRW` | Dump estruturado (JSON) de um desenho real da Gromar, fiel ao que está na tela |
| O2 | **Revisão automática de desenho** — o agente aponta problemas: cota sem tolerância em superfície crítica, GD&T sem datum, nota de solda incompleta, material divergente, legenda desatualizada | Relatório de revisão de um SLDDRW real com achados verificáveis (sem falso "está tudo certo") |
| O3 | **Criação assistida de desenho 2D** — a partir de peça 3D: abrir template Gromar, inserir vistas padrão, escala, preencher legenda via propriedades, importar cotas do modelo (`InsertModelAnnotations3`) | Desenho ~80% pronto gerado de uma peça de teste; projetista finaliza a cotagem |
| O4 | **Operações em lote** — aplicar O1–O3 sobre listas de arquivos (revisar pasta inteira, atualizar legenda de família de peças) | Batch sobre N arquivos com relatório por arquivo, sem travar o SolidWorks |
| O5 | **Integração com o ERP Mavito** (fase posterior) — cruzar dados do desenho com o cadastro do produto (material, código, revisão) | Divergência desenho×cadastro apontada na revisão |

### 2.1 Não-objetivos (explícitos)

- **Cotagem "inteligente" autônoma.** Decidir quais cotas o operador precisa e a partir de qual referência é trabalho de projetista. O sistema importa cotas do modelo e monta o desenho; não substitui a decisão de cotagem funcional.
- **Modelagem 3D generativa** (criar peças por texto). Fora de escopo — o valor está no desenho 2D e na revisão.
- **PDM/gestão de arquivos.** Não somos cofre; trabalhamos nos arquivos que o usuário indicar.
- **Rodar sem SolidWorks aberto/instalado.** COM exige a aplicação na mesma máquina.

## 3. Requisitos

### 3.1 Funcionais

**RF-01 Conexão** — Conectar à instância aberta do SolidWorks (`GetActiveObject`) ou abrir uma nova sob demanda; reportar versão e documentos abertos.
**RF-02 Documentos** — Abrir/ativar/fechar/salvar `.SLDDRW`, `.SLDPRT`, `.SLDASM`; identificar tipo e estado (salvo/modificado, somente-leitura).
**RF-03 Leitura de desenho** — Enumerar folhas (nome, formato, escala), vistas (tipo, modelo referenciado, configuração, escala, posição), cotas (valor, tolerância, tipo, marcada para inspeção), anotações (GD&T, acabamento, solda, notas de texto), tabelas (revisão, furos, BOM) e legenda/propriedades.
**RF-04 Leitura de modelo** — Do 3D referenciado: propriedades customizadas, material, massa, caixa envolvente, lista de features, configurações.
**RF-05 Revisão** — Regras de verificação executadas sobre o dump de leitura (camada Python pura, testável sem SolidWorks) + síntese pelo agente. Regras da Gromar em arquivo de configuração versionado, não hardcoded.
**RF-06 Criação de desenho** — Novo desenho a partir de template indicado; inserir vistas padrão/projetadas/seção; definir escala; importar anotações do modelo; preencher legenda a partir de propriedades.
**RF-07 Edição pontual** — Atualizar propriedade customizada, texto de nota, célula de tabela de revisão. Toda escrita declara antes o que vai alterar.
**RF-08 Exportação** — PDF, DXF, DWG, STEP de documento aberto ou por caminho; em lote.
**RF-09 Lote** — Qualquer operação de leitura/exportação aplicável a lista de arquivos ou pasta+padrão, com relatório por item e continuação após falha individual.

### 3.2 Não-funcionais

**RNF-01 Sem falha silenciosa (inegociável).** Toda chamada COM que falhe levanta exceção com método, argumentos e HRESULT. Nenhuma tool retorna sucesso sem efeito verificado. Proibido `getattr` defensivo/equivalente de `?.()` em chamada COM.
**RNF-02 COM single-threaded.** Todas as chamadas COM serializadas numa única STA thread (fila + worker). O servidor MCP pode ser async; o COM nunca é concorrente.
**RNF-03 Unidades na fronteira.** API interna do SolidWorks trabalha em metros/radianos; conversão para mm/graus em um único módulo (`units.py`). Tudo que o agente vê é mm/graus, documentado nos schemas.
**RNF-04 Leitura nunca altera.** Tools de leitura não disparam rebuild que modifique o arquivo, não salvam, não mudam configuração ativa sem restaurar.
**RNF-05 Escrita segura.** Tools de escrita separadas das de leitura (nomes distintos, `write_` ou verbo explícito); nunca sobrescrever arquivo sem o documento ter sido salvo antes por decisão explícita; suportar dry-run onde couber.
**RNF-06 Testável sem SolidWorks.** Camada COM isolada atrás de interface; domínio e regras de revisão testam com fixtures JSON. Testes de integração (com SolidWorks real) separados e opcionais.
**RNF-07 Robustez de sessão.** SolidWorks fechado/travado no meio da operação → erro claro + reconexão sob demanda, sem derrubar o servidor.
**RNF-08 Logs.** Toda chamada COM logada (método, duração, resultado/erro) em arquivo rotativo; nível configurável.
**RNF-09 Compatibilidade.** Alvo: versão do SolidWorks instalada na Gromar (a confirmar — RISCO R3). Métodos versionados (`*2`, `*3`…) centralizados na camada COM para facilitar upgrade.

## 4. Arquitetura

### 4.1 Camadas

```
┌─────────────────────────────────────────────────┐
│  MCP Server (FastMCP / mcp SDK)                 │  tools, schemas (pydantic),
│  server/                                        │  descrições p/ o agente
├─────────────────────────────────────────────────┤
│  Domínio                                        │  modelos de dados (Drawing,
│  domain/  + review/ (regras de revisão)         │  View, Dimension…), regras —
│                                                 │  PYTHON PURO, zero COM
├─────────────────────────────────────────────────┤
│  Serviços SolidWorks                            │  casos de uso: ler desenho,
│  services/                                      │  criar vistas, exportar, lote
├─────────────────────────────────────────────────┤
│  Ponte COM                                      │  única camada que toca
│  com/  (STA worker + wrappers tipados)          │  win32com; serialização,
│                                                 │  erros, unidades, constantes
└─────────────────────────────────────────────────┘
                    │ pywin32 (COM)
              SolidWorks (instância aberta)
```

**Regra de dependência:** de cima para baixo, nunca o contrário. `domain/` e `review/` não importam nada de `com/` — é isso que torna a revisão testável com fixtures.

### 4.2 Padrões adotados (e por quê)

- **Ports & Adapters (hexagonal).** `services/` define o que precisa do CAD via interface (`Protocol`); `com/` implementa. Permite fake em testes e, no limite, outro CAD.
- **Command queue / STA worker.** Um thread dedicado com `pythoncom.CoInitialize`; chamadas entram por fila, resultados voltam por future. Resolve RNF-02 sem espalhar locks.
- **Fail-fast com erro rico.** Wrapper único para invocação COM: captura `com_error`, traduz HRESULT, anexa método+args. Resolve RNF-01 num lugar só.
- **DTOs imutáveis (pydantic/dataclasses frozen)** na fronteira das camadas — o dump de leitura (RF-03) é um documento serializável, não objetos COM vazando.
- **Rule engine simples para revisão:** cada regra é uma função `(DrawingDump, Config) -> list[Finding]` registrada por decorator. Regras da Gromar entram como dados (`review/rules/*.yaml` + funções), não como if's no serviço.
- **Sem herança profunda, sem framework mágico.** Módulos e funções; classes só onde há estado real (sessão COM, worker).

### 4.3 Estrutura de diretórios

```
solidworks/
├── docs/
│   ├── ESPECIFICACAO.md          # este documento
│   └── decisoes/                 # ADRs curtos (uma decisão por arquivo)
├── reference/                    # material dos projetos avaliados (não é código nosso)
│   ├── constantes-api.md
│   └── vba-templates/
├── src/
│   └── swmcp/
│       ├── __init__.py
│       ├── server.py             # entrypoint MCP: registra tools, valida schemas
│       ├── tools/                # uma família de tools por arquivo
│       │   ├── connection.py     # RF-01, RF-02
│       │   ├── read_drawing.py   # RF-03
│       │   ├── read_model.py     # RF-04
│       │   ├── review.py         # RF-05
│       │   ├── create_drawing.py # RF-06
│       │   ├── edit.py           # RF-07
│       │   ├── export.py         # RF-08
│       │   └── batch.py          # RF-09
│       ├── services/
│       │   ├── ports.py          # Protocols (interfaces p/ o CAD)
│       │   ├── drawing_reader.py
│       │   ├── drawing_builder.py
│       │   ├── exporter.py
│       │   └── batch_runner.py
│       ├── domain/
│       │   ├── drawing.py        # DrawingDump, Sheet, View, Dimension, Annotation…
│       │   ├── model.py          # propriedades, material, massa
│       │   └── findings.py       # Finding, Severity, Report
│       ├── review/
│       │   ├── engine.py
│       │   ├── rules/            # uma regra por função; config Gromar em YAML
│       │   └── gromar.yaml       # tolerâncias padrão, campos obrigatórios de legenda…
│       └── com/
│           ├── session.py        # conectar/reconectar, versão, docs abertos
│           ├── worker.py         # STA thread + fila (RNF-02)
│           ├── invoke.py         # wrapper fail-fast (RNF-01)
│           ├── units.py          # RNF-03 — único ponto de conversão
│           ├── constants.py      # swDocDRAWING=3 etc., com nome e fonte
│           └── wrappers/         # funções tipadas por área da API
│               ├── document.py
│               ├── drawing.py
│               ├── dimension.py
│               └── annotation.py
├── tests/
│   ├── unit/                     # domínio + revisão, fixtures JSON, sem SolidWorks
│   ├── fixtures/                 # dumps reais anonimizados de desenhos Gromar
│   └── integration/              # exige SolidWorks aberto; marcados, não rodam no CI padrão
├── pyproject.toml                # uv/pip; deps: mcp, pydantic, pywin32, pyyaml
└── README.md
```

### 4.4 Stack

| Item | Escolha | Justificativa |
|---|---|---|
| Linguagem | Python 3.13 (`py -V:3.13` na máquina) | pywin32 maduro; 3.14 é muito recente para pywin32 em produção — validar na Fase 0, senão usar 3.13 |
| COM | `pywin32` (win32com) | Suporta VARIANT por referência e métodos com N parâmetros — exatamente onde a ponte Node falha |
| MCP | SDK oficial `mcp` (FastMCP) | Padrão, schemas via pydantic |
| Validação | `pydantic` v2 | Schemas das tools + DTOs |
| Config | `pyyaml` | Regras Gromar como dados |
| Testes | `pytest` + fixtures JSON | RNF-06 |
| Empacote | `pyproject.toml` + `uv` | Instalação reproduzível |

## 5. Contratos das tools (resumo da fase 1)

Nomes definitivos na implementação; princípios: leitura usa substantivo (`get_`, `list_`), escrita usa verbo explícito, tudo em mm/graus, respostas sempre com `success` **verificado** e nunca inferido.

- `sw_status` — versão, docs abertos, doc ativo
- `sw_open_document(path)` / `sw_close_document(save=False)`
- `get_drawing_dump(path?, sheets?)` — o coração do O1: dump completo em JSON
- `get_model_properties(path?)` — propriedades, material, massa
- `review_drawing(path?, ruleset='gromar')` — dump + engine → `Report`
- `export_document(path?, format, output)` / `batch_export(...)`
- *(fase 2)* `create_drawing_from_model(model_path, template, views=[...])`, `fill_title_block(...)`, `insert_model_annotations(...)`

## 6. Roadmap

| Fase | Entrega | Critério de aceite |
|---|---|---|
| **0. Fundação** (primeira) | `com/` completo: session, STA worker, invoke fail-fast, units + `sw_status` funcionando de ponta a ponta no MCP | Claude Code conecta e lê versão + docs abertos do SolidWorks real; matar o SW no meio produz erro claro e reconexão |
| **1. Leitura** | `get_drawing_dump` + `get_model_properties` validados contra o SLDDRW cobaia da Gromar | Dump JSON confere com o desenho na tela (cotas, tolerâncias, notas, legenda) — verificação manual assistida |
| **2. Revisão** | Engine + primeiras regras Gromar (`gromar.yaml`) + `review_drawing` | Relatório sobre desenho real com ≥1 achado verdadeiro conhecido e zero falso "ok"; regras testadas com fixtures |
| **3. Criação** | Template → vistas → legenda → `InsertModelAnnotations3` | Desenho gerado de peça de teste, abrível e editável, legenda correta |
| **4. Lote + export** | `batch_*` sobre pasta real | N arquivos processados com relatório por item, SW estável ao final |
| **5. ERP Mavito** | Cruzamento desenho×cadastro na revisão | Divergência de material/código apontada |

Fase 0 não depende do arquivo cobaia — pode começar imediatamente. Fases 1–2 precisam do caminho do SLDDRW e da versão do SolidWorks (pendências abertas com o usuário).

## 7. Riscos

| # | Risco | Mitigação |
|---|---|---|
| R1 | pywin32 no Python 3.14 (instalado como default) com comportamento imaturo | Smoke test na Fase 0; fallback imediato ao 3.13 já presente na máquina |
| R2 | API COM instável em sessão longa (memória, referências pendentes) | Worker libera referências por operação; `batch` reabre documento a cada item; reconexão automática |
| R3 | Versão do SolidWorks da Gromar não confirmada → métodos `*3`/`*4` divergentes | Detectar versão em `session.py` na conexão; wrappers centralizam a escolha do método |
| R4 | Dump de leitura incompleto (anotação exótica não mapeada) | Dump inclui seção `unrecognized[]` com tipo bruto — nunca omitir silenciosamente (coerente com RNF-01) |
| R5 | Escrita corromper desenho de produção | Fases 0–2 são somente-leitura; escrita chega na Fase 3 sob RNF-05, testada primeiro em cópias |
| R6 | Licença/edição do SolidWorks sem algum recurso de API | Verificar edição na Fase 0 e registrar em ADR |

## 8. Convenções

- Código e identificadores em inglês; docstrings, mensagens ao usuário e documentação em português (pt-BR).
- Commits: convencionais (`feat:`, `fix:`, `docs:`…), corpo em português.
- Toda decisão de arquitetura relevante vira ADR curto em `docs/decisoes/`.
- `main` sempre instalável; integração com SolidWorks real testada antes de merge de mudanças em `com/`.

## 9. Pendências para o usuário

1. **Caminho de um `.SLDDRW` cobaia** representativo (com legenda e convenções Gromar) — habilita Fases 1–2.
2. **Confirmar versão/edição do SolidWorks** (ou autorizar detecção automática via registro na Fase 0).
3. **Regras de revisão da Gromar** — para a Fase 2, levantar com o projetista: campos obrigatórios de legenda, tolerâncias padrão por classe, exigências de nota de solda/acabamento.
