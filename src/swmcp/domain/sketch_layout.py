"""Plano de cotagem de pontos soltos de esboço (puro, sem COM).

Serve para o esboço de posição do assistente de furação e para qualquer
esboço de pontos: decide QUAIS relações e QUAIS cotas deixam o conjunto
totalmente definido do jeito que um desenhista cotaria.

- pontos com o mesmo X ficam numa COLUNA (relação vertical entre eles);
- pontos com o mesmo Y ficam numa LINHA (relação horizontal entre eles);
- as colunas são cotadas em cadeia na horizontal: a primeira a partir da
  origem, cada uma das seguintes a partir da anterior (16,5 → 955);
- as linhas idem na vertical, começando pela mais próxima da origem
  (17,5 → 15), que é como se cota um par de furos a partir da borda.

Com as relações, cada ponto herda o X da coluna e o Y da linha, então uma cota
por coluna e uma por linha bastam — nenhuma cota repetida (que sobredefiniria).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

TOL_MM = 1e-4


@dataclass
class PointLayout:
    columns: list[list[int]] = field(default_factory=list)   # índices, ordenados por Y
    rows: list[list[int]] = field(default_factory=list)      # índices, ordenados por X
    # cadeia de cotas: (ponto de referência ou None = origem, ponto cotado)
    horizontal_chain: list[tuple[int | None, int]] = field(default_factory=list)
    vertical_chain: list[tuple[int | None, int]] = field(default_factory=list)
    at_origin: list[int] = field(default_factory=list)
    # coluna em X=0 (fora da origem) não tem cota horizontal possível: prende
    # por relação vertical com a origem; idem linha em Y=0 com relação horizontal
    vertical_to_origin: list[int] = field(default_factory=list)
    horizontal_to_origin: list[int] = field(default_factory=list)


def _group(values: Sequence[float], tol: float) -> list[list[int]]:
    grupos: list[tuple[float, list[int]]] = []
    for i, v in enumerate(values):
        for chave, membros in grupos:
            if abs(chave - v) < tol:
                membros.append(i)
                break
        else:
            grupos.append((v, [i]))
    return [m for _, m in grupos]


def _chain(groups: list[list[int]], coord: Sequence[float],
           other: Sequence[float]) -> list[tuple[int | None, int]]:
    """Cadeia a partir da origem: ordena pelo valor e começa pelo mais perto de 0.

    O ponto que representa cada grupo é o mais perto da origem na outra
    direção — é dele que a cota sai, rente à borda, como no desenho.
    """
    reps = sorted((min(g, key=lambda i: abs(other[i])) for g in groups), key=lambda i: coord[i])
    if not reps:
        return []
    inicio = min(range(len(reps)), key=lambda k: abs(coord[reps[k]]))
    cadeia: list[tuple[int | None, int]] = []
    if abs(coord[reps[inicio]]) >= TOL_MM:
        cadeia.append((None, reps[inicio]))
    for k in range(inicio + 1, len(reps)):           # para um lado...
        cadeia.append((reps[k - 1], reps[k]))
    for k in range(inicio - 1, -1, -1):              # ...e para o outro
        cadeia.append((reps[k + 1], reps[k]))
    return cadeia


def plan_points(points_mm: Sequence[Sequence[float]], tol_mm: float = TOL_MM) -> PointLayout:
    """Relações e cotas para deixar pontos soltos totalmente definidos."""
    xs = [float(p[0]) for p in points_mm]
    ys = [float(p[1]) for p in points_mm]
    colunas = [sorted(g, key=lambda i: ys[i]) for g in _group(xs, tol_mm)]
    linhas = [sorted(g, key=lambda i: xs[i]) for g in _group(ys, tol_mm)]
    na_origem = [i for i in range(len(xs)) if abs(xs[i]) < tol_mm and abs(ys[i]) < tol_mm]
    return PointLayout(
        columns=colunas,
        rows=linhas,
        horizontal_chain=_chain(colunas, xs, ys),
        vertical_chain=_chain(linhas, ys, xs),
        at_origin=na_origem,
        # a origem já prende X e Y do grupo inteiro via relação da coluna/linha
        vertical_to_origin=[g[0] for g in colunas if abs(xs[g[0]]) < tol_mm
                            and not any(i in na_origem for i in g)],
        horizontal_to_origin=[g[0] for g in linhas if abs(ys[g[0]]) < tol_mm
                              and not any(i in na_origem for i in g)],
    )
