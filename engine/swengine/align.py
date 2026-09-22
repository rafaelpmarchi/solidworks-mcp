"""Alinhamento da malha ao sistema de coordenadas de trabalho.

Modos:
- pca: eixos principais de inércia -> XYZ, centroide -> origem
- bbox: caixa envolvente mínima orientada -> XYZ, canto mínimo -> origem
- plane_to_xy: ajusta um plano numa região e leva esse plano para Z=0 (normal +Z)
- matrix: aplica uma matriz 4x4 explícita
- to_reference: registra o scan num STL de referência (CAD) por PCA + ICP
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


# ------------------------------------------------------ registro no CAD (ICP)

def _pca_frame(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(centroide, matriz 3x3 com os eixos principais em colunas, destra)."""
    c = pts.mean(axis=0)
    _, vec = np.linalg.eigh(np.cov((pts - c).T))
    vec = vec[:, ::-1]  # maior variância primeiro
    if np.linalg.det(vec) < 0:
        vec[:, 2] *= -1
    return c, vec


def _icp(src: np.ndarray, ref: np.ndarray, ref_normals: np.ndarray | None,
         init: np.ndarray, max_dist_mm: float, iters: int) -> np.ndarray:
    """ICP ponto-a-plano (Open3D) com fallback ponto-a-ponto (trimesh)."""
    try:
        import open3d as o3d
        s = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(src))
        r = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(ref))
        if ref_normals is not None:
            r.normals = o3d.utility.Vector3dVector(ref_normals)
            est = o3d.pipelines.registration.TransformationEstimationPointToPlane()
        else:
            est = o3d.pipelines.registration.TransformationEstimationPointToPoint()
        res = o3d.pipelines.registration.registration_icp(
            s, r, max_dist_mm, init, est,
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=iters))
        return np.asarray(res.transformation)
    except ImportError:
        matrix, _, _ = trimesh.registration.icp(
            src, ref, initial=init, threshold=1e-5, max_iterations=iters,
            scale=False, reflection=False)
        return np.asarray(matrix)


def _score(src: np.ndarray, ref_tree, matrix: np.ndarray) -> float:
    """Mediana da distância ao ponto amostrado mais próximo (só para ordenar
    candidatos — a amostragem da referência limita a precisão absoluta)."""
    d, _ = ref_tree.query(trimesh.transform_points(src, matrix), workers=-1)
    return float(np.median(d))


def _surface_stats(src: np.ndarray, reference: trimesh.Trimesh,
                   matrix: np.ndarray, inlier_mm: float,
                   max_pts: int = 20000) -> dict:
    """Distância REAL à superfície da referência (não à amostra de pontos)."""
    if len(src) > max_pts:
        src = src[np.random.default_rng(1).choice(len(src), max_pts,
                                                  replace=False)]
    p = trimesh.transform_points(src, matrix)
    _, d, _ = trimesh.proximity.closest_point(reference, p)
    return {"rms_mm": float(np.sqrt(np.mean(d ** 2))),
            "mediana_mm": float(np.median(d)),
            "p95_mm": float(np.percentile(d, 95)),
            "inlier_fraction": float(np.mean(d <= inlier_mm))}


def align_to_reference(mesh: trimesh.Trimesh, reference: trimesh.Trimesh,
                       region: dict | None = None, samples: int = 30000,
                       seed_rotations: int = 12, inlier_mm: float = 0.5,
                       initial: list | None = None) -> tuple[np.ndarray, dict]:
    """Registra o scan no CAD (best-fit rígido): devolve a matriz 4x4 que leva
    a malha ao sistema de coordenadas da referência, mais estatísticas.

    Busca grosseira: frames PCA dos dois + as 4 rotações próprias de sinal +
    `seed_rotations` giros em torno do eixo de menor variância (peça de
    revolução tem furos que fixam esse giro). Cada candidato faz um ICP curto;
    o melhor faz o ICP fino. `region` restringe os pontos do SCAN usados
    (ex.: só faces usinadas) — a referência é sempre a peça inteira.
    `initial` (4x4) pula a busca grosseira e só refina."""
    from scipy.spatial import cKDTree

    mask = region_vertex_mask(mesh, region)
    src_all = mesh.vertices[mask]
    if len(src_all) < 100:
        raise ValueError("região com menos de 100 vértices para registrar")
    rng = np.random.default_rng(0)
    src = src_all[rng.choice(len(src_all), min(samples, len(src_all)),
                             replace=False)]
    ref_normals = None
    if len(reference.faces):
        ref, fid = trimesh.sample.sample_surface(reference, samples, seed=0)
        ref = np.asarray(ref)
        ref_normals = reference.face_normals[fid]
    else:
        ref = reference.vertices
    tree = cKDTree(ref)

    if initial is not None:
        candidates = [np.asarray(initial, float).reshape(4, 4)]
    else:
        cs, es = _pca_frame(src)
        cr, er = _pca_frame(ref)
        flips = [np.diag([1, 1, 1]), np.diag([1, -1, -1]),
                 np.diag([-1, 1, -1]), np.diag([-1, -1, 1])]
        candidates = []
        for k in range(max(1, seed_rotations)):
            ang = 2 * np.pi * k / max(1, seed_rotations)
            rz = trimesh.transformations.rotation_matrix(ang, [0, 0, 1])[:3, :3]
            for f in flips:
                rot = er @ rz @ f @ es.T  # scan -> canônico -> giro -> CAD
                m = np.eye(4)
                m[:3, :3] = rot
                m[:3, 3] = cr - rot @ cs
                candidates.append(m)

    diag = float(np.linalg.norm(reference.extents))
    coarse_dist = max(2.0, 0.05 * diag)
    scored = []
    for m in candidates:
        m2 = _icp(src, ref, ref_normals, m, coarse_dist, 20)
        scored.append((_score(src, tree, m2), m2))
    scored.sort(key=lambda t: t[0])
    best = scored[0][1]
    for dist in (coarse_dist, 1.0, 0.3):
        best = _icp(src, ref, ref_normals, best, dist, 60)

    stats = _surface_stats(src_all, reference, best, inlier_mm)
    stats["antes"] = _surface_stats(src_all, reference, np.eye(4), inlier_mm)
    stats["candidatos"] = len(candidates)
    stats["pontos_scan"] = int(len(src_all))
    stats["inlier_mm"] = inlier_mm
    return best, stats
