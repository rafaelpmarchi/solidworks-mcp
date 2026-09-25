"""Chapa metálica, furo de folga, esboço amarrado e montagem girada, ao vivo.

Refaz em miniatura a prateleira 1900x1000x400 (cantoneira 40x40 furada em
pares + bandeja em U) só com as tools do MCP. Salva as peças numa pasta
temporária do pytest (a montagem precisa de arquivo) e fecha tudo no fim.
"""

import pytest

from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import SwSession, cast_to
from swmcp.com.wrappers import assembly as a
from swmcp.com.wrappers import holes as h
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o
from swmcp.com.wrappers import sheetmetal as sm

pytestmark = pytest.mark.integration

ESP = 2.65
ALTURA = 400.0          # coluna curta: 4 pares de furos a cada 100
PARES = [50.0, 150.0, 250.0, 350.0]
LARGURA, PROF = 300.0, 200.0
FOLGA_BANDEJA = 6.0


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


def _title(app):
    return com_call(cast_to(com_get(app, "ActiveDoc"), "IModelDoc2"), "GetTitle")


def _save(app, path):
    model = cast_to(com_get(app, "ActiveDoc"), "IModelDoc2")
    ok = com_call(cast_to(com_get(model, "Extension"), "IModelDocExtension"),
                  "SaveAs3", str(path), 0, 1, None, None, 0, 0)
    assert ok, f"não salvou {path}"


def _holes_xy(app, diameter):
    """Centros (x, y) dos furos Ø diameter da peça ativa, em mm."""
    part = cast_to(com_get(app, "ActiveDoc"), "IPartDoc")
    saida = set()
    for rb in com_call(part, "GetBodies2", 0, True):
        for rf in com_call(cast_to(rb, "IBody2"), "GetFaces"):
            s = cast_to(com_call(cast_to(rf, "IFace2"), "GetSurface"), "ISurface")
            if com_call(s, "IsCylinder") and abs(com_call(s, "CylinderParams")[6] * 2000 - diameter) < 0.01:
                p = com_call(s, "CylinderParams")
                saida.add((round(p[0] * 1000, 2), round(p[1] * 1000, 2)))
    return saida


def test_prateleira_em_miniatura(session, tmp_path):
    abertos = []
    try:
        # ---------------- coluna: cantoneira 40x40 pela face externa
        def coluna(app):
            o.new_document(app, "part")
            abertos.append(_title(app))
            m.insert_sketch(app, "Plano superior")
            m.sketch_polyline(app, [[40, 0], [0, 0], [0, -40]])
            flange = sm.sheet_metal_base_flange(app, ESP, ALTURA, thicken_reverse=True)
            furo = h.hole_wizard(app, 22.5, PARES[0], 0, 0, size="M6", standard="ISO",
                                 hole_type="clearance", fit="close", through_all=True,
                                 model_positions_mm=[[22.5, y - 7.5, 0] for y in PARES]
                                 + [[22.5, y + 7.5, 0] for y in PARES])
            _save(app, tmp_path / "coluna.SLDPRT")
            abertos[-1] = _title(app)   # salvar muda o título (Peça9 → coluna.SLDPRT)
            return flange, furo, _holes_xy(app, 6.4)
        flange, furo, furos_col = session.run(coluna)
        assert flange["sketch_definition"]["fully_defined"]
        assert flange["bodies"][0]["box_mm"] == [0, 0, 0, 40, ALTURA, 40]
        assert furo["drill_diameter_mm"] == 6.4 and furo["holes"] == 8
        assert furo["sketch_definition"]["fully_defined"]
        esperado = {(22.5, y + d) for y in PARES for d in (-7.5, 7.5)}
        assert furos_col == esperado

        # ---------------- bandeja: U aberto, abas de 50 para baixo
        def bandeja(app):
            o.new_document(app, "part")
            abertos.append(_title(app))
            m.insert_sketch(app, "Plano direito")
            fundo = PROF - 2 * ESP - 1.0
            m.sketch_polyline(app, [[0, -50], [0, 0], [fundo, 0], [fundo, -50]])
            comp = LARGURA - 2 * FOLGA_BANDEJA
            flange = sm.sheet_metal_base_flange(app, ESP, comp)
            x = 22.5 - FOLGA_BANDEJA
            furo = h.hole_wizard(app, x, -25, 0, 0, size="M6", standard="ISO",
                                 hole_type="clearance", fit="close", through_all=True,
                                 model_positions_mm=[[x, -17.5, 0], [x, -32.5, 0],
                                                     [comp - x, -17.5, 0], [comp - x, -32.5, 0]])
            _save(app, tmp_path / "bandeja.SLDPRT")
            abertos[-1] = _title(app)
            return flange, furo
        flange_b, furo_b = session.run(bandeja)
        assert flange_b["sketch_definition"]["fully_defined"]
        assert flange_b["bodies"][0]["box_mm"][3] == pytest.approx(LARGURA - 2 * FOLGA_BANDEJA)
        assert furo_b["sketch_definition"]["fully_defined"]
        cotas = sorted(d["value_mm"] for d in furo_b["sketch_definition"]["dimensions"])
        assert cotas == sorted([16.5, LARGURA - 2 * FOLGA_BANDEJA - 2 * 16.5, 17.5, 15.0])

        # ---------------- montagem com colunas giradas e invertidas
        def montagem(app):
            o.new_document(app, "assembly")
            abertos.append(_title(app))
            col = str(tmp_path / "coluna.SLDPRT")
            ban = str(tmp_path / "bandeja.SLDPRT")
            caixas = [
                a.insert_component(app, col, 0, 0, -PROF, [0, 0, 0], fixed=True),
                a.insert_component(app, col, LARGURA, 0, 0, [0, 180, 0], fixed=True),
                a.insert_component(app, col, 0, ALTURA, 0, [180, 0, 0], fixed=True),
                a.insert_component(app, col, LARGURA, ALTURA, -PROF, [0, 0, 180], fixed=True),
                a.insert_component(app, ban, FOLGA_BANDEJA, PARES[1] + 25, -(ESP + 0.5),
                                   [0, 0, 0], fixed=True),
            ]
            return caixas, a.check_interference(app)
        caixas, interferencias = session.run(montagem)
        assert caixas[1]["placement"]["box_mm"] == pytest.approx([LARGURA - 40, 0, -40, LARGURA, ALTURA, 0])
        assert caixas[2]["placement"]["box_mm"] == pytest.approx([0, 0, -40, 40, ALTURA, 0])
        assert interferencias == []
    finally:
        for titulo in reversed(abertos):
            session.run(lambda app, t=titulo: com_call(app, "CloseDoc", t))
