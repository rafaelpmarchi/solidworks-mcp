"""Alinhamento da malha ao sistema de coordenadas de trabalho.

Modos:
- pca: eixos principais de inércia -> XYZ, centroide -> origem
- bbox: caixa envolvente mínima orientada -> XYZ, canto mínimo -> origem
- plane_to_xy: ajusta um plano numa região e leva esse plano para Z=0 (normal +Z)
- matrix: aplica uma matriz 4x4 explícita
"""

from __future__ import annotations

import numpy as np
import trimesh

from .region import region_vertex_mask


def _basis_to_matrix(origin: np.ndarray, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Matriz 4x4 que leva o frame (origin, x, y, z) para o frame canônico."""
    rot = np.vstack([x, y, z])  # linhas = novos eixos
    m = np.eye(4)
    m[:3, :3] = rot
    m[:3, 3] = -rot @ origin
    return m


def align_pca(mesh: trimesh.Trimesh) -> np.ndarray:
    v = mesh.vertices
    centroid = v.mean(axis=0)
    cov = np.cov((v - centroid).T)
    eigval, eigvec = np.linalg.eigh(cov)
    # maior variância -> X, menor -> Z (peça deitada na "mesa")
    order = np.argsort(eigval)[::-1]
    x, y, z = eigvec[:, order[0]], eigvec[:, order[1]], eigvec[:, order[2]]
    z = np.cross(x, y)  # garante destro
    z /= np.linalg.norm(z)
    return _basis_to_matrix(centroid, x, y, z)


def align_bbox(mesh: trimesh.Trimesh) -> np.ndarray:
    # to_origin leva a malha para a caixa mínima orientada centrada na origem
    to_origin, extents = trimesh.bounds.oriented_bounds(mesh)
    # desloca para o canto mínimo ficar em (0,0,0)
    shift = np.eye(4)
    shift[:3, 3] = np.asarray(extents) / 2.0
    return shift @ to_origin


def align_plane_to_xy(mesh: trimesh.Trimesh, region: dict | None = None) -> np.ndarray:
    """Ajusta plano (mínimos quadrados) nos vértices da região e leva-o a Z=0."""
    mask = region_vertex_mask(mesh, region)
    pts = mesh.vertices[mask]
    if len(pts) < 3:
        raise ValueError("região com menos de 3 vértices para ajustar plano")
    centroid = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - centroid, full_matrices=False)
    normal = vt[2]
    # normal aponta para o lado com mais malha "acima" -> invertemos para +Z externo
    above = np.dot(mesh.vertices - centroid, normal)
    if above.mean() < 0:
        normal = -normal
    z = normal / np.linalg.norm(normal)
    x = np.cross([0.0, 1.0, 0.0], z)
    if np.linalg.norm(x) < 1e-6:
        x = np.cross([1.0, 0.0, 0.0], z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return _basis_to_matrix(centroid, x, y, z)


def apply_alignment(mesh: trimesh.Trimesh, matrix: np.ndarray) -> trimesh.Trimesh:
    out = mesh.copy()
    out.apply_transform(matrix)
    return out


def align(mesh: trimesh.Trimesh, mode: str, region: dict | None = None,
          matrix: list | None = None) -> tuple[trimesh.Trimesh, np.ndarray]:
    if mode == "pca":
        m = align_pca(mesh)
    elif mode == "bbox":
        m = align_bbox(mesh)
    elif mode == "plane_to_xy":
        m = align_plane_to_xy(mesh, region)
    elif mode == "matrix":
        if matrix is None:
            raise ValueError("mode=matrix exige matrix 4x4")
        m = np.asarray(matrix, dtype=float).reshape(4, 4)
    else:
        raise ValueError(f"modo de alinhamento desconhecido: {mode}")
    return apply_alignment(mesh, m), m
