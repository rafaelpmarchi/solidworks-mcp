"""Perfil exato, furo do assistente e rosca ao vivo (exige SolidWorks).

Cria uma peça descartável e fecha sem salvar. Nunca toca em arquivo do usuário.
"""

import math

import pytest

from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import SwSession
from swmcp.com.wrappers import holes as h
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o

pytestmark = pytest.mark.integration

# Meio-perfil (z, raio) de um eixo escalonado com rebaixo de cota quebrada: é
# justamente esse 33,8 que os snaps do SolidWorks arredondavam para 35.
PERFIL = [(0, 0), (0, 20), (40, 20), (43, 16.9), (55, 16.9), (58, 20), (100, 20), (100, 0)]


def volume_revolucao_mm3(perfil):
    """Volume exato do sólido de revolução do perfil (troncos de cone)."""
    total = 0.0
    for (z1, r1), (z2, r2) in zip(perfil, perfil[1:]):
        total += math.pi / 3.0 * (r1 * r1 + r1 * r2 + r2 * r2) * (z2 - z1)
    return total


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


@pytest.fixture
def eixo(session):
    session.run(lambda app: o.new_document(app, "part"))
    title = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    perfil = [[z, r] for z, r in PERFIL]
    info = session.run(lambda app: m.sketch_polyline(app, perfil, close_with_centerline=True))
    session.run(lambda app: m.revolve(app, 360.0))
    yield info
    session.run(lambda app: com_call(app, "CloseDoc", title))


def test_perfil_sai_com_as_cotas_pedidas_e_contorno_fechado(session, eixo):
    assert eixo["closed_contours"] == 1, "perfil não fechou — revolve/extrude falhariam"
    assert eixo["segments"] == len(PERFIL)  # n-1 linhas + o fechamento pelo eixo

    medido = session.run(lambda app: h.measure_bodies(app))[0]
    assert medido["volume_mm3"] == pytest.approx(volume_revolucao_mm3(PERFIL), rel=1e-6)

    # o rebaixo saiu com Ø33,8 e não arredondado para 35
    rebaixo = [e for e in session.run(lambda app: h.list_circular_edges(app, 30, 40))
               if e["center_mm"][0] == 43.0]
    assert rebaixo and rebaixo[0]["diameter_mm"] == pytest.approx(33.8)


def test_furo_do_assistente_sai_no_tamanho_pedido_e_centrado(session, eixo):
    antes = session.run(lambda app: h.measure_bodies(app))[0]["volume_mm3"]
    furo = session.run(lambda app: h.hole_wizard(app, 0, 10, 0, 10.2, 25, "tap", 20))
    assert furo["position_mm"] == [0.0, 0.0]

    depois = session.run(lambda app: h.measure_bodies(app))[0]["volume_mm3"]
    esperado = math.pi * (10.2 / 2) ** 2 * 25
    assert antes - depois == pytest.approx(esperado, rel=1e-3), "furo saiu com outro tamanho"

    boca = [e for e in session.run(lambda app: h.list_circular_edges(app, 10, 11))
            if e["center_mm"] == [0.0, 0.0, 0.0]]
    assert boca, "furo não ficou centrado no eixo"

    rosca = session.run(lambda app: h.cosmetic_thread(app, [0, 0, 0], 10.2, 12, 20, "M12x1,75"))
    assert rosca["callout"] == "M12x1,75"


def test_corte_para_o_outro_lado_usa_reverse_e_nao_flip(session, eixo):
    """reverse_direction corta do outro lado; flip inverteria o lado do material."""
    volume = session.run(lambda app: h.measure_bodies(app))[0]["volume_mm3"]
    for reverse in (False, True):
        session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
        session.run(lambda app: m.sketch_rectangle(app, 40.0, 18.0, 60.0, 40.0))
        session.run(lambda app, r=reverse: m.extrude(app, 50.0, cut=True, through_all=True,
                                                     reverse_direction=r))
        agora = session.run(lambda app: h.measure_bodies(app))[0]["volume_mm3"]
        assert agora < volume, "o corte não removeu material"
        assert agora > volume * 0.9, "o corte comeu a peça — lado do material invertido"
        volume = agora


def test_aresta_inexistente_falha_dizendo_o_que_fazer(session, eixo):
    with pytest.raises(ComCallError, match="list_circular_edges"):
        session.run(lambda app: h.select_circular_edge(app, [0, 0, 0], 999.0))
