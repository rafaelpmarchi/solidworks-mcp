# ADR 0002 — pip + venv em vez de uv

**Data:** 2026-08-26 · **Status:** Aceito

## Contexto

A especificação sugeria `uv` para empacotamento/instalação. O `uv` não está instalado
na máquina de desenvolvimento.

## Decisão

Usar `python -m venv` + `pip install -e .[dev]`. O `pyproject.toml` é padrão
(setuptools), então migrar para `uv` no futuro é trivial (`uv sync` lê o mesmo arquivo).

## Consequências

- Instalação documentada no README com venv/pip.
- Sem lockfile por ora; dependências com versões mínimas no `pyproject.toml`.
