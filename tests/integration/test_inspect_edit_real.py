"""Cotas/tolerâncias, inspeção, edição de canto e reparo ao vivo (exige SolidWorks).

Cria uma peça descartável (eixo escalonado) e fecha sem salvar.
"""

import pytest

from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import SwSession, cast_to
from swmcp.com.wrappers import dimensioning as dm
from swmcp.com.wrappers import dimensions as d
from swmcp.com.wrappers import holes as h
from swmcp.com.wrappers import inspect as i
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o
from swmcp.com.wrappers import repair as r
from swmcp.com.wrappers import sketch_edit as se

pytestmark = pytest.mark.integration

# meio-perfil (z, raio): Ø40 até z=40, depois Ø60 até z=100 — canto interno em (40, 20)
PERFIL = [(0, 0), (0, 20), (40, 20), (40, 30), (100, 30), (100, 0)]


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


@pytest.fixture
def eixo(session):
    session.run(lambda app: o.new_document(app, "part"))
    title = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    sketch = session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    session.run(lambda app: m.sketch_polyline(app, [[z, rr] for z, rr in PERFIL], close_with_centerline=True))
    cotagem = session.run(dm.fully_dimension_profile)   # como a tool revolve faz: esboço preto
    assert cotagem["fully_defined"], cotagem
    revolve = session.run(lambda app: m.revolve(app, 360.0))
    yield {"sketch": sketch, "revolve": revolve}
    session.run(lambda app: com_call(app, "CloseDoc", title))


def _edges(session, diameter):
    return [e for e in session.run(h.list_circular_edges) if abs(e["diameter_mm"] - diameter) < 0.01]


def test_list_dimensions_traz_nome_completo_valor_e_tolerancia(session, eixo):
    cotas = session.run(lambda app: d.list_dimensions(app, eixo["sketch"]))
    nomes = {c["name"] for c in cotas}
    assert all("@" in n for n in nomes)
    diametros = [c for c in cotas if c["diametric"]]
    assert {round(c["value"]) for c in diametros} >= {40, 60}
    assert all(c["tolerance"] == {"type": "none"} for c in cotas)


def test_ajuste_iso_bilateral_e_simetrica(session, eixo):
    cotas = session.run(lambda app: d.list_dimensions(app, eixo["sketch"]))
    d60 = next(c for c in cotas if c["diametric"] and round(c["value"]) == 60)
    d40 = next(c for c in cotas if c["diametric"] and round(c["value"]) == 40)
    comprimento = next(c for c in cotas if not c["diametric"] and round(c["value"]) == 100)

    eixo_h6 = session.run(lambda app: d.set_dimension_tolerance(app, d60["name"], "fit", fit="h6"))
    assert eixo_h6["tolerance"]["fit"] == "h6"
    assert eixo_h6["tolerance"]["upper_mm"] == 0
    assert eixo_h6["tolerance"]["lower_mm"] == pytest.approx(-0.019, abs=1e-4)

    # letra de furo num eixo: o SolidWorks aceita e calcula H7 do Ø40
    furo_h7 = session.run(lambda app: d.set_dimension_tolerance(app, d40["name"], "fit", fit="H7"))
    assert furo_h7["tolerance"]["upper_mm"] == pytest.approx(0.025, abs=1e-4)

    bil = session.run(lambda app: d.set_dimension_tolerance(
        app, comprimento["name"], "bilateral", upper_mm=0.1, lower_mm=-0.05))
    assert (bil["tolerance"]["lower_mm"], bil["tolerance"]["upper_mm"]) == pytest.approx((-0.05, 0.1))

    sim = session.run(lambda app: d.set_dimension_tolerance(app, comprimento["name"], "symmetric", upper_mm=0.2))
    assert (sim["tolerance"]["lower_mm"], sim["tolerance"]["upper_mm"]) == pytest.approx((-0.2, 0.2))

    with pytest.raises(ComCallError, match="fit"):
        session.run(lambda app: d.set_dimension_tolerance(app, d60["name"], "fit"))
    with pytest.raises(ComCallError, match="não encontrada"):
        session.run(lambda app: d.set_dimension_tolerance(app, "D99@Nada", "bilateral", upper_mm=0.1))


