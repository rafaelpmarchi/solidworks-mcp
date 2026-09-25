"""Casar a entidade de um mate com uma face/aresta do corpo (puro, sem COM).

O mate guarda cada lado como IMateEntity2.EntityParams: um ponto QUALQUER do
plano/reta infinitos (não necessariamente em cima da face) + a direção, e o
raio quando é cilindro/círculo. Por isso "o ponto está na face" não serve para
achar a entidade de volta — o teste certo é geométrico (a face está NO plano,
a aresta está NA reta) e, quando várias estão no mesmo plano (as pontas de
dois rasgos alinhados), desempata quem fica mais perto de um ponto de
referência.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Vec = Sequence[float]

ANGLE_TOL = 1e-4     # |cos| a menos de 1e-4 de 1 ⇒ paralelos (~0,8°·10⁻²)


def _dot(a: Vec, b: Vec) -> float:
    return sum(float(a[i]) * float(b[i]) for i in range(3))


def _sub(a: Vec, b: Vec) -> list[float]:
    return [float(a[i]) - float(b[i]) for i in range(3)]


def _norm(a: Vec) -> float:
    return math.sqrt(_dot(a, a))


def distance(a: Vec, b: Vec) -> float:
    return _norm(_sub(a, b))


def parallel(a: Vec, b: Vec, tol: float = ANGLE_TOL) -> bool:
    """Mesma direção ou oposta (normais e eixos não têm sentido fixo no mate)."""
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return False
    return abs(abs(_dot(a, b) / (na * nb)) - 1.0) <= tol


def point_plane_distance(point: Vec, plane_origin: Vec, normal: Vec) -> float:
    n = _norm(normal)
    return abs(_dot(_sub(point, plane_origin), normal)) / n


def point_line_distance(point: Vec, line_origin: Vec, direction: Vec) -> float:
    w = _sub(point, line_origin)
    d = _norm(direction)
    k = _dot(w, direction) / (d * d)
    return _norm([w[i] - k * float(direction[i]) for i in range(3)])


def same_plane(p: Vec, n: Vec, q: Vec, m: Vec, tol_mm: float) -> bool:
    """O plano (p, n) é o mesmo plano (q, m)?"""
    return parallel(n, m) and point_plane_distance(p, q, m) <= tol_mm


def same_line(p: Vec, d: Vec, q: Vec, e: Vec, tol_mm: float) -> bool:
    """A reta (p, d) é a mesma reta (q, e)? Serve para eixo de cilindro também."""
    return parallel(d, e) and point_line_distance(p, q, e) <= tol_mm


def shifted(point: Vec, offset: Vec) -> list[float]:
    return [float(point[i]) + float(offset[i]) for i in range(3)]
