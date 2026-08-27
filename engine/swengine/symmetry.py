"""Detecção de plano de simetria (comando 'Symmetry plane' do QuickSurface).

Candidatos: os 3 planos principais (PCA) pelo centroide. Cada candidato é
avaliado espelhando uma amostra da malha e medindo a distância ao vizinho
mais próximo; o melhor é refinado por Nelder-Mead (normal + offset).
"""

from __future__ import annotations

import numpy as np
import trimesh
from scipy.optimize import minimize
from scipy.spatial import cKDTree

_SEED = 7


def _mirror(pts: np.ndarray, point: np.ndarray, normal: np.ndarray) -> np.ndarray:
    d = (pts - point) @ normal
    return pts - 2.0 * np.outer(d, normal)


def _score(sample: np.ndarray, tree: cKDTree, point: np.ndarray,
           normal: np.ndarray) -> float:
    """Média da distância dos pontos espelhados à malha (mm).

    Média (não mediana/percentil): uma protuberância que quebra a simetria
    contribui proporcionalmente à sua área, então até um detalhe local
    assimétrico puxa o score para cima."""
    mirrored = _mirror(sample, point, normal)
    dist, _ = tree.query(mirrored, workers=-1)
    return float(dist.mean())


def find_symmetry_plane(mesh: trimesh.Trimesh, max_score_mm: float | None = None
                        ) -> dict:
    rng = np.random.default_rng(_SEED)
    v = mesh.vertices.astype(float)
    if len(v) > 60000:
        v = v[rng.choice(len(v), 60000, replace=False)]
    tree = cKDTree(v)
    sample = v[rng.choice(len(v), min(3000, len(v)), replace=False)]
    centroid = v.mean(axis=0)
    extent = float(np.linalg.norm(v.max(axis=0) - v.min(axis=0)))

    # candidatos: eixos principais
    cov = np.cov((v - centroid).T)
    _, eigvec = np.linalg.eigh(cov)
    candidates = [eigvec[:, i] for i in range(3)]

    best = None
    for n0 in candidates:
        s = _score(sample, tree, centroid, n0)
        if best is None or s < best[0]:
            best = (s, n0)
    s0, n0 = best

    # refino: normal em ângulos esféricos + offset ao longo da normal
    theta0 = float(np.arccos(np.clip(n0[2], -1, 1)))
    phi0 = float(np.arctan2(n0[1], n0[0]))

    def unpack(x):
        theta, phi, off = x
        n = np.array([np.sin(theta) * np.cos(phi),
                      np.sin(theta) * np.sin(phi),
                      np.cos(theta)])
        return centroid + n * off, n

    def objective(x):
        p, n = unpack(x)
        return _score(sample, tree, p, n)

    res = minimize(objective, [theta0, phi0, 0.0], method="Nelder-Mead",
                   options={"maxiter": 120, "xatol": 1e-4, "fatol": 1e-4})
    point, normal = unpack(res.x)
    score = float(res.fun)

    limit = max_score_mm if max_score_mm is not None else 0.01 * extent
    out = {
        "point": [round(float(x), 4) for x in point],
        "normal": [round(float(x), 6) for x in normal],
        "score_mm": round(score, 4),
        "limite_mm": round(float(limit), 4),
        "simetrica": bool(score <= limit),
    }
    if not out["simetrica"]:
        out["aviso"] = (f"desvio de simetria {score:.3f} mm acima do limite "
                        f"{limit:.3f} mm — a peça pode não ter simetria real")
    return out
