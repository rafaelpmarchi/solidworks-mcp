"""Cantos de aberturas numa chapa (domínio puro, sem COM).

Uma abertura recortada numa chapa (grelha de ventilação, fenda, janela) tem
cantos vivos: arestas retas que atravessam a espessura, ligando o contorno da
abertura na face da frente ao contorno na face de trás. Este módulo escolhe,
entre as arestas que chegam aos vértices desses contornos, as que são cantos
de verdade — o wrapper COM só coleta candidatos e aplica o filete.

Critérios (medidos ao vivo no SW2023, ver docs/decisoes/0006-cantos-de-abertura.md):
- reta e paralela à normal da chapa (atravessa a espessura);
- NÃO tangente: as duas faces vizinhas têm normais diferentes no ponto médio.
  Isso exclui a costura de um furo redondo e as bordas de um filete que já
  existe (o filete é tangente aos vizinhos), então a tool é idempotente;
- dentro da região opcional (caixa em mm), para tratar uma grelha por vez.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class EdgeCandidate:
    """Aresta que chega a um vértice do contorno de uma abertura (coordenadas em mm)."""

    start: Vec
    end: Vec
    plate_normal: Vec
    face_normals: tuple[Vec, ...] = ()  # normais das faces vizinhas no ponto médio
    is_line: bool = True


@dataclass(frozen=True)
class CornerEdge:
    """Canto escolhido; `index` aponta para o candidato original (objeto COM)."""

    index: int
    mid: Vec
    length_mm: float


@dataclass
class CornerSelection:
    corners: list[CornerEdge] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    def _skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v: Vec) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _cos_between(a: Vec, b: Vec) -> float:
    na, nb = _norm(a), _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb)


def _in_box(p: Vec, box: list[float] | tuple[float, ...]) -> bool:
    lo = [min(box[i], box[i + 3]) for i in range(3)]
    hi = [max(box[i], box[i + 3]) for i in range(3)]
    return all(lo[i] - 1e-6 <= p[i] <= hi[i] + 1e-6 for i in range(3))


def select_corner_edges(
    candidates: list[EdgeCandidate],
    region_mm: list[float] | tuple[float, ...] | None = None,
    angle_tol_deg: float = 1.0,
    min_length_mm: float = 0.05,
) -> CornerSelection:
    """Filtra os candidatos e devolve os cantos (sem repetição) e o motivo dos descartes.

    region_mm: [xmin, ymin, zmin, xmax, ymax, zmax] em mm; None = sem limite.
    """
    if region_mm is not None and len(region_mm) != 6:
        raise ValueError("region_mm precisa de 6 valores: [xmin, ymin, zmin, xmax, ymax, zmax]")
    cos_tol = math.cos(math.radians(angle_tol_deg))
    sel = CornerSelection()
    seen: set[tuple[Vec, Vec]] = set()
    for i, c in enumerate(candidates):
        if not c.is_line:
            sel._skip("nao_reta")
            continue
        d = _sub(c.end, c.start)
        length = _norm(d)
        if length < min_length_mm:
            sel._skip("degenerada")
            continue
        if _cos_between(d, c.plate_normal) < cos_tol:
            sel._skip("nao_atravessa_espessura")
            continue
        if len(c.face_normals) >= 2 and _cos_between(c.face_normals[0], c.face_normals[1]) >= cos_tol:
            sel._skip("tangente")  # costura de furo redondo ou filete já feito
            continue
        mid = tuple((c.start[k] + c.end[k]) / 2.0 for k in range(3))
        if region_mm is not None and not _in_box(mid, region_mm):
            sel._skip("fora_da_regiao")
            continue
        a = tuple(round(v, 3) for v in c.start)
        b = tuple(round(v, 3) for v in c.end)
        key = (a, b) if a <= b else (b, a)
        if key in seen:
            sel._skip("repetida")
            continue
        seen.add(key)
        sel.corners.append(CornerEdge(index=i, mid=mid, length_mm=round(length, 3)))
    sel.corners.sort(key=lambda e: e.mid)
    return sel
