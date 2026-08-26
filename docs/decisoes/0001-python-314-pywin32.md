# ADR 0001 — Python 3.14 com pywin32

**Data:** 2026-08-26 · **Status:** Aceito

## Contexto

A especificação (R1) previa Python 3.13 como alvo, com smoke test do pywin32 no 3.14
(default da máquina) antes de decidir.

## Decisão

Usar **Python 3.14** (`C:\Python314`, default via `py`). O smoke test passou:
`pywin32` instala e `pythoncom.CoInitialize()` + `win32com.client` importam sem erro
no 3.14.3.

## Consequências

- `requires-python = ">=3.13"` mantém o 3.13 como fallback imediato se o COM real
  apresentar instabilidade na Etapa 1 (a máquina tem o 3.13 instalado).
- Qualquer regressão observada com o SolidWorks real reverte esta decisão — registrar
  novo ADR se acontecer.
