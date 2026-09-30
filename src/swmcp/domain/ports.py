"""Pórtico hidráulico e canal furado como perfil de revolução (puro, sem COM).

Um pórtico G (rosca cilíndrica ISO 228) em bloco hidráulico tem três
diâmetros no mesmo eixo: o rebaixo de vedação (d2 × a), a broca da rosca até t
e, quando segue para dentro do bloco, o canal de ligação, que termina na ponta
de broca de 118°. O assistente de furação do SW2023 não faz isso numa feature
só — o rebaixo customizado sai em polegada (ver holes.py) —, então o pórtico é
um corte por revolução deste meio-perfil em torno do eixo do furo.

Coordenadas do meio-perfil: s ao longo do eixo (0 = face de entrada, positivo
para dentro da peça) e r o raio. O perfil começa em s = -overshoot, FORA da
peça: assim o rebaixo corta também um ressalto ou aba que esteja por cima da
face (o erro do ressalto NG6 do 3-50200-92000, em que o furo feito a partir da
face do bloco deixou 0,5 mm de ressalto sobre o rebaixo).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# ponta de broca de 118°: comprimento do cone = r / tan(59°)
DRILL_POINT_FACTOR = 1.0 / math.tan(math.radians(59.0))


@dataclass(frozen=True)
class PipePort:
    """Medidas de um pórtico G (DIN EN ISO 1179-1 / DIN 3852, tabela Siemens).

    d2: Ø do rebaixo de vedação; b: comprimento roscado mínimo; t: profundidade
    da broca da rosca; tap_drill: broca de macho (ISO 228); minor: Ø menor da
    rosca (ISO 228-1).
    """

    size: str
    d2: float
    b: float
    t: float
    tap_drill: float
    minor: float


# d2, b, t: tabelas dos desenhos Siemens 3-50200-92000 e -92309 ("Einschraub-
# löcher ähnlich DIN EN ISO 1179-1"); broca e Ø menor: ISO 228-1.
PIPE_PORTS: dict[str, PipePort] = {
    "G1/8": PipePort("G1/8", 15.0, 10.0, 12.0, 8.8, 8.566),
    "G1/4": PipePort("G1/4", 20.0, 14.0, 17.0, 11.8, 11.445),
    "G3/8": PipePort("G3/8", 23.0, 14.0, 17.0, 15.25, 14.950),
    "G1/2": PipePort("G1/2", 28.0, 17.0, 21.0, 19.0, 18.631),
    "G3/4": PipePort("G3/4", 33.0, 18.0, 22.0, 24.5, 24.117),
}


def pipe_port(size: str) -> PipePort:
    chave = size.strip().upper().replace(" ", "")
    if chave not in PIPE_PORTS:
        raise ValueError(f"pórtico {size!r} não está na tabela — tamanhos: {sorted(PIPE_PORTS)}")
    return PIPE_PORTS[chave]


def drill_profile(diameter: float, length: float, overshoot: float = 2.0,
                  point: bool = True) -> list[tuple[float, float]]:
    """Meio-perfil fechado (s, r) de um furo liso: cilindro até length + ponta."""
    if diameter <= 0 or length <= 0:
        raise ValueError("diâmetro e comprimento do furo precisam ser positivos")
    r = diameter / 2.0
    pts = [(-overshoot, 0.0), (-overshoot, r), (length, r)]
    pts.append((length + r * DRILL_POINT_FACTOR, 0.0) if point else (length, 0.0))
    return pts


def port_profile(size: str, spot_depth: float = 1.0, thread_drill_depth: float | None = None,
                 channel_diameter: float = 0.0, channel_length: float = 0.0,
                 overshoot: float = 5.0, spot_diameter: float | None = None,
                 thread_drill: float | None = None) -> list[tuple[float, float]]:
    """Meio-perfil fechado (s, r) do pórtico: rebaixo, broca da rosca e canal.

    spot_depth é o "a" do desenho (1 no rebaixo raso, 5,5 onde o desenho cota);
    thread_drill_depth padrão = t da tabela. Com channel_diameter/length o furo
    continua como canal até channel_length (medido da face, fim do cilindro) e
    termina em ponta de broca; sem canal a ponta fica no fim da broca da rosca.
    """
    p = pipe_port(size)
    r2 = (spot_diameter or p.d2) / 2.0
    rt = (thread_drill or p.tap_drill) / 2.0
    t = p.t if thread_drill_depth is None else thread_drill_depth
    if spot_depth <= 0 or t <= spot_depth:
        raise ValueError("a broca da rosca precisa ir além do rebaixo (t > a > 0)")
    if rt >= r2:
        raise ValueError("a broca da rosca tem que ser menor que o rebaixo")
    pts = [(-overshoot, 0.0), (-overshoot, r2), (spot_depth, r2), (spot_depth, rt)]
    if channel_diameter and channel_length:
        rc = channel_diameter / 2.0
        if rc > rt:
            raise ValueError("o canal tem que ser menor ou igual à broca da rosca")
        if channel_length <= t:
            raise ValueError("o canal tem que terminar depois da broca da rosca")
        if rc < rt:
            # degrau com o cone de 118° da broca maior
            pts += [(t, rt), (t + (rt - rc) * DRILL_POINT_FACTOR, rc)]
        pts += [(channel_length, rc), (channel_length + rc * DRILL_POINT_FACTOR, 0.0)]
    else:
        pts += [(t, rt), (t + rt * DRILL_POINT_FACTOR, 0.0)]
    return pts


def profile_volume_mm3(profile: Sequence[tuple[float, float]]) -> float:
    """Volume do sólido de revolução do meio-perfil (soma de troncos de cone)."""
    total = 0.0
    for (s1, r1), (s2, r2) in zip(profile, profile[1:]):
        total += math.pi / 3.0 * (r1 * r1 + r1 * r2 + r2 * r2) * (s2 - s1)
    return abs(total)


# ------------------------------------------------------------ geometria 3D

Vec = tuple[float, float, float]

# normais dos três planos base (Frontal = XY, Superior = XZ, Direito = YZ) e o
# índice da coordenada que o offset do plano paralelo segue
BASE_PLANES = (("front", (0.0, 0.0, 1.0), 2), ("top", (0.0, 1.0, 0.0), 1),
               ("right", (1.0, 0.0, 0.0), 0))


def normalize(v: Sequence[float]) -> Vec:
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        raise ValueError("direção nula")
    return (v[0] / n, v[1] / n, v[2] / n)


def cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass(frozen=True)
class AxisPlane:
    """Plano paralelo a um plano base que contém o eixo do furo."""

    base: str            # "front" | "top" | "right"
    normal: Vec
    offset_mm: float     # coordenada do plano ao longo da normal
    radial: Vec          # direção do raio do meio-perfil, dentro do plano


def axis_plane(start: Sequence[float], direction: Sequence[float],
               prefer: str | None = None) -> AxisPlane:
    """Escolhe o plano base cujo paralelo contém o eixo (start + s·direction).

    O eixo precisa ser perpendicular à normal de algum plano base — furo
    normal a uma face do bloco, ou inclinado DENTRO de um plano de vista (os
    canais das interfaces NG6: 10° em planta, 12,5° em elevação). Eixo
    oblíquo aos três planos não tem plano paralelo que o contenha.
    """
    d = normalize(direction)
    candidatos = [p for p in BASE_PLANES if abs(dot(p[1], d)) < 1e-6]
    if prefer:
        candidatos.sort(key=lambda p: p[0] != prefer)
    if not candidatos:
        raise ValueError("o eixo é oblíquo aos três planos base — não há plano paralelo que o contenha")
    nome, normal, idx = candidatos[0]
    radial = normalize(cross(normal, d))
    return AxisPlane(nome, normal, float(start[idx]), radial)


def profile_to_model(start: Sequence[float], direction: Sequence[float], radial: Sequence[float],
                     profile: Sequence[tuple[float, float]]) -> list[Vec]:
    """Pontos (s, r) do meio-perfil → coordenadas da peça (mm)."""
    d = normalize(direction)
    return [tuple(start[i] + s * d[i] + r * radial[i] for i in range(3)) for s, r in profile]  # type: ignore[misc]


def direction_from_angles(base_direction: Sequence[float], toward: Sequence[float],
                          angle_deg: float) -> Vec:
    """Gira base_direction de angle_deg na direção de 'toward' (no plano dos dois).

    É como o desenho cota um canal inclinado: "entra normal à face e desvia 10°
    para o lado X". toward precisa ser perpendicular a base_direction.
    """
    b = normalize(base_direction)
    t = normalize(toward)
    if abs(dot(b, t)) > 1e-6:
        raise ValueError("'toward' precisa ser perpendicular à direção base")
    a = math.radians(angle_deg)
    return normalize(tuple(math.cos(a) * b[i] + math.sin(a) * t[i] for i in range(3)))
