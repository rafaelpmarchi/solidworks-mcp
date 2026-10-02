"""Arco que fecha contorno de polyline e padrão circular conferido — ao vivo.

Peça descartável fechada sem salvar: o disco da roda de polo 10006900433
(Ø225 × 20, furo Ø60, eixo X), onde o arco deixou uma ponta solta e o padrão
de 30 vãos saiu com ~3 instâncias sem erro.
"""

import math

import pytest

from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import SwSession
from swmcp.com.wrappers import inspect as i
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o
from swmcp.tools.create import _define_active

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


@pytest.fixture
def disco(session):
    session.run(lambda app: o.new_document(app, "part"))
    titulo = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    session.run(lambda app: m.sketch_polyline(app, [[0, 30], [0, 112.5], [20, 112.5], [20, 30]],
                                              close=True))
    session.run(lambda app: m.sketch_line(app, 0, 0, 30, 0, centerline=True))
    session.run(lambda app: m.revolve(app, 360.0))
    yield titulo
    session.run(lambda app: com_call(app, "CloseDoc", titulo))


def _vao_com_fundo_em_arco(session) -> dict:
    """Vão de faces paralelas com fundo em arco R104,5, no Plano direito (x=0)."""
    y_fundo = math.sqrt(104.5 ** 2 - 5.9 ** 2)
    session.run(lambda app: m.insert_sketch(app, "Plano direito"))
    session.run(lambda app: m.sketch_polyline(
        app, [[5.9, y_fundo], [5.9, 120], [-5.9, 120], [-5.9, y_fundo]]))
    return session.run(lambda app: m.sketch_arc_center(
        app, 0, 0, -5.9, y_fundo, 5.9, y_fundo, -1))


def test_arco_une_as_duas_pontas_e_o_corte_sai(session, disco):
    arco = _vao_com_fundo_em_arco(session)
    assert arco["length_mm"] < 20
    pontos = session.run(lambda app: len(com_call(
        com_get(com_get(com_get(app, "ActiveDoc"), "SketchManager"), "ActiveSketch"),
        "GetSketchPoints2")))
    assert pontos == 5, "4 vértices + centro do arco: ponta duplicada não foi unida"
    corte = session.run(lambda app: m.extrude(app, 20, cut=True, through_all=True,
                                              reverse_direction=True))
    assert corte


def test_padrao_circular_por_aresta_confere_30_instancias(session, disco):
    _vao_com_fundo_em_arco(session)
    corte = session.run(lambda app: m.extrude(app, 20, cut=True, through_all=True,
                                              reverse_direction=True))
    r = session.run(lambda app: m.circular_pattern(
        app, 30, features=[corte], axis_edge_center_mm=[0, 0, 0], axis_edge_diameter_mm=60))
    assert r["ok"], r
    assert r["instances_measured"] == pytest.approx(30, abs=0.05)
    assert r["seed_volume_effect_mm3"] < 0


def test_padrao_circular_acusa_instancias_faltando(session, disco):
    # 30 cópias em 20°: as instâncias se sobrepõem e o volume não fecha 30 —
    # é o tipo de resultado que antes passava calado
    _vao_com_fundo_em_arco(session)
    corte = session.run(lambda app: m.extrude(app, 20, cut=True, through_all=True,
                                              reverse_direction=True))
    r = session.run(lambda app: m.circular_pattern(
        app, 30, angle_deg=20, equal_spacing=True, features=[corte],
        axis_edge_center_mm=[0, 0, 0], axis_edge_diameter_mm=60))
    assert r["ok"] is False
    assert "warning" in r


def test_revolve_deixa_perfil_com_chanfro_preto_de_primeira(session):
    # perfil da roda com chanfro no furo e linha de centro começando ANTES da
    # origem: a cotagem de perfil devolvia sub-definido e a revolve aceitava
    session.run(lambda app: o.new_document(app, "part"))
    titulo = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    try:
        nome = session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
        session.run(lambda app: m.sketch_polyline(
            app, [[0, 30], [0, 112.5], [20, 112.5], [20, 50], [35, 50], [35, 32.5], [32.5, 30]],
            close=True))
        session.run(lambda app: m.sketch_line(app, -5, 0, 40, 0, centerline=True))
        definicao = session.run(lambda app: _define_active(app, revolution=True))
        assert definicao["fully_defined"], definicao
        session.run(lambda app: m.revolve(app, 360.0))
        assert session.run(lambda app: i.sketch_status(app, nome))["fully_defined"]
    finally:
        session.run(lambda app: com_call(app, "CloseDoc", titulo))
