"""Geometria do alívio DIN 509 forma E (puro, sem COM).

No canto interno entre a superfície cilíndrica e o ressalto, o alívio entra
na superfície cilíndrica: um raio r tangente ao ressalto e ao fundo, o fundo
t abaixo da superfície, e uma rampa de saída em ângulo até a superfície,
totalizando a largura f medida sobre a superfície a partir do canto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]

# (raio r, profundidade t) → largura f padrão da norma (mm)
DIN509_E_WIDTH: dict[tuple[float, float], float] = {
    (0.2, 0.1): 1.0, (0.4, 0.2): 2.0, (0.6, 0.2): 2.0, (0.6, 0.3): 2.5,
    (0.8, 0.3): 2.5, (1.0, 0.2): 2.5, (1.0, 0.4): 4.0, (1.2, 0.2): 2.5,
    (1.2, 0.4): 4.0, (1.6, 0.3): 4.0, (1.6, 0.6): 5.0, (2.5, 0.4): 5.0,
    (2.5, 0.6): 7.0, (4.0, 0.5): 7.0, (4.0, 1.0): 10.0,
}
RAMP_DEG = 15.0


@dataclass(frozen=True)
class Undercut:
    shoulder: Point      # início do arco, sobre o ressalto (a r−t do canto)
    floor_start: Point   # fim do arco / início do fundo
    floor_end: Point     # fim do fundo / início da rampa
    cylinder: Point      # fim da rampa, sobre a superfície cilíndrica (a f do canto)
    arc_center: Point
    width: float


def unit(dx: float, dy: float) -> Point:
    n = math.hypot(dx, dy)
    if n < 1e-9:
        raise ValueError("vetor nulo")
    return dx / n, dy / n


def default_width(radius: float, depth: float) -> float | None:
    return DIN509_E_WIDTH.get((round(radius, 2), round(depth, 2)))


def din509_e(corner: Point, along: Point, into_material: Point, radius: float, depth: float,
             width: float | None = None, ramp_deg: float = RAMP_DEG) -> Undercut:
    """Pontos do alívio no canto, dados o versor ao longo da superfície
    cilíndrica (saindo do canto) e o versor perpendicular para dentro do
    material. Levanta ValueError para combinação impossível."""
    if radius <= depth:
        raise ValueError("o raio precisa ser maior que a profundidade (forma E)")
    f = width or default_width(radius, depth)
    if not f:
        raise ValueError("par r×t fora da tabela DIN 509 — informe a largura")
    rampa = depth / math.tan(math.radians(ramp_deg))
    if f <= radius + rampa:
        raise ValueError("largura pequena demais para o raio e a rampa")
    u, n = along, into_material
    if abs(u[0] * n[0] + u[1] * n[1]) > 1e-6:
        raise ValueError("os versores precisam ser perpendiculares")

    def p(su: float, sn: float) -> Point:
        return corner[0] + u[0] * su + n[0] * sn, corner[1] + u[1] * su + n[1] * sn

    return Undercut(
        shoulder=p(0.0, depth - radius),
        floor_start=p(radius, depth),
        floor_end=p(f - rampa, depth),
        cylinder=p(f, 0.0),
        arc_center=p(radius, depth - radius),
        width=f,
    )
