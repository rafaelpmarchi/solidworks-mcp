"""Mapa de desvio scan × referência renderizado em PNG.

Referência pode ser outra malha (ex.: o CAD reconstruído exportado como STL
pelo SolidWorks) ou uma primitiva ajustada. Vértices sem correspondência
dentro de max_dist ficam CINZA — lacuna é informação, não interpolamos.
"""

from __future__ import annotations

import numpy as np
import trimesh

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def deviation_to_mesh(scan: trimesh.Trimesh, reference: trimesh.Trimesh,
                      max_dist_mm: float = 5.0) -> np.ndarray:
    """Distância assinada de cada vértice do scan à superfície de referência.

    NaN onde a correspondência mais próxima passa de max_dist_mm.
    """
    closest, dist, tri_id = trimesh.proximity.closest_point(reference, scan.vertices)
    normals = reference.face_normals[tri_id]
    signed = ((scan.vertices - closest) * normals).sum(axis=1)
    signed[dist > max_dist_mm] = np.nan
    return signed


def deviation_to_primitive(scan: trimesh.Trimesh, primitive: dict,
                           region: dict | None = None,
                           max_dist_mm: float = 5.0) -> np.ndarray:
    """Distância assinada dos vértices a uma primitiva ajustada (dict do fit)."""
    from . import fit as _fit
    from .region import region_vertex_mask

    pts = scan.vertices.astype(float)
    kind = primitive["kind"]
    if kind == "plane":
        d = _fit._plane_dist(pts, np.asarray(primitive["point"]),
                             np.asarray(primitive["normal"]))
    elif kind == "sphere":
        d = _fit._sphere_dist(pts, np.asarray(primitive["center"]),
                              float(primitive["radius"]))
    elif kind == "cylinder":
        d = _fit._cyl_dist(pts, np.asarray(primitive["point"]),
                           np.asarray(primitive["axis"]), float(primitive["radius"]))
    elif kind == "cone":
        d = _fit._cone_dist(pts, np.asarray(primitive["apex"]),
                            np.asarray(primitive["axis"]),
                            np.radians(float(primitive["half_angle_deg"])))
    else:
        raise ValueError(f"primitiva desconhecida: {kind}")
    d = d.copy()
    d[np.abs(d) > max_dist_mm] = np.nan
    if region:
        mask = region_vertex_mask(scan, region)
        d[~mask] = np.nan
    return d


def deviation_stats(signed: np.ndarray) -> dict:
    valid = signed[~np.isnan(signed)]
    n = len(signed)
    if len(valid) == 0:
        return {"cobertura": 0.0, "aviso": "nenhum ponto dentro de max_dist"}
    return {
        "cobertura": round(float(len(valid) / n), 4),
        "sem_dado": int(n - len(valid)),
        "media_mm": round(float(valid.mean()), 4),
        "rms_mm": round(float(np.sqrt((valid ** 2).mean())), 4),
        "min_mm": round(float(valid.min()), 4),
        "max_mm": round(float(valid.max()), 4),
        "p95_abs_mm": round(float(np.percentile(np.abs(valid), 95)), 4),
    }


def _pass_fail_colors(face_vals: np.ndarray, tol: float) -> np.ndarray:
    """Colorização Passa/Falha (spec do Mesh2Surface): verde dentro de ±tol,
    gradiente amarelo->vermelho (acima) / ciano->azul (abaixo) até 5*tol,
    escuro além disso, cinza sem dado."""
    colors = np.empty((len(face_vals), 4))
    colors[:] = (0.55, 0.55, 0.55, 1.0)  # sem dado
    ok = np.isfinite(face_vals)
    v = face_vals[ok]
    c = np.empty((len(v), 4))
    c[:] = (0.1, 0.65, 0.1, 1.0)  # dentro da tolerância
    t = np.clip((np.abs(v) - tol) / (4.0 * tol), 0.0, 1.0)  # 0 em tol, 1 em 5tol
    acima = v > tol
    abaixo = v < -tol
    # acima: amarelo -> vermelho -> vermelho escuro
    c[acima] = np.column_stack([
        np.full(acima.sum(), 0.85) - 0.35 * t[acima],
        0.75 * (1.0 - t[acima]),
        np.zeros(acima.sum()),
        np.ones(acima.sum())])
    # abaixo: ciano -> azul -> azul escuro
    c[abaixo] = np.column_stack([
        np.zeros(abaixo.sum()),
        0.75 * (1.0 - t[abaixo]),
        np.full(abaixo.sum(), 0.85) - 0.35 * t[abaixo],
        np.ones(abaixo.sum())])
    colors[ok] = c
    return colors


