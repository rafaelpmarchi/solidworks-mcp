"""Posição e rotação no formato do IMathTransform do SolidWorks (puro, sem COM).

O ArrayData de um IMathTransform tem 16 números: a matriz de rotação 3×3 em
[0..8], a translação em [9..11] (metros), a escala em [12] e três zeros. O
SolidWorks aplica a transformada a um ponto como VETOR-LINHA:

    p' = p · R + T   →   x' = x·a[0] + y·a[3] + z·a[6] + a[9]

então as três primeiras posições são a imagem do eixo X, as três seguintes a
do eixo Y e as últimas a do eixo Z. Montar isso à mão é onde a rotação sai
transposta sem ninguém perceber — por isso fica aqui, testado.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Matrix = list[list[float]]


def _rx(a: float) -> Matrix:
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def _ry(a: float) -> Matrix:
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def _rz(a: float) -> Matrix:
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def _mul(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _clean(v: float) -> float:
    """Zera o resíduo de cos(90°) — 6e-17 vira 0 e o ArrayData fica legível."""
    return 0.0 if abs(v) < 1e-12 else v


def rotation_matrix(rotation_deg: Sequence[float]) -> Matrix:
    """Matriz (vetor-coluna) de girar rx em X, depois ry em Y, depois rz em Z.

    Os giros são em torno dos eixos FIXOS da montagem, na ordem X → Y → Z.
    """
    rx, ry, rz = (math.radians(float(v)) for v in rotation_deg)
    m = _mul(_rz(rz), _mul(_ry(ry), _rx(rx)))
    return [[_clean(v) for v in linha] for linha in m]


def transform_array(origin_mm: Sequence[float],
                    rotation_deg: Sequence[float] = (0.0, 0.0, 0.0)) -> list[float]:
    """Os 16 números do ArrayData: rotação, translação (m) e escala 1."""
    m = rotation_matrix(rotation_deg)
    colunas = [m[i][j] for j in range(3) for i in range(3)]  # imagem de X, de Y, de Z
    x, y, z = (float(v) / 1000.0 for v in origin_mm)
    return [*colunas, x, y, z, 1.0, 0.0, 0.0, 0.0]


def to_local(array: Sequence[float], point_mm: Sequence[float]) -> tuple[float, float, float]:
    """Inverso de apply_transform: ponto da montagem → coordenadas da peça.

    A rotação é ortonormal, então a inversa é a transposta:
    p = (p' − T) · Rᵀ  →  p_i = Σ_j (p'_j − T_j) · a[3i + j].
    """
    a = array
    escala = a[12] if len(a) > 12 and a[12] else 1.0
    q = [float(point_mm[j]) - a[9 + j] * 1000.0 for j in range(3)]
    return tuple(sum(q[j] * a[3 * i + j] for j in range(3)) / escala for i in range(3))  # type: ignore[return-value]


def direction_to_local(array: Sequence[float], direction: Sequence[float]) -> tuple[float, float, float]:
    """Direção (sem translação) da montagem para a peça."""
    a = array
    return tuple(sum(float(direction[j]) * a[3 * i + j] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def apply_transform(array: Sequence[float], point_mm: Sequence[float]) -> tuple[float, float, float]:
    """Aplica um ArrayData a um ponto em mm (mesma convenção do SolidWorks)."""
    x, y, z = (float(v) for v in point_mm)
    a = array
    escala = a[12] if len(a) > 12 and a[12] else 1.0
    return (
        (x * a[0] + y * a[3] + z * a[6]) * escala + a[9] * 1000.0,
        (x * a[1] + y * a[4] + z * a[7]) * escala + a[10] * 1000.0,
        (x * a[2] + y * a[5] + z * a[8]) * escala + a[11] * 1000.0,
    )
