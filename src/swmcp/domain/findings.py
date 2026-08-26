"""Achados de revisão (RF-05): Finding, Severity, Report."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class Severity(str, Enum):
    ERROR = "error"  # bloqueia liberação do desenho
    WARNING = "warning"  # merece olhar humano
    INFO = "info"  # observação


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule: str  # id da regra que disparou
    severity: Severity
    message: str  # em pt-BR, direto ao ponto
    where: str  # "sheet:Folha1", "view:Vista de desenho17", "dim:RD5"
    data: dict[str, str | float | int | bool | None] = {}


class Report(BaseModel):
    model_config = ConfigDict(frozen=True)

    drawing_path: str
    ruleset: str
    rules_run: list[str]
    findings: list[Finding]

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)