def render_deviation(scan: trimesh.Trimesh, signed: np.ndarray, png_path: str,
                     scale_mm: float | None = None, render_faces: int = 40000,
                     pass_fail_tol_mm: float | None = None) -> dict:
    """Renderiza 4 vistas do scan colorido pelo desvio. Retorna stats.

    pass_fail_tol_mm ativa o modo Passa/Falha (verde = dentro da tolerância)."""
    from . import mesh_io

    stats = deviation_stats(signed)
    mesh = scan
    values = signed
    if len(mesh.faces) > render_faces:
        # decima só para renderizar; reamostra o desvio por vértice mais próximo
        small = mesh_io.decimate(mesh, render_faces)
        from scipy.spatial import cKDTree
        tree = cKDTree(mesh.vertices)
        _, idx = tree.query(small.vertices, workers=-1)
        values = signed[idx]
        mesh = small

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # face toda-NaN -> NaN
        face_vals = np.nanmean(values[mesh.faces], axis=1)
    if scale_mm is None:
        finite = face_vals[np.isfinite(face_vals)]
        scale_mm = float(np.percentile(np.abs(finite), 98)) if len(finite) else 1.0
        scale_mm = max(scale_mm, 0.01)
    norm = TwoSlopeNorm(vmin=-scale_mm, vcenter=0.0, vmax=scale_mm)
    cmap = plt.get_cmap("RdYlBu_r")  # vermelho = scan acima do CAD, azul = abaixo
    if pass_fail_tol_mm is not None:
        colors = _pass_fail_colors(face_vals, float(pass_fail_tol_mm))
    else:
        colors = cmap(norm(np.nan_to_num(face_vals, nan=0.0)))
        colors[~np.isfinite(face_vals)] = (0.55, 0.55, 0.55, 1.0)  # sem dado

    views = [("isométrica", 30, -60), ("topo", 90, -90),
             ("frente", 0, -90), ("lateral", 0, 0)]
    fig = plt.figure(figsize=(14, 11), dpi=100)
    tris = mesh.vertices[mesh.faces]
    span = mesh.extents.max()
    center = mesh.bounds.mean(axis=0)
    for i, (name, elev, azim) in enumerate(views, 1):
        ax = fig.add_subplot(2, 2, i, projection="3d")
        pc = Poly3DCollection(tris, facecolors=colors, edgecolors="none")
        ax.add_collection3d(pc)
        for setter, c in ((ax.set_xlim, 0), (ax.set_ylim, 1), (ax.set_zlim, 2)):
            setter(center[c] - span / 2, center[c] + span / 2)
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(name)
        ax.set_axis_off()
        try:
            ax.set_box_aspect((1, 1, 1))
        except Exception:
            pass
    if pass_fail_tol_mm is None:
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        cbar = fig.colorbar(sm, ax=fig.axes, shrink=0.6, pad=0.02)
        cbar.set_label("desvio scan − referência (mm) · cinza = sem dado")
    else:
        valid = signed[np.isfinite(signed)]
        dentro = float((np.abs(valid) <= pass_fail_tol_mm).mean()) if len(valid) else 0.0
        stats["dentro_tolerancia"] = round(dentro, 4)
        fig.text(0.5, 0.02,
                 f"PASSA/FALHA ±{pass_fail_tol_mm} mm · verde = dentro "
                 f"({dentro * 100:.1f}%) · quente = acima · frio = abaixo · "
                 "cinza = sem dado", ha="center")
    fig.suptitle(
        f"cobertura {stats.get('cobertura', 0) * 100:.1f}%  ·  "
        f"rms {stats.get('rms_mm', '?')} mm  ·  "
        f"p95 |desvio| {stats.get('p95_abs_mm', '?')} mm")
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)
    stats["png"] = png_path
    stats["escala_mm"] = round(scale_mm, 3)
    return stats
