"""DTOs do domínio validam os dumps reais da Gromar (RNF-06)."""

import json
from pathlib import Path

import pytest

from swmcp.domain.drawing import DrawingDump
from swmcp.domain.model import ModelProperties

# Os dumps são de peças de clientes e ficam só na máquina da Gromar
# (tests/fixtures está no .gitignore); sem eles estes testes são pulados.
FIXTURES = Path(__file__).parents[1] / "fixtures"
DRAWING_FIXTURES = sorted(p for p in FIXTURES.glob("*.json") if not p.stem.endswith("_model"))


@pytest.mark.parametrize("path", DRAWING_FIXTURES, ids=lambda p: p.stem)
def test_dump_real_valida_no_schema(path):
    dump = DrawingDump.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert dump.sheets, "desenho sem folha"
    assert dump.title
    # toda cota tem unidade conhecida e tolerância estruturada
    for sheet in dump.sheets:
        for view in sheet.views:
            for dim in view.dimensions:
                assert dim.unit in ("mm", "deg")
                assert dim.tolerance.type


def test_dump_e_imutavel():
    if not DRAWING_FIXTURES:
        pytest.skip("sem dumps reais em tests/fixtures")
    dump = DrawingDump.model_validate(
        json.loads(DRAWING_FIXTURES[0].read_text(encoding="utf-8"))
    )
    with pytest.raises(Exception):
        dump.title = "outro"


def test_model_properties_fixture():
    path = FIXTURES / "bocal_krones_model.json"
    if not path.exists():
        pytest.skip("sem dumps reais em tests/fixtures")
    props = ModelProperties.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert props.mass_kg is not None and props.mass_kg > 0
    assert props.bounding_box is not None
    assert props.material is None  # peça real sem material atribuído
