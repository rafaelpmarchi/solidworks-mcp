"""Casamento geométrico de entidade de mate e inversa da transformada."""

import pytest

from swmcp.domain.entity_match import (
    parallel,
    point_line_distance,
    point_plane_distance,
    same_line,
    same_plane,
    shifted,
)
from swmcp.domain.placement import apply_transform, direction_to_local, to_local, transform_array


def test_paralelo_aceita_sentido_oposto():
    assert parallel((1, 0, 0), (-2, 0, 0))
    assert not parallel((1, 0, 0), (1, 0.1, 0))
    assert not parallel((0, 0, 0), (1, 0, 0))


def test_ponto_do_mate_fora_da_face_ainda_esta_no_plano():
    # o mate da ponta do rasgo guardou y=450, 50 mm abaixo da própria face
    assert point_plane_distance((58, 450, -109.82), (58, 497, -105), (1, 0, 0)) == pytest.approx(0)
    assert same_plane((58, 450, -109.82), (1, 0, 0), (58, 0, 0), (-1, 0, 0), 0.01)
    assert not same_plane((58, 450, 0), (1, 0, 0), (90, 0, 0), (1, 0, 0), 0.01)


def test_reta_e_eixo():
    assert point_line_distance((5, 3, 0), (0, 0, 0), (1, 0, 0)) == pytest.approx(3)
    assert same_line((100, 497.35, -106.82), (1, 0, 0), (58, 497.35, -106.82), (-1, 0, 0), 0.01)
    assert not same_line((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 0, 0), 0.01)


def test_deslocamento():
    assert shifted((73, 500, -108.32), (-32, 0, 96.6667)) == pytest.approx([41, 500, -11.6533])


@pytest.mark.parametrize("rot", [(0, 0, 0), (180, 0, 0), (34.08, 0, 0), (30, 45, 60)])
def test_to_local_desfaz_apply(rot):
    arr = transform_array((73, 491.72, -104.21), rot)
    p = (12.5, -3.0, 40.0)
    assert to_local(arr, apply_transform(arr, p)) == pytest.approx(p)


def test_direcao_para_local_ignora_translacao():
    arr = transform_array((1000, 0, 0), (0, 180, 0))
    assert direction_to_local(arr, (1, 0, 0)) == pytest.approx((-1, 0, 0))
