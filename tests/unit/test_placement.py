"""Transformada de componente no formato do IMathTransform (vetor-linha)."""

import pytest

from swmcp.domain.placement import apply_transform, rotation_matrix, transform_array


def _perto(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_identidade_so_translada():
    arr = transform_array((1000, 0, -400))
    assert arr[:9] == [1, 0, 0, 0, 1, 0, 0, 0, 1]
    assert arr[9:13] == [1.0, 0.0, -0.4, 1.0]
    assert len(arr) == 16
    assert _perto(apply_transform(arr, (40, 1900, 40)), (1040, 1900, -360))


def test_180_em_y_inverte_x_e_z():
    # coluna frontal direita da prateleira: pernas passam a apontar para -X e -Z
    arr = transform_array((1000, 0, 0), (0, 180, 0))
    assert _perto(apply_transform(arr, (40, 0, 0)), (960, 0, 0))
    assert _perto(apply_transform(arr, (0, 0, 40)), (1000, 0, -40))


def test_180_em_x_vira_de_cabeca_para_baixo():
    arr = transform_array((0, 1900, 0), (180, 0, 0))
    assert _perto(apply_transform(arr, (0, 17.5, 0)), (0, 1882.5, 0))


def test_90_em_z_leva_x_em_y():
    # convenção vetor-linha: as 3 primeiras posições são a imagem do eixo X
    arr = transform_array((0, 0, 0), (0, 0, 90))
    assert _perto(arr[0:3], (0, 1, 0))
    assert _perto(apply_transform(arr, (10, 0, 0)), (0, 10, 0))
    assert _perto(apply_transform(arr, (0, 10, 0)), (-10, 0, 0))


def test_ordem_x_depois_y_eixos_fixos():
    # 90 em X leva Y→Z; depois 90 em Y leva Z→X  ⇒  Y termina em X
    m = rotation_matrix((90, 90, 0))
    imagem_y = [m[i][1] for i in range(3)]
    assert _perto(imagem_y, (1, 0, 0))


@pytest.mark.parametrize("rot", [(0, 0, 0), (90, 0, 0), (30, 45, 60), (180, 90, -90)])
def test_rotacao_e_ortonormal(rot):
    m = rotation_matrix(rot)
    for i in range(3):
        for j in range(3):
            prod = sum(m[k][i] * m[k][j] for k in range(3))
            assert abs(prod - (1.0 if i == j else 0.0)) < 1e-12
