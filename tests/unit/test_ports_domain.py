"""Pórtico G, canal furado e plano do eixo (sem SolidWorks)."""

import math

import pytest

from swmcp.domain import ports as p
from swmcp.domain.tree import desired_sequence, order_mismatches


def test_tabela_bate_com_o_desenho_siemens():
    g34 = p.pipe_port("g3/4")
    assert (g34.d2, g34.b, g34.t, g34.tap_drill) == (33.0, 18.0, 22.0, 24.5)
    assert p.pipe_port("G1/8").d2 == 15.0
    with pytest.raises(ValueError, match="tabela"):
        p.pipe_port("G2")


def test_perfil_do_p_do_92000_rebaixo_rosca_e_canal():
    # P G1/2: rebaixo Ø28x1, broca 19 até 21, canal Ø11,75 até 230
    prof = p.port_profile("G1/2", spot_depth=1, channel_diameter=11.75, channel_length=230)
    assert prof[0] == (-5.0, 0.0) and prof[1] == (-5.0, 14.0)   # começa fora da peça
    assert prof[2] == (1, 14.0) and prof[3] == (1, 9.5)
    assert prof[4] == (21.0, 9.5)
    assert prof[5][1] == 5.875 and prof[5][0] == pytest.approx(21 + (9.5 - 5.875) / math.tan(math.radians(59)))
    assert prof[6] == (230, 5.875)
    assert prof[-1][1] == 0.0 and prof[-1][0] == pytest.approx(230 + 5.875 / math.tan(math.radians(59)))


def test_perfil_sem_canal_termina_na_ponta_da_broca_da_rosca():
    prof = p.port_profile("G1/4", spot_depth=5.5)
    assert prof[-2] == (17.0, 5.9) and prof[-1][1] == 0.0


@pytest.mark.parametrize("kw,msg", [
    ({"spot_depth": 30}, "t > a"),
    ({"channel_diameter": 30, "channel_length": 100}, "menor ou igual"),
    ({"channel_diameter": 10, "channel_length": 10}, "depois da broca"),
])
def test_perfil_recusa_medida_impossivel(kw, msg):
    with pytest.raises(ValueError, match=msg):
        p.port_profile("G3/4", **kw)


def test_volume_do_furo_liso_e_cilindro_mais_cone():
    prof = p.drill_profile(10, 50, overshoot=0, point=True)
    esperado = math.pi * 25 * 50 + math.pi * 25 * (5 * p.DRILL_POINT_FACTOR) / 3
    assert p.profile_volume_mm3(prof) == pytest.approx(esperado)


def test_plano_do_eixo_furo_na_face_y_fica_no_frontal_ou_superior():
    pl = p.axis_plane((-72, 125, 249), (0, -1, 0))
    assert pl.base == "front" and pl.offset_mm == 249
    assert abs(p.dot(pl.radial, (0, -1, 0))) < 1e-9 and abs(p.dot(pl.radial, pl.normal)) < 1e-9


def test_canal_inclinado_em_planta_usa_o_plano_frontal():
    d = p.direction_from_angles((0, 1, 0), (1, 0, 0), 7.5)   # V-A do 92000
    pl = p.axis_plane((-6.2, -125.5, 238.6), d)
    assert pl.base == "front" and pl.offset_mm == 238.6
    fim = p.profile_to_model((-6.2, -125.5, 238.6), d, pl.radial, [(51, 0)])[0]
    assert fim[0] == pytest.approx(0.457, abs=1e-3) and fim[1] == pytest.approx(-74.94, abs=1e-2)


def test_canal_inclinado_em_elevacao_usa_o_plano_direito():
    d = p.direction_from_angles((0, 1, 0), (0, 0, -1), 12.5)  # V-T sobe 12,5°
    assert p.axis_plane((-15, -125.5, 228.2), d).base == "right"


def test_eixo_obliquo_nao_tem_plano():
    with pytest.raises(ValueError, match="oblíquo"):
        p.axis_plane((0, 0, 0), (1, 1, 1))


def test_toward_precisa_ser_perpendicular():
    with pytest.raises(ValueError, match="perpendicular"):
        p.direction_from_angles((0, 1, 0), (0, 1, 1), 10)


def test_sequencia_e_divergencia_da_arvore():
    grupos = [("TOPO", ["a", "b"]), ("Face +Y", ["c"])]
    assert desired_sequence(grupos) == ["a", "b", "c"]
    assert order_mismatches(["x", "a", "Esboço9", "b", "c"], ["a", "b", "c"]) == []
    assert order_mismatches(["b", "a", "c"], ["a", "b", "c"]) == [("a", "b"), ("b", "a")]
    assert order_mismatches(["a"], ["a", "z"]) == [("z", "<não está na árvore>")]
    with pytest.raises(ValueError, match="mais de um grupo"):
        desired_sequence([("A", ["a"]), ("B", ["a"])])
