"""Roll/Unroll — planificação da malha (chapa conformada, tubos, cones).

- Cilindro/cone: desenvolvimento EXATO da superfície, com costura (seam)
  configurável — o desvio radial do scan vira relevo (z) na planificação.
- Superfície genérica: parametrização conforme LSCM (aproximada), com
  relatório de distorção de área — dupla curvatura NÃO desenvolve sem
  esticar, e o relatório diz quanto.

Saída: malha planificada (STL) + contorno 2D como entidades (linha/arco/
polilinha) prontas para virar sketch de corte no SolidWorks.
"""

from __future__ import annotations

import numpy as np
import trimesh

from . import fit as fit_mod
from .region import region_vertex_mask
from .section import _entity_from_piece, _merge_collinear, _split_polyline


def _submesh(mesh: trimesh.Trimesh, region: dict | None) -> trimesh.Trimesh:
    if not region:
        return mesh
    vmask = region_vertex_mask(mesh, region)
    fmask = vmask[mesh.faces].all(axis=1)
    if not fmask.any():
        raise ValueError("região sem faces inteiras")
    sub = mesh.submesh([np.flatnonzero(fmask)], append=True)
    return sub


def _boundary_entities(flat: trimesh.Trimesh, tol_mm: float) -> list[dict]:
    """Contorno externo da malha planificada como entidades 2D."""
    try:
        outline = flat.outline()
    except BaseException:
        return []
    loops = []
    for entity in getattr(outline, "entities", []):
        pts = outline.vertices[entity.points][:, :2]
        if len(pts) < 3:
            continue
        closed = bool(np.linalg.norm(pts[0] - pts[-1]) < 1e-6)
        ents = _merge_collinear(
            [_entity_from_piece(p, tol_mm) for p in _split_polyline(pts)],
            closed)
        loops.append({"closed": closed, "entities": ents})
    return loops


def _stats(mesh3d: trimesh.Trimesh, flat: trimesh.Trimesh,
           kept_faces: np.ndarray | None = None) -> dict:
    a3 = mesh3d.area_faces
    if kept_faces is not None:
        a3 = a3[kept_faces]
    a2 = flat.area_faces
    if len(a2) != len(a3):  # faces degeneradas removidas no processo
        n = min(len(a2), len(a3))
        a2, a3 = a2[:n], a3[:n]
    ok = a3 > 1e-12
    ratio = np.ones_like(a3)
    ratio[ok] = a2[ok] / a3[ok]
    return {
        "area_3d_mm2": round(float(a3.sum()), 2),
        "area_plana_mm2": round(float(a2.sum()), 2),
        "distorcao_media_pct": round(float(np.abs(ratio[ok] - 1).mean() * 100), 3),
        "distorcao_max_pct": round(float(np.abs(ratio[ok] - 1).max() * 100), 3),
    }


# ------------------------------------------------------------ desenvolvíveis

