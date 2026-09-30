"""Canal U1, recotagem limpa, chanfro movido, volume do perfil, arco curto,
profundidade de furo, troca por canal e filete em arestas — ao vivo.

Peça descartável fechada sem salvar: um anel torneado Z = eixo (esboço no
Plano superior, x = raio, y = -z), com furo Ø40 de 30 e degrau para Ø30 —
o mesmo arranjo do 3-50200-92000 onde o U1 foi feito à mão.
"""

import math

import pytest

from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import SwSession
from swmcp.com.wrappers import channels as ch
from swmcp.com.wrappers import holes as h
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o
from swmcp.com.wrappers import profile_edit as pe
from swmcp.com.wrappers import sketch_edit as se
from swmcp.com.wrappers import validate as v

pytestmark = pytest.mark.integration

PERFIL = [(20, 0), (60, 0), (60, -50), (15, -50), (15, -30), (20, -30)]


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


@pytest.fixture
def anel(session):
    session.run(lambda app: o.new_document(app, "part"))
    titulo = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    nome = session.run(lambda app: m.insert_sketch(app, "Plano superior"))
    session.run(lambda app: m.sketch_polyline(app, [list(p) for p in PERFIL], close=True))
    session.run(lambda app: m.sketch_line(app, 0, 10, 0, -60, centerline=True))
    session.run(lambda app: pe.sketch_redefine(app))   # como a tool revolve faz com eixo vertical
    session.run(lambda app: m.revolve(app, 360.0))
    yield {"title": titulo, "sketch": nome}
    session.run(lambda app: com_call(app, "CloseDoc", titulo))


def test_u1_volume_bate_com_o_perfil_e_recotagem_deixa_preto(session, anel):
    antes = session.run(lambda app: pe.profile_volume(app, anel["sketch"]))
    assert antes["profile_volume_mm3"] == pytest.approx(antes["body_volume_mm3"], rel=1e-4)
    session.run(lambda app: m.edit_sketch(app, anel["sketch"]))
    g = session.run(lambda app: pe.sketch_relief_groove(app, [20, -30], 0.4, 4.0, 1.6))
    assert g["points_mm"]["wall"] == pytest.approx([20.0, -26.0])
    session.run(m.exit_sketch)
    session.run(lambda app: m.rebuild(app))
    depois = session.run(lambda app: pe.profile_volume(app, anel["sketch"]))
    assert depois["major_arcs"] == []
    d_perfil = depois["profile_volume_mm3"] - antes["profile_volume_mm3"]
    d_corpo = depois["body_volume_mm3"] - antes["body_volume_mm3"]
    assert d_corpo == pytest.approx(d_perfil, abs=1.0)
    assert d_perfil < 0     # partindo do canto vivo, o canal tira material
    red = session.run(lambda app: pe.sketch_redefine(app, anel["sketch"]))
    assert red["fully_defined"], red
    final = session.run(lambda app: pe.profile_volume(app, anel["sketch"]))
    assert final["body_volume_mm3"] == pytest.approx(depois["body_volume_mm3"], abs=0.01)
    val = session.run(lambda app: v.validate_model(app))
    assert val["ok"], val


def test_chanfro_muda_de_canto_com_as_pontas_pedidas(session, anel):
    session.run(lambda app: m.edit_sketch(app, anel["sketch"]))
    session.run(lambda app: se.sketch_corner_chamfer(app, [60, 0], 2.0))
    r = 2.5 * math.tan(math.radians(20))
    res = session.run(lambda app: pe.move_sketch_chamfer(
        app, [58, 0], [60, -2], [60, -50], [60, -47.5], [60 - r, -50]))
    assert res["removed"]["corner_mm"] == pytest.approx([60, 0])
    pontos = {tuple(round(x, 3) for x in res["chamfer"][k]) for k in ("chamfer_from_mm", "chamfer_to_mm")}
    assert pontos == {(60.0, -47.5), (round(60 - r, 3), -50.0)}
    session.run(m.exit_sketch)
    session.run(lambda app: pe.sketch_redefine(app, anel["sketch"]))
    val = session.run(lambda app: v.validate_model(app))
    assert val["ok"], val


def test_arco_sai_sempre_curto(session, anel):
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    # o quarto de volta de (10,0) a (0,10): nos dois sentidos pedidos sai o curto
    for sentido in (1, -1):
        r = session.run(lambda app: m.sketch_arc_center(app, 0, 0, 10, 0, 0, 10, sentido))
        assert r["length_mm"] == pytest.approx(math.pi * 5, abs=1e-3)
    session.run(m.exit_sketch)


def test_furo_profundidade_troca_por_canal_e_filete(session, anel):
    caixa = session.run(lambda app: h.measure_bodies(app))[0]["box_mm"]
    topo = caixa[2] if abs(caixa[2]) < abs(caixa[5]) else caixa[5]     # face do furo Ø40 (z≈0)
    session.run(lambda app: h.hole_wizard(app, 40, 0, topo, 10, diameter_mm=6,
                                          model_positions_mm=[[40, 0, topo]]))
    furo = session.run(lambda app: com_call(ch._last_feature(app), "Name"))
    r = session.run(lambda app: ch.set_hole_depth(app, furo, 12))
    assert r["depth_mm"] == pytest.approx(12) and r["previous_depth_mm"] == pytest.approx(10)
    sinal = 1 if topo <= caixa[5] - 1 else -1
    t = session.run(lambda app: ch.replace_hole_with_channel(
        app, furo, [40, 0, topo], 6.0, "Canal Ø6 inclinado", length_mm=12,
        direction=[math.sin(math.radians(10)), 0, sinal * math.cos(math.radians(10))]))
    assert t["replaced"] == furo and t["removed_mm3"] > 0
    nomes = session.run(lambda app: [c["feature"] for c in v.dump_holes(app)])
    assert furo not in nomes
    arestas = session.run(lambda app: h.list_circular_edges(app, 119.9, 120.1))
    f = session.run(lambda app: ch.fillet_circular_edges(
        app, [[*a["center_mm"], a["diameter_mm"]] for a in arestas[:1]], 1.0, "R1 externo"))
    assert f["feature"] == "R1 externo" and f["volume_change_mm3"] < 0
    val = session.run(lambda app: v.validate_model(app))
    assert val["ok"], val
