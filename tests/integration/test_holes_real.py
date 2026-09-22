"""Perfil exato, furo do assistente e rosca ao vivo (exige SolidWorks).

Cria uma peça descartável e fecha sem salvar. Nunca toca em arquivo do usuário.
"""

import math

import pytest

from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import SwSession
from swmcp.com.wrappers import hole_library as hl
from swmcp.com.wrappers import dimensioning as dm
from swmcp.com.wrappers import holes as h
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o
from swmcp.com.wrappers import turning as t

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
    furo = session.run(lambda app: h.hole_wizard(app, 0, 10, 0, 25, diameter_mm=10.2,
                                                 hole_type="tap", thread_depth_mm=20))
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


def test_furo_por_tamanho_da_biblioteca(session, eixo):
    """size='M12x1.75' tira o Ø da broca da base do SolidWorks, não de um chute."""
    tamanho = session.run(lambda app: hl.resolve_size(app, "M12x1.75", "Ansi Metric", "tap"))
    assert tamanho["drill_diameter_mm"] == pytest.approx(10.2)
    assert tamanho["pitch_mm"] == pytest.approx(1.75)

    antes = session.run(lambda app: h.measure_bodies(app))[0]["volume_mm3"]
    furo = session.run(lambda app: h.hole_wizard(app, 0, 10, 0, 25, size="M12x1.75",
                                                 standard="Ansi Metric", hole_type="tap",
                                                 thread_depth_mm=20))
    assert furo["drill_diameter_mm"] == pytest.approx(10.2)
    assert furo["mode"] in ("standard", "legacy")  # legacy quando o assistente ignora a norma
    assert furo["cosmetic_thread"]["callout"] == "M12x1.75"

    depois = session.run(lambda app: h.measure_bodies(app))[0]["volume_mm3"]
    esperado = math.pi * (10.2 / 2) ** 2 * 25
    assert antes - depois == pytest.approx(esperado, rel=1e-3), "furo saiu com outro tamanho"


def test_tamanho_fora_da_biblioteca_diz_onde_procurar(session, eixo):
    with pytest.raises(ComCallError, match="não está na biblioteca"):
        session.run(lambda app: h.hole_wizard(app, 0, 10, 0, 25, size="M13x1.9",
                                              standard="Ansi Metric", hole_type="tap"))


def test_canal_de_alivio_sai_com_rampas_e_raios(session, eixo):
    """O canal do desenho tem rampa em ângulo e raio no fundo, não canto vivo."""
    antes = session.run(lambda app: h.measure_bodies(app))[0]["volume_mm3"]
    r = session.run(lambda app: t.groove_relief(app, 70.0, 85.0, 30.0,
                                                ramp_angle_deg=60.0, corner_radius_mm=2.0))
    assert r["outer_diameter_start_mm"] == pytest.approx(40.0)
    assert r["fillet"], "os cantos do fundo ficaram vivos"

    depois = session.run(lambda app: h.measure_bodies(app))[0]["volume_mm3"]
    assert depois < antes, "o canal não removeu material"

    fundo = [e for e in session.run(lambda app: h.list_circular_edges(app, 29, 31))]
    assert fundo, "não há aresta no diâmetro do fundo do canal"


def test_canal_estreito_demais_avisa_em_vez_de_sair_torto(session, eixo):
    with pytest.raises(ComCallError, match="se cruzam antes do fundo"):
        session.run(lambda app: t.groove_relief(app, 70.0, 72.0, 30.0, ramp_angle_deg=60.0))


def test_rebaixo_plano_varre_o_cone_vizinho(session, eixo_com_colar):
    """Cortar só a largura do colar deixa dente no cone ao lado; auto_extend não."""
    r = session.run(lambda app: t.flats_across(app, 50.0, 40.0, 52.0))
    assert r["extended"], "o trecho devia crescer sozinho para varrer o cone"
    assert r["span_mm"][1] > 52.0, "parou na face do colar e deixou o dente do cone"
    assert not r["warnings"], f"sobrou material acima do plano: {r['warnings']}"

    # nada do corpo pode passar do entre-faces onde o rebaixo foi feito
    medido = session.run(lambda app: h.measure_bodies(app))[0]
    assert medido["box_mm"][1] == pytest.approx(-25.0, abs=0.01)
    assert medido["box_mm"][4] == pytest.approx(25.0, abs=0.01)


def test_rebaixo_avisa_quando_o_material_nao_acaba(session, eixo):
    """Num eixo reto, pedir entre-faces menor que o corpo varreria a peça toda."""
    r = session.run(lambda app: t.flats_across(app, 30.0, 43.0, 55.0))
    assert r["warnings"], "devia avisar que o material acima do plano não acaba"


@pytest.fixture
def eixo_com_colar(session):
    """Eixo Ø40 com colar Ø60 (x 40..52) e cone de 45° descendo até o corpo."""
    session.run(lambda app: o.new_document(app, "part"))
    title = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    perfil = [[0, 0], [0, 20], [40, 20], [40, 30], [52, 30], [62, 20], [100, 20], [100, 0]]
    session.run(lambda app: m.sketch_polyline(app, perfil, close_with_centerline=True))
    session.run(lambda app: m.revolve(app, 360.0))
    yield perfil
    session.run(lambda app: com_call(app, "CloseDoc", title))


def test_perfil_fica_totalmente_definido(session, eixo):
    r = session.run(lambda app: dm.fully_dimension_profile(app, "Esboço1", reset=True))
    assert r["fully_defined"], f"esboço continuou sub-definido (status {r['status']})"
    assert any("metro" in d["kind"] for d in r["dimensions"]), "nenhuma cota de diâmetro"
    assert any("comprimento" in d["kind"] for d in r["dimensions"]), "nenhuma cota axial"
