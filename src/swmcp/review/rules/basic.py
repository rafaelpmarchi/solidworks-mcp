"""Primeiras regras Gromar (Fase 2). Cada função: (dump, config) -> [Finding]."""

from __future__ import annotations

import re
from typing import Any

from swmcp.domain.drawing import DrawingDump, Sheet
from swmcp.domain.findings import Finding, Severity
from swmcp.review.engine import rule


def _sheet_note_texts(sheet: Sheet) -> list[str]:
    return [n.text for n in sheet.notes]


@rule("title_block.required_labels")
def required_labels(dump: DrawingDump, config: dict[str, Any]) -> list[Finding]:
    """Rótulos obrigatórios da legenda precisam existir na folha."""
    required = config.get("title_block", {}).get("required_labels", [])
    findings: list[Finding] = []
    for sheet in dump.sheets:
        texts = " \n".join(_sheet_note_texts(sheet)).upper()
        for label in required:
            if label.upper() not in texts:
                findings.append(
                    Finding(
                        rule="title_block.required_labels",
                        severity=Severity.ERROR,
                        message=f"legenda sem o campo obrigatório {label!r}",
                        where=f"sheet:{sheet.name}",
                        data={"label": label},
                    )
                )
    return findings


@rule("title_block.material_declared")
def material_declared(dump: DrawingDump, config: dict[str, Any]) -> list[Finding]:
    """Algum texto da legenda precisa declarar o material da peça."""
    patterns = config.get("material", {}).get("patterns", [])
    if not patterns:
        return []
    regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
    findings: list[Finding] = []
    for sheet in dump.sheets:
        texts = _sheet_note_texts(sheet)
        if not any(rx.search(t) for t in texts for rx in regexes):
            findings.append(
                Finding(
                    rule="title_block.material_declared",
                    severity=Severity.ERROR,
                    message="nenhum material identificável declarado na legenda "
                    "(campo 'MATERIAL:' vazio ou ilegível para as regras atuais)",
                    where=f"sheet:{sheet.name}",
                    data={},
                )
            )
    return findings


@rule("title_block.scale_matches_sheet")
def scale_matches_sheet(dump: DrawingDump, config: dict[str, Any]) -> list[Finding]:
    """Escala declarada na legenda (ex.: 'ESCALA:1:2') deve bater com a da folha."""
    findings: list[Finding] = []
    rx = re.compile(r"ESCALA\s*:?\s*(\d+(?:[.,]\d+)?)\s*:\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
    for sheet in dump.sheets:
        if not sheet.scale:
            continue
        declared = None
        for text in _sheet_note_texts(sheet):
            m = rx.search(text)
            if m:
                declared = f"{m.group(1).replace(',', '.')}:{m.group(2).replace(',', '.')}"
                break
        if declared is None:
            continue  # ausência do rótulo é assunto de required_labels
        expected = sheet.scale.replace(",", ".")
        if _norm_scale(declared) != _norm_scale(expected):
            findings.append(
                Finding(
                    rule="title_block.scale_matches_sheet",
                    severity=Severity.ERROR,
                    message=f"escala da legenda ({declared}) difere da escala da folha ({sheet.scale})",
                    where=f"sheet:{sheet.name}",
                    data={"declared": declared, "sheet_scale": sheet.scale},
                )
            )
    return findings


def _norm_scale(scale: str) -> tuple[float, float] | None:
    try:
        a, b = scale.split(":")
        return float(a), float(b)
    except ValueError:
        return None


@rule("dimensions.inspection_requires_tolerance")
def inspection_requires_tolerance(dump: DrawingDump, config: dict[str, Any]) -> list[Finding]:
    """Cota marcada para inspeção sem tolerância explícita é erro."""
    if not config.get("dimensions", {}).get("inspection_requires_tolerance", True):
        return []
    findings: list[Finding] = []
    for sheet in dump.sheets:
        for view in sheet.views:
            for dim in view.dimensions:
                if dim.is_inspection and dim.tolerance.type == "NONE":
                    findings.append(
                        Finding(
                            rule="dimensions.inspection_requires_tolerance",
                            severity=Severity.ERROR,
                            message=f"cota de inspeção {dim.name} ({dim.value}{dim.unit}) sem tolerância",
                            where=f"dim:{dim.full_name}",
                            data={"value": dim.value, "unit": dim.unit},
                        )
                    )
    return findings


@rule("gtol.requires_datum_in_view")
def gtol_requires_datum(dump: DrawingDump, config: dict[str, Any]) -> list[Finding]:
    """GD&T numa vista sem nenhum datum na mesma vista merece verificação."""
    if not config.get("gtol", {}).get("require_datum_in_view", True):
        return []
    findings: list[Finding] = []
    for sheet in dump.sheets:
        for view in sheet.views:
            kinds = {a.kind for a in view.annotations}
            if "gtol" in kinds and "datum_tag" not in kinds:
                findings.append(
                    Finding(
                        rule="gtol.requires_datum_in_view",
                        severity=Severity.WARNING,
                        message=f"vista {view.name!r} tem GD&T mas nenhum datum na mesma vista",
                        where=f"view:{view.name}",
                        data={},
                    )
                )
    return findings


@rule("weld.requires_text")
def weld_requires_text(dump: DrawingDump, config: dict[str, Any]) -> list[Finding]:
    """Símbolo de solda sem descrição é nota de solda incompleta."""
    if not config.get("weld", {}).get("require_text", True):
        return []
    findings: list[Finding] = []
    for sheet in dump.sheets:
        for view in sheet.views:
            for ann in view.annotations:
                if ann.kind == "weld_symbol" and not ann.text.strip():
                    findings.append(
                        Finding(
                            rule="weld.requires_text",
                            severity=Severity.WARNING,
                            message=f"símbolo de solda sem descrição na vista {view.name!r}",
                            where=f"view:{view.name}",
                            data={},
                        )
                    )
    return findings


@rule("dump.unrecognized_items")
def unrecognized_items(dump: DrawingDump, config: dict[str, Any]) -> list[Finding]:
    """Itens não mapeados pela leitura: a revisão NÃO os viu (R4) — informar."""
    return [
        Finding(
            rule="dump.unrecognized_items",
            severity=Severity.INFO,
            message=f"item não interpretado pela leitura (tipo bruto {u.raw_type}) — "
            "a revisão não o avaliou",
            where=u.where,
            data={"raw_type": u.raw_type, "detail": u.detail},
        )
        for u in dump.unrecognized
    ]
