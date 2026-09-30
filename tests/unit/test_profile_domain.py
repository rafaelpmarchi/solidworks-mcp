"""Canal U1 e volume de perfil de revolução com arcos (sem SolidWorks)."""

import math

import pytest

from swmcp.domain.profile import Segment, arc_length, chain, revolved_volume
from swmcp.domain.undercut import relief_groove


def test_u1_do_92000_no_perfil_x_raio_y_menos_z():
    # canto Ø200 × degrau em (100, -157): parede sobe (+y), material em +x
    g = relief_groove((100.0, -157.0), (0.0, 1.0), (1.0, 0.0), depth=0.4, height=4.0, radius=1.6)
    dz = math.sqrt(1.6**2 - 1.2**2)
    assert g.shoulder == pytest.approx((98.8, -157.0))
    assert g.floor_start == pytest.approx((100.4, -155.4))
    assert g.floor_end == pytest.approx((100.4, -153.0 - dz))
    assert g.wall == pytest.approx((100.0, -153.0))
    # os dois arcos têm raio 1,6 e são tangentes ao fundo
    assert math.dist(g.foot_center, g.shoulder) == pytest.approx(1.6)
    assert math.dist(g.entry_center, g.wall) == pytest.approx(1.6)
    assert g.entry_center[0] == pytest.approx(g.floor_end[0] - 1.6)


@pytest.mark.parametrize("kw,msg", [({"depth": 2.0}, "menor que o raio"),
                                    ({"height": 2.0}, "altura pequena")])
def test_u1_recusa_medida_impossivel(kw, msg):
    base = {"depth": 0.4, "height": 4.0, "radius": 1.6}
    with pytest.raises(ValueError, match=msg):
        relief_groove((0, 0), (0, 1), (1, 0), **{**base, **kw})


def test_volume_de_cilindro_e_de_anel():
    # retângulo r 0..10, z 0..20 girando em torno do eixo y (x=0)
    ret = [(0, 0), (10, 0), (10, 20), (0, 20)]
    assert revolved_volume(ret, (0, 0), (0, 1)) == pytest.approx(math.pi * 100 * 20)
    anel = [(5, 0), (10, 0), (10, 20), (5, 20)]
    assert revolved_volume(anel, (0, 0), (0, 1)) == pytest.approx(math.pi * 75 * 20)


def test_arco_maior_e_arco_menor_tem_volumes_bem_diferentes():
    # semicírculo sobre o eixo x gira e vira esfera
    semi = [Segment((10, 0), (-10, 0), (0, 0), ccw=True), Segment((-10, 0), (10, 0))]
    v = revolved_volume(chain(semi), (0, 0), (1, 0))
    assert v == pytest.approx(4 / 3 * math.pi * 1000, rel=1e-4)
    curto = Segment((1.2, 1.058), (1.6, 0.0), (0, 0), ccw=False)
    longo = Segment((1.2, 1.058), (1.6, 0.0), (0, 0), ccw=True)
    assert arc_length(curto) == pytest.approx(1.6 * math.atan2(1.058, 1.2), rel=1e-3)
    assert arc_length(longo) > 5 * arc_length(curto)


def test_perfil_que_nao_fecha_e_recusado():
    with pytest.raises(ValueError, match="não fecha"):
        chain([Segment((0, 0), (1, 0)), Segment((5, 5), (6, 6))])
