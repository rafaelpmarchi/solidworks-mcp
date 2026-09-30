"""Geometria do alívio DIN 509 forma E (sem SolidWorks)."""

import math

import pytest

from swmcp.domain.undercut import default_width, din509_e


def test_e08x03_num_furo_bate_com_o_desenho_da_siemens():
    # canto do Ø200 H8 com o degrau, no esboço do perfil (x = raio, y = -Z):
    # cilindro sobe (+y), ressalto vai para o eixo (-x), material está em +x
    geo = din509_e(corner=(100.0, -166.0), along=(0.0, 1.0), into_material=(1.0, 0.0),
                   radius=0.8, depth=0.3)
    assert geo.width == 2.5
    assert geo.shoulder == pytest.approx((99.5, -166.0))
    assert geo.floor_start == pytest.approx((100.3, -165.2))
    assert geo.floor_end == pytest.approx((100.3, -166.0 + 2.5 - 0.3 / math.tan(math.radians(15))))
    assert geo.cylinder == pytest.approx((100.0, -163.5))
    assert geo.arc_center == pytest.approx((99.5, -165.2))


def test_num_eixo_o_material_fica_para_dentro():
    # eixo Ø50 com ressalto para Ø80: canto em (25, 0), cilindro para +x,
    # ressalto sobe (+y), material para baixo (-y)
    geo = din509_e(corner=(25.0, 0.0), along=(1.0, 0.0), into_material=(0.0, -1.0),
                   radius=0.6, depth=0.2)
    assert geo.width == 2.0
    assert geo.floor_start[1] == pytest.approx(-0.2)
    assert geo.shoulder == pytest.approx((25.0, 0.4))   # arco começa no ressalto, r-t acima
    assert geo.cylinder == pytest.approx((27.0, 0.0))


def test_arco_e_tangente_ao_ressalto_e_ao_fundo():
    geo = din509_e((0.0, 0.0), (0.0, 1.0), (1.0, 0.0), 0.8, 0.3)
    # centro a r do ressalto (x = t - r) e a r do fundo (x = t): tangências
    assert geo.arc_center[0] == pytest.approx(geo.shoulder[0])
    assert geo.arc_center[0] + 0.8 == pytest.approx(geo.floor_start[0])
    assert math.dist(geo.arc_center, geo.shoulder) == pytest.approx(0.8)
    assert math.dist(geo.arc_center, geo.floor_start) == pytest.approx(0.8)


@pytest.mark.parametrize("r,t", [(0.3, 0.3), (0.2, 0.5)])
def test_raio_menor_ou_igual_a_profundidade_e_recusado(r, t):
    with pytest.raises(ValueError, match="raio"):
        din509_e((0, 0), (0, 1), (1, 0), r, t, width=5)


def test_par_fora_da_norma_pede_largura():
    assert default_width(0.7, 0.3) is None
    with pytest.raises(ValueError, match="largura"):
        din509_e((0, 0), (0, 1), (1, 0), 0.7, 0.3)
    assert din509_e((0, 0), (0, 1), (1, 0), 0.7, 0.3, width=3).width == 3


def test_largura_menor_que_raio_mais_rampa_e_recusada():
    with pytest.raises(ValueError, match="largura pequena"):
        din509_e((0, 0), (0, 1), (1, 0), 0.8, 0.3, width=1.5)


def test_versores_nao_perpendiculares_sao_recusados():
    with pytest.raises(ValueError, match="perpendiculares"):
        din509_e((0, 0), (0, 1), (0.5, 0.5), 0.8, 0.3)
