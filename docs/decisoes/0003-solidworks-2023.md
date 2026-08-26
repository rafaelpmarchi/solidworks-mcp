# ADR 0003 — SolidWorks 2023 detectado (R3)

**Data:** 2026-08-26 · **Status:** Aceito

## Contexto

R3 da especificação: versão do SolidWorks da Gromar não confirmada. A detecção
automática na conexão (autorizada pelo plano) reportou nesta máquina:

- `RevisionNumber` = **31.5.0** → **SolidWorks 2023** SP5.

## Decisão

Alvo de compatibilidade: **SolidWorks 2023**. Os wrappers usam os métodos
versionados disponíveis nessa versão (`OpenDoc6`, `ActivateDoc3`,
`InsertModelAnnotations3`…). A escolha do sufixo fica centralizada em
`com/wrappers/` — upgrade futuro mexe num lugar só (RNF-09).

## Pendências

- Edição/licença (R6) ainda não verificada por API — confirmar quando a
  necessidade de um recurso específico surgir (ex.: eDrawings API).
- Confirmar se a máquina da Gromar usa a mesma versão que esta máquina de
  desenvolvimento.