def test_inspecao_faces_status_e_erros(session, eixo):
    faces = session.run(lambda app: i.list_faces(app, "cylinder"))
    assert {round(f["diameter_mm"]) for f in faces} == {40, 60}
    planos = session.run(lambda app: i.list_faces(app, "plane"))
    assert len(planos) == 3   # duas faces de extremidade + o ressalto

    st = session.run(lambda app: i.sketch_status(app, eixo["sketch"]))
    assert st["fully_defined"] and st["under_defined_segments"] == []

    erros = session.run(lambda app: i.check_rebuild_errors(app))
    assert erros["clean"] and erros["problems"] == []


def test_alivio_din509_no_canto_mantem_cotas_e_fica_definido(session, eixo):
    antes = session.run(lambda app: d.list_dimensions(app, eixo["sketch"]))
    session.run(lambda app: m.edit_sketch(app, eixo["sketch"]))
    try:
        res = session.run(lambda app: se.sketch_undercut_din509(app, [40, 20], 0.6, 0.2))
    finally:
        session.run(m.exit_sketch)
    assert res["width_mm"] == 2.0
    assert res["material_side"] == [0.0, -1.0]          # eixo: material para dentro
    assert res["points_mm"]["cylinder"] == [38.0, 20.0]
    assert res["points_mm"]["floor_start"] == pytest.approx([39.4, 19.8])
    assert res["lines"] == {"cylinder": "split", "shoulder": "moved"}
    assert res["lost_dimensions"] == []
    assert res["fully_defined"], res
    assert {c["kind"] for c in res["dimensions"]} == {"R", "t", "f", "angle"}

    depois = session.run(lambda app: d.list_dimensions(app, eixo["sketch"]))
    assert {c["name"] for c in antes} <= {c["name"] for c in depois}
    assert _edges(session, 39.6), "fundo do alívio (Ø39,6) não apareceu no corpo"
    assert any(abs(e["center_mm"][0] - 38.0) < 0.01 for e in _edges(session, 40.0)), "cilindro Ø40 devia terminar em z=38"
    assert session.run(lambda app: i.check_rebuild_errors(app))["clean"]


def test_chanfro_e_filete_de_canto_no_esboco(session, eixo):
    session.run(lambda app: m.edit_sketch(app, eixo["sketch"]))
    try:
        ch = session.run(lambda app: se.sketch_corner_chamfer(app, [100, 30], 1.0))
        fi = session.run(lambda app: se.sketch_corner_fillet(app, [0, 20], 2.0))
    finally:
        session.run(m.exit_sketch)
    assert sorted([ch["chamfer_from_mm"], ch["chamfer_to_mm"]]) == [[99.0, 30.0], [100.0, 29.0]]
    assert fi["center_mm"] == pytest.approx([2.0, 18.0])
    assert _edges(session, 58.0), "chanfro 1×45° devia deixar aresta Ø58 na ponta"
    assert session.run(lambda app: i.sketch_status(app, eixo["sketch"]))["fully_defined"]


def test_religa_eixo_de_padrao_circular_e_renomeia_em_lote(session, eixo):
    furo = session.run(lambda app: h.hole_wizard(
        app, 100, 20, 0, depth_mm=10, diameter_mm=5, hole_type="simple",
        model_positions_mm=[[100, 20, 0]], add_cosmetic_thread=False))
    def seleciona(app):
        m.clear_selection(app)
        m.select_entity(app, furo["feature"], "BODYFEATURE", mark=4)
        h.select_face_at(app, 60, 30, 0, append=True, mark=1)   # face Ø60 = eixo

    session.run(seleciona)
    padrao = session.run(lambda app: m.circular_pattern(app, 4))
    assert session.run(lambda app: i.check_rebuild_errors(app))["clean"]

    religado = session.run(lambda app: r.set_circular_pattern_axis(app, padrao, [20, 0, 20]))
    assert religado["ok"]
    assert len(_edges(session, 5.0)) >= 4

    ren = session.run(lambda app: r.rename_features(app, {padrao: "Padrão 4x furos", furo["feature"]: "Furo Ø5"}))
    assert ren["count"] == 2
    with pytest.raises(ComCallError, match="já renomeadas"):
        session.run(lambda app: r.rename_features(app, {"Padrão 4x furos": "P", "NãoExiste": "X"}))
