"""Engine de revisão: cada regra é uma função (DrawingDump, config) -> [Finding].

Regras se registram pelo decorator ``@rule``; a configuração da Gromar vem de
YAML versionado (``gromar.yaml``), não de if's no código.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from swmcp.domain.drawing import DrawingDump
from swmcp.domain.findings import Finding, Report

log = logging.getLogger(__name__)

RuleFn = Callable[[DrawingDump, dict[str, Any]], list[Finding]]

_RULES: dict[str, RuleFn] = {}


def rule(rule_id: str) -> Callable[[RuleFn], RuleFn]:
    """Registra uma regra de revisão. O id aparece nos achados e no relatório."""

    def deco(fn: RuleFn) -> RuleFn:
        if rule_id in _RULES:
            raise ValueError(f"regra duplicada: {rule_id}")
        _RULES[rule_id] = fn
        return fn

    return deco


def registered_rules() -> list[str]:
    _ensure_rules_loaded()
    return sorted(_RULES)


def load_config(ruleset: str) -> dict[str, Any]:
    path = Path(__file__).parent / f"{ruleset}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"ruleset desconhecido: {ruleset!r} (esperado {path})")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def review(dump: DrawingDump, ruleset: str = "gromar") -> Report:
    """Roda todas as regras registradas sobre o dump e monta o relatório."""
    _ensure_rules_loaded()
    config = load_config(ruleset)
    findings: list[Finding] = []
    for rule_id, fn in sorted(_RULES.items()):
        result = fn(dump, config)
        log.debug("regra %s: %d achado(s)", rule_id, len(result))
        findings.extend(result)
    return Report(
        drawing_path=dump.path,
        ruleset=ruleset,
        rules_run=sorted(_RULES),
        findings=findings,
    )


def _ensure_rules_loaded() -> None:
    # importa o pacote de regras uma vez; o decorator faz o resto
    from swmcp.review import rules  # noqa: F401
