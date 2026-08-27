"""Segmentação liso × rugoso por variação local de normais.

Face usinada (flange, mancal, furo) tem normais coerentes na vizinhança;
superfície bruta de fundição tem normais espalhadas. Medimos a "rugosidade"
de cada vértice como o desvio angular das normais dos vizinhos e separamos
por limiar, depois agrupamos em componentes conexas.
"""

from __future__ import annotations

import numpy as np
import trimesh
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


def vertex_roughness(mesh: trimesh.Trimesh, radius_mm: float = 3.0) -> np.ndarray:
    """Desvio angular médio (graus) das normais na vizinhança de cada vértice."""
    normals = mesh.vertex_normals
    tree = cKDTree(mesh.vertices)
    neighbors = tree.query_ball_point(mesh.vertices, r=radius_mm, workers=-1)
    rough = np.zeros(len(mesh.vertices))
    for i, idx in enumerate(neighbors):
        if len(idx) < 3:
            rough[i] = 0.0
            continue
        local = normals[idx]
        mean = local.mean(axis=0)
        norm = np.linalg.norm(mean)
        if norm < 1e-12:
            rough[i] = 90.0
            continue
        mean /= norm
        cos = np.clip(local @ mean, -1.0, 1.0)
        rough[i] = float(np.degrees(np.arccos(cos)).mean())
    return rough


def segment(mesh: trimesh.Trimesh, radius_mm: float = 3.0,
            smooth_threshold_deg: float = 8.0,
            min_region_vertices: int = 50) -> tuple[np.ndarray, list[dict]]:
    """Rotula vértices: 0 = rugoso/não classificado; 1..N = regiões lisas conexas.

    Retorna (labels, stats) onde stats descreve cada região liso encontrada.
    """
    rough = vertex_roughness(mesh, radius_mm)
    smooth_mask = rough <= smooth_threshold_deg

    # grafo de adjacência restrito aos vértices lisos
    edges = mesh.edges_unique
    keep = smooth_mask[edges].all(axis=1)
    edges = edges[keep]

    n = len(mesh.vertices)
    from scipy.sparse import coo_matrix
    if len(edges):
        adj = coo_matrix(
            (np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(n, n)
        )
        _, comp = connected_components(adj, directed=False)
    else:
        comp = np.arange(n)

    labels = np.zeros(n, dtype=np.int32)
    stats: list[dict] = []
    next_label = 1
    for c in np.unique(comp[smooth_mask]):
        members = np.flatnonzero((comp == c) & smooth_mask)
        if len(members) < min_region_vertices:
            continue
        pts = mesh.vertices[members]
        labels[members] = next_label
        stats.append({
            "label": next_label,
            "vertices": int(len(members)),
            "centroid_mm": [round(float(x), 3) for x in pts.mean(axis=0)],
            "bounds_min_mm": [round(float(x), 3) for x in pts.min(axis=0)],
            "bounds_max_mm": [round(float(x), 3) for x in pts.max(axis=0)],
            "roughness_deg": round(float(rough[members].mean()), 2),
        })
        next_label += 1

    stats.sort(key=lambda s: -s["vertices"])
    return labels, stats
