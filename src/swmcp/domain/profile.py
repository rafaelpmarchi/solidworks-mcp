"""Volume teórico de um perfil de revolução com linhas e arcos (puro, sem COM).

Pappus: V = 2π · r̄ · A, com A a área do perfil e r̄ a distância do centroide
ao eixo. Os arcos são discretizados finamente. É a conferência que pegou o
arco de entrada do U1 saindo como arco MAIOR (+10 000 mm³ onde a conta dava
+816): a massa sozinha parecia plausível.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class Segment:
    """Linha (center=None) ou arco (center + ccw) de start até end."""

    start: Point
    end: Point
    center: Point | None = None
    ccw: bool = True

    def points(self, n: int = 256) -> list[Point]:
        if self.center is None:
            return [self.start, self.end]
        cx, cy = self.center
        r = math.dist(self.center, self.start)
        a0 = math.atan2(self.start[1] - cy, self.start[0] - cx)
        a1 = math.atan2(self.end[1] - cy, self.end[0] - cx)
        if self.ccw:
            while a1 <= a0:
                a1 += 2 * math.pi
        else:
            while a1 >= a0:
                a1 -= 2 * math.pi
        return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n))
                for i in range(n + 1)]


def arc_length(seg: Segment) -> float:
    pts = seg.points(512)
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def chain(segments: Sequence[Segment], tol: float = 1e-3) -> list[Point]:
    """Encadeia os segmentos num contorno fechado (lista de pontos)."""
    restantes = [s.points() for s in segments]
    if not restantes:
        raise ValueError("perfil vazio")
    laco = list(restantes.pop(0))
    while restantes:
        fim = laco[-1]
        for i, pts in enumerate(restantes):
            if math.dist(pts[0], fim) < tol:
                laco += pts[1:]
                break
            if math.dist(pts[-1], fim) < tol:
                laco += list(reversed(pts))[1:]
                break
        else:
            raise ValueError(f"o perfil não fecha: nada continua em {fim}")
        restantes.pop(i)
    if math.dist(laco[0], laco[-1]) > tol:
        raise ValueError("o perfil não fecha no ponto inicial")
    return laco[:-1]


def revolved_volume(contour: Sequence[Point], axis_point: Point, axis_dir: Point) -> float:
    """Volume do sólido gerado girando o contorno fechado em torno do eixo."""
    ux, uy = axis_dir
    n = math.hypot(ux, uy)
    ux, uy = ux / n, uy / n
    # coordenadas (axial, radial com sinal) — o perfil fica de um lado só do eixo
    loc = [((p[0] - axis_point[0]) * ux + (p[1] - axis_point[1]) * uy,
            -(p[0] - axis_point[0]) * uy + (p[1] - axis_point[1]) * ux) for p in contour]
    area = 0.0
    momento = 0.0
    for (x0, y0), (x1, y1) in zip(loc, loc[1:] + loc[:1]):
        c = x0 * y1 - x1 * y0
        area += c
        momento += (y0 + y1) * c
    area /= 2.0
    if abs(area) < 1e-12:
        return 0.0
    r_centroide = momento / (6.0 * area)
    return abs(2 * math.pi * r_centroide * area)