def unroll_cylinder(mesh: trimesh.Trimesh, params: dict,
                    seam_deg: float = 0.0) -> trimesh.Trimesh:
    p0 = np.asarray(params["point"], float)
    a = np.asarray(params["axis"], float)
    a = a / np.linalg.norm(a)
    r = float(params["radius"])
    u = np.cross(a, [1.0, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1.0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(a, u)
    d = mesh.vertices - p0
    x, y, h = d @ u, d @ v, d @ a
    theta = np.arctan2(y, x)
    seam = np.radians(seam_deg)
    theta = np.mod(theta - seam, 2 * np.pi)  # costura em theta=0
    r_pt = np.hypot(x, y)
    flat_v = np.column_stack([r * theta, h, r_pt - r])  # desvio vira relevo z
    flat = trimesh.Trimesh(vertices=flat_v, faces=mesh.faces.copy(),
                           process=False)
    # remove triângulos que cruzam a costura (largura ~ 2*pi*r)
    keep = np.ptp(flat_v[flat.faces][:, :, 0], axis=1) < np.pi * r
    flat.update_faces(keep)
    flat.remove_unreferenced_vertices()
    return flat, keep


def unroll_cone(mesh: trimesh.Trimesh, params: dict,
                seam_deg: float = 0.0) -> trimesh.Trimesh:
    apex = np.asarray(params["apex"], float)
    a = np.asarray(params["axis"], float)
    a = a / np.linalg.norm(a)
    half = np.radians(float(params["half_angle_deg"]))
    u = np.cross(a, [1.0, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1.0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(a, u)
    d = mesh.vertices - apex
    x, y = d @ u, d @ v
    theta = np.mod(np.arctan2(y, x) - np.radians(seam_deg), 2 * np.pi)
    s = np.linalg.norm(d, axis=1)                      # distância inclinada
    phi = theta * np.sin(half)                         # ângulo desenvolvido
    dev = (np.hypot(x, y) - (d @ a) * np.tan(half)) * np.cos(half)
    flat_v = np.column_stack([s * np.cos(phi), s * np.sin(phi), dev])
    flat = trimesh.Trimesh(vertices=flat_v, faces=mesh.faces.copy(),
                           process=False)
    keep = np.ptp(theta[flat.faces], axis=1) < np.pi
    flat.update_faces(keep)
    flat.remove_unreferenced_vertices()
    return flat, keep


# ------------------------------------------------------------------- LSCM

def unroll_lscm(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Parametrização conforme por mínimos quadrados (LSCM) para superfície
    aberta genérica. Aproximada: minimiza distorção de ângulo; a de área é
    reportada em stats."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import lsqr

    vtx = mesh.vertices
    faces = mesh.faces
    n = len(vtx)

    # fixa os 2 vértices mais distantes entre si (aproximado pelos extremos
    # da caixa) para remover translação/rotação/escala
    ext = vtx @ (vtx.max(axis=0) - vtx.min(axis=0))
    pin = [int(ext.argmin()), int(ext.argmax())]
    pin_uv = {pin[0]: (0.0, 0.0),
              pin[1]: (float(np.linalg.norm(vtx[pin[1]] - vtx[pin[0]])), 0.0)}

    rows, cols, vals = [], [], []
    rhs = []
    row = 0
    for f in faces:
        p = vtx[f]
        e1 = p[1] - p[0]
        e2 = p[2] - p[0]
        nrm = np.cross(e1, e2)
        area2 = np.linalg.norm(nrm)
        if area2 < 1e-12:
            continue
        # base local do triângulo
        bx = e1 / np.linalg.norm(e1)
        bz = nrm / area2
        by = np.cross(bz, bx)
        w = [np.array([0.0, 0.0]),
             np.array([float(e1 @ bx), 0.0]),
             np.array([float(e2 @ bx), float(e2 @ by)])]
        # gradientes conformes (formulação clássica LSCM por triângulo)
        wr = [w[2] - w[1], w[0] - w[2], w[1] - w[0]]
        s = 1.0 / np.sqrt(area2)
        for comp in range(2):  # parte real e imaginária da energia conforme
            rr = 0.0
            for k in range(3):
                vi = int(f[k])
                wx, wy = wr[k] * s
                # coeficientes de (u_i, v_i)
                cu, cv = (wx, -wy) if comp == 0 else (wy, wx)
                if vi in pin_uv:
                    rr -= cu * pin_uv[vi][0] + cv * pin_uv[vi][1]
                else:
                    rows += [row, row]
                    cols += [2 * vi, 2 * vi + 1]
                    vals += [cu, cv]
            rhs.append(rr)
            row += 1

    a = coo_matrix((vals, (rows, cols)), shape=(row, 2 * n)).tocsr()
    sol = lsqr(a, np.asarray(rhs), atol=1e-10, btol=1e-10, iter_lim=4000)[0]
    uv = sol.reshape(-1, 2).copy()
    for vi, (pu, pv) in pin_uv.items():
        uv[vi] = (pu, pv)

    # reescala global para preservar a ÁREA total (LSCM preserva ângulos)
    flat0 = trimesh.Trimesh(vertices=np.column_stack([uv, np.zeros(n)]),
                            faces=faces.copy(), process=False)
    if flat0.area > 1e-12:
        uv *= np.sqrt(mesh.area / flat0.area)

    # alinha o eixo principal com X (os pinos deixam a peça rotacionada)
    centered = uv - uv.mean(axis=0)
    _, vecs = np.linalg.eigh(np.cov(centered.T))
    rot = vecs[:, ::-1]  # maior variância -> X
    if np.linalg.det(rot) < 0:
        rot[:, 1] = -rot[:, 1]
    uv = centered @ rot
    uv -= uv.min(axis=0)  # canto em (0,0)

    flat = trimesh.Trimesh(vertices=np.column_stack([uv, np.zeros(n)]),
                           faces=faces.copy(), process=False)
    return flat


# -------------------------------------------------------------------- API

def unroll(mesh: trimesh.Trimesh, region: dict | None = None,
           method: str = "auto", seam_deg: float = 0.0,
           tol_mm: float = 0.15, out_path: str | None = None) -> dict:
    """method: auto | cylinder | cone | lscm."""
    sub = _submesh(mesh, region)
    used = method
    params = None
    if method in ("auto", "cylinder", "cone"):
        kinds = {"auto": "auto", "cylinder": "cylinder", "cone": "cone"}[method]
        try:
            params = fit_mod.fit_primitive(sub, kinds if kinds != "auto" else "auto",
                                           tolerance_mm=tol_mm * 2)
        except ValueError:
            params = None
        kept = None
        if params and params["kind"] == "cylinder" and params["inlier_fraction"] > 0.5:
            flat, kept = unroll_cylinder(sub, params, seam_deg)
            used = "cylinder"
        elif params and params["kind"] == "cone" and params["inlier_fraction"] > 0.5:
            flat, kept = unroll_cone(sub, params, seam_deg)
            used = "cone"
        elif method == "auto":
            flat = unroll_lscm(sub)
            used = "lscm"
            params = None
        else:
            raise ValueError(
                f"a região não ajusta bem num {method} — use method='lscm'")
    elif method == "lscm":
        flat = unroll_lscm(sub)
        params = None
        kept = None
    else:
        raise ValueError(f"method desconhecido: {method}")

    out = {"metodo": used, **_stats(sub, flat, kept)}
    if params:
        out["primitiva"] = params
    if used == "lscm" and out["distorcao_max_pct"] > 5.0:
        out["aviso"] = ("dupla curvatura: distorção de até "
                        f"{out['distorcao_max_pct']}% — a chapa real estica; "
                        "use como referência, não como corte final")
    if out_path:
        flat.export(out_path)
        out["malha_plana"] = out_path
    out["contorno"] = _boundary_entities(flat, tol_mm)
    lo = flat.vertices.min(axis=0)
    hi = flat.vertices.max(axis=0)
    out["dimensoes_mm"] = [round(float(hi[0] - lo[0]), 3),
                           round(float(hi[1] - lo[1]), 3)]
    return out
