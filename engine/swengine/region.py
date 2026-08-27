"""Delimitação de regiões da malha sem picking gráfico.

Uma "região" é um dict JSON vindo do chat/MCP. Formas aceitas:
- {"box": {"min": [x,y,z], "max": [x,y,z]}}          caixa alinhada aos eixos
- {"axis_range": {"axis": "z", "min": 80, "max": 120}} faixa numa coordenada
- {"seed": {"point": [x,y,z], "radius": 15}}          esfera em torno de um ponto
- {"labels": {"path": "labels.npy", "value": 3}}      rótulos salvos pela segmentação
- {"mask": {"path": "mask.npy"}}                      máscara booleana (pincel do viewer)
- None                                                 malha inteira
Combinações: {"box": ..., "axis_range": ...} -> interseção (E lógico).
"""

from __future__ import annotations

import numpy as np
import trimesh

_AXES = {"x": 0, "y": 1, "z": 2}


def region_vertex_mask(mesh: trimesh.Trimesh, region: dict | None) -> np.ndarray:
    """Máscara booleana (n_vertices,) dos vértices dentro da região."""
    n = len(mesh.vertices)
    mask = np.ones(n, dtype=bool)
    if not region:
        return mask
    v = mesh.vertices

    if "box" in region:
        lo = np.asarray(region["box"]["min"], dtype=float)
        hi = np.asarray(region["box"]["max"], dtype=float)
        mask &= np.all((v >= lo) & (v <= hi), axis=1)

    if "axis_range" in region:
        ar = region["axis_range"]
        idx = _AXES[ar["axis"].lower()]
        if "min" in ar and ar["min"] is not None:
            mask &= v[:, idx] >= float(ar["min"])
        if "max" in ar and ar["max"] is not None:
            mask &= v[:, idx] <= float(ar["max"])

    if "seed" in region:
        p = np.asarray(region["seed"]["point"], dtype=float)
        r = float(region["seed"]["radius"])
        mask &= np.linalg.norm(v - p, axis=1) <= r

    if "mask" in region:
        m = np.load(region["mask"]["path"])
        if len(m) != n:
            raise ValueError(
                f"mask tem {len(m)} entradas, malha tem {n} vértices — "
                "a seleção foi feita em outra malha/decimação")
        mask &= m.astype(bool)

    if "labels" in region:
        labels = np.load(region["labels"]["path"])
        if len(labels) != n:
            raise ValueError(
                f"labels tem {len(labels)} entradas, malha tem {n} vértices — "
                "segmentação foi feita em outra malha/decimação"
            )
        mask &= labels == int(region["labels"]["value"])

    if not mask.any():
        raise ValueError("região não contém nenhum vértice da malha")
    return mask


def region_face_mask(mesh: trimesh.Trimesh, region: dict | None) -> np.ndarray:
    """Máscara de faces cujos 3 vértices estão na região."""
    vmask = region_vertex_mask(mesh, region)
    return vmask[mesh.faces].all(axis=1)
