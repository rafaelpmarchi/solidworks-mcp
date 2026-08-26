"""Regras de revisão sobre fixtures reais e sintéticas — positivo E negativo."""

import json
from pathlib import Path

import pytest

from swmcp.domain.drawing import (
    Annotation,
    Dimension,
    DrawingDump,
    Note,
    Sheet,
    Tolerance,
    View,
)
from swmcp.review import engine

FIXTURES = Path(__file__).parents[1] / "fixtures"


def load(name: str) -> DrawingDump:
    return DrawingDump.model_validate(
        json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    )


def rules_fired(report, rule_id):
    return [f for f in report.findings if f.rule == rule_id]


# ------------------------------------------------------------- fixtures reais


def test_fresa_sem_material_declarado_dispara():
    report = engine.review(load("fresa_tag247"))
    achados = rules_fired(report, "title_block.material_declared")
    assert len(achados) == 1  # achado real: campo MATERIAL: vazio no desenho


def test_bucha_com_material_nao_dispara():
    # a bucha declara "MATERIAL G17CrMoV510" numa nota — não deve acusar
    report = engine.review(load("bucha_labirinto"))
    assert rules_fired(report, "title_block.material_declared") == []


def test_fresa_legenda_completa_nos_rotulos():
    report = engine.review(load("fresa_tag247"))
    assert rules_fired(report, "title_block.required_labels") == []


def test_fresa_escala_coerente():
    report = engine.review(load("fresa_tag247"))
    assert rules_fired(report, "title_block.scale_matches_sheet") == []


def test_relatorio_lista_regras_executadas():
    report = engine.review(load("bocal_krones"))
    assert "title_block.material_declared" in report.rules_run
    assert len(report.rules_run) >= 6


# ------------------------------------------------------- fixtures sintéticas


def _dump(views=(), notes=(), scale="1:1", unrecognized=()):
    return DrawingDump(
        path="C:/teste.slddrw",
        title="teste",
        sheets=[Sheet(name="Folha1", scale=scale, views=list(views), notes=list(notes))],
        unrecognized=list(unrecognized),
    )


LEGENDA_OK = [
    Note(name="n1", text="MATERIAL: AÇO SAE 4140"),
    Note(name="n2", text="TÍTULO: PEÇA"),
    Note(name="n3", text="DES. Nº 123"),
    Note(name="n4", text="REVISÃO 0"),
    Note(name="n5", text="ESCALA:1:1"),
]


def test_rotulo_faltando_dispara_um_por_campo():
    report = engine.review(_dump(notes=LEGENDA_OK[:2]))  # sem DES. Nº, REVISÃO, ESCALA
    achados = rules_fired(report, "title_block.required_labels")
    assert {f.data["label"] for f in achados} == {"DES. Nº", "REVISÃO", "ESCALA:"}


def test_escala_divergente_dispara():
    report = engine.review(_dump(notes=LEGENDA_OK, scale="1:2"))
    achados = rules_fired(report, "title_block.scale_matches_sheet")
    assert len(achados) == 1
    assert achados[0].data["declared"] == "1:1"


def test_cota_inspecao_sem_tolerancia_dispara():
    dim_ok = Dimension(
        name="D1", full_name="D1@V1@t", value=10, unit="mm", text="",
        tolerance=Tolerance(type="BILATERAL", max_variation=0.1, min_variation=-0.1),
        is_inspection=True, view="V1",
    )
    dim_ruim = Dimension(
        name="D2", full_name="D2@V1@t", value=20, unit="mm", text="",
        tolerance=Tolerance(type="NONE"), is_inspection=True, view="V1",
    )
    dim_livre = Dimension(  # sem inspeção: tolerância NONE é aceitável
        name="D3", full_name="D3@V1@t", value=30, unit="mm", text="",
        tolerance=Tolerance(type="NONE"), is_inspection=False, view="V1",
    )
    view = View(name="V1", type="named", dimensions=[dim_ok, dim_ruim, dim_livre])
    report = engine.review(_dump(views=[view], notes=LEGENDA_OK))
    achados = rules_fired(report, "dimensions.inspection_requires_tolerance")
    assert [f.data["value"] for f in achados] == [20]


def test_gtol_sem_datum_dispara_e_com_datum_nao():
    v_ruim = View(name="V1", type="named", annotations=[Annotation(kind="gtol", text="pos")])
    v_ok = View(
        name="V2", type="named",
        annotations=[Annotation(kind="gtol", text="pos"), Annotation(kind="datum_tag", text="A")],
    )
    report = engine.review(_dump(views=[v_ruim, v_ok], notes=LEGENDA_OK))
    achados = rules_fired(report, "gtol.requires_datum_in_view")
    assert [f.where for f in achados] == ["view:V1"]


def test_solda_sem_texto_dispara():
    view = View(
        name="V1", type="named",
        annotations=[Annotation(kind="weld_symbol", text=""), Annotation(kind="weld_symbol", text="CJP 6mm")],
    )
    report = engine.review(_dump(views=[view], notes=LEGENDA_OK))
    assert len(rules_fired(report, "weld.requires_text")) == 1


def test_unrecognized_vira_info():
    from swmcp.domain.drawing import Unrecognized

    report = engine.review(_dump(notes=LEGENDA_OK, unrecognized=[Unrecognized(where="sheet:Folha1", raw_type=99)]))
    achados = rules_fired(report, "dump.unrecognized_items")
    assert len(achados) == 1
    assert achados[0].severity.value == "info"


def test_ruleset_inexistente_falha_alto():
    with pytest.raises(FileNotFoundError, match="ruleset desconhecido"):
        engine.review(_dump(notes=LEGENDA_OK), ruleset="nao_existe")
