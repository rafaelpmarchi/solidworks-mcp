"""Carga, inspeção, decimação e suavização de malhas (STL/OBJ/PLY)."""

from __future__ import annotations

import numpy as np
import trimesh


def load_mesh(path: str) -> trimesh.Trimesh:
    """Carrega STL/OBJ/PLY como Trimesh único (concatena cenas multi-geometria)."""
    obj = trimesh.load(path, force="mesh", process=False)
    if not isinstance(obj, trimesh.Trimesh):
        raise ValueError(f"arquivo não contém malha triangular: {path}")
    if len(obj.faces) == 0:
        raise ValueError(f"malha vazia: {path}")
    # remove degenerados sem mexer na topologia útil
    obj.remove_infinite_values()
    obj.merge_vertices()  # STL vem com vértices duplicados por face
    obj.update_faces(obj.nondegenerate_faces())
    obj.remove_unreferenced_vertices()
    return obj


def mesh_info(mesh: trimesh.Trimesh) -> dict:
    """Estatísticas da malha em mm."""
    bounds = mesh.bounds  # (2, 3)
    extents = mesh.extents
    info = {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "bounds_min_mm": [round(float(v), 4) for v in bounds[0]],
        "bounds_max_mm": [round(float(v), 4) for v in bounds[1]],
        "extents_mm": [round(float(v), 4) for v in extents],
        "watertight": bool(mesh.is_watertight),
        "euler_number": int(mesh.euler_number),
        "area_mm2": round(float(mesh.area), 2),
    }
    if mesh.is_watertight:
        info["volume_mm3"] = round(float(mesh.volume), 2)
    # heurística de unidade: peça automotiva escaneada raramente tem < 5 de extensão
    max_ext = float(max(extents))
    if max_ext < 5.0:
        info["aviso_unidade"] = (
            f"extensão máxima {max_ext:.3f} — se o scan estiver em metros, "
            "aplique scale=1000"
        )
    return info


def _cluster_decimate(mesh: trimesh.Trimesh, pitch: float) -> trimesh.Trimesh:
    """Decimação por agrupamento em grade: vértices na mesma célula viram um só
    (média). Faces que colapsam somem. Determinística, robusta a ruído de scan."""
    keys = np.floor(mesh.vertices / pitch).astype(np.int64)
    _, cluster_of, counts = np.unique(keys, axis=0, return_inverse=True,
                                      return_counts=True)
    # representante = média dos vértices da célula
    reps = np.zeros((len(counts), 3))
    np.add.at(reps, cluster_of, mesh.vertices)
    reps /= counts[:, None]
    faces = cluster_of[mesh.faces]
    ok = ((faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2])
          & (faces[:, 0] != faces[:, 2]))
    faces = np.unique(np.sort(faces[ok], axis=1), axis=0)
    out = trimesh.Trimesh(vertices=reps, faces=faces, process=False)
    out.remove_unreferenced_vertices()
    return out


def _decimate_open3d(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh | None:
    """Decimação quadric do Open3D (backend WSL/Linux). None se indisponível."""
    try:
        import open3d as o3d
    except ImportError:
        return None
    m = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(mesh.vertices.astype(np.float64)),
        o3d.utility.Vector3iVector(mesh.faces.astype(np.int32)))
    m = m.simplify_quadric_decimation(target_number_of_triangles=int(target_faces))
    out = trimesh.Trimesh(vertices=np.asarray(m.vertices),
                          faces=np.asarray(m.triangles), process=False)
    if len(out.faces) < 4:
        return None
    out.update_faces(out.nondegenerate_faces())
    out.remove_unreferenced_vertices()
    return out


def decimate(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Reduz a malha para ~target_faces triângulos.

    Com Open3D disponível (backend Linux/WSL) usa quadric decimation, que
    preserva arestas vivas. Sem ele (venv Windows py3.13: sem wheel, e
    fast-simplification empaca em ~30% nesta build), cai no agrupamento em
    grade com ajuste do passo.
    """
    if target_faces >= len(mesh.faces):
        return mesh
    via_o3d = _decimate_open3d(mesh, target_faces)
    if via_o3d is not None:
        return via_o3d
    # passo inicial: ~2 triângulos por célula de superfície
    pitch = float(np.sqrt(2.0 * mesh.area / target_faces))
    out = mesh
    for _ in range(8):
        cand = _cluster_decimate(mesh, pitch)
        if len(cand.faces) < 4:
            pitch *= 0.7
            continue
        out = cand
        ratio = len(cand.faces) / target_faces
        if 0.8 <= ratio <= 1.2:
            break
        pitch *= np.sqrt(ratio) ** 0.9  # ajusta o passo na direção do alvo
    return out


def smooth(mesh: trimesh.Trimesh, iterations: int = 10, lamb: float = 0.5) -> trimesh.Trimesh:
    """Suavização laplaciana (filtro de Taubin evita encolhimento)."""
    out = mesh.copy()
    trimesh.smoothing.filter_taubin(out, lamb=lamb, nu=-lamb - 0.03, iterations=int(iterations))
    return out


def save_mesh(mesh: trimesh.Trimesh, path: str) -> None:
    mesh.export(path)
