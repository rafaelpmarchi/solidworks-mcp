"""Ajuste de primitivas (plano, esfera, cilindro, cone) por RANSAC + refino.

Fluxo: RANSAC dá uma hipótese robusta a outliers (tampas, rebarba, ruído de
scan); o refino por mínimos quadrados roda SÓ nos inliers da hipótese.
Distâncias em mm, ângulos em graus.
"""

from __future__ import annotations

import numpy as np
import trimesh
from scipy.optimize import least_squares

from .region import region_vertex_mask

_RNG_SEED = 7  # determinístico: mesmo scan -> mesmo resultado


def _unit(v):
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------- distâncias

def _plane_dist(pts, point, normal):
    return (pts - np.asarray(point)) @ np.asarray(normal)


def _sphere_dist(pts, center, radius):
    return np.linalg.norm(pts - np.asarray(center), axis=1) - radius


def _cyl_dist(pts, point, axis, radius):
    d = pts - np.asarray(point)
    axis = np.asarray(axis)
    proj = d - np.outer(d @ axis, axis)
    return np.linalg.norm(proj, axis=1) - radius


def _cone_dist(pts, apex, axis, half_angle_rad):
    d = pts - np.asarray(apex)
    axis = np.asarray(axis)
    h = d @ axis
    r = np.linalg.norm(d - np.outer(h, axis), axis=1)
    return r * np.cos(half_angle_rad) - h * np.sin(half_angle_rad)


def _dist(kind, pts, params):
    if kind == "plane":
        return _plane_dist(pts, params["point"], params["normal"])
    if kind == "sphere":
        return _sphere_dist(pts, params["center"], params["radius"])
    if kind == "cylinder":
        return _cyl_dist(pts, params["point"], params["axis"], params["radius"])
    if kind == "cone":
        return _cone_dist(pts, params["apex"], params["axis"],
                          np.radians(params["half_angle_deg"]))
    raise ValueError(kind)


# ---------------------------------------------------------------- hipóteses

def _circle_3pts(p2):
    """Círculo por 3 pontos 2D. Retorna (center, r) ou None se colineares."""
    a = np.column_stack([p2 * 2, np.ones(3)])
    b = (p2 ** 2).sum(axis=1)
    try:
        sol = np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        return None
    c = sol[:2]
    r2 = sol[2] + (c ** 2).sum()
    if r2 <= 0:
        return None
    return c, float(np.sqrt(r2))


def _hyp_plane(pts, normals, rng):
    i = rng.choice(len(pts), 3, replace=False)
    p0, p1, p2 = pts[i]
    n = np.cross(p1 - p0, p2 - p0)
    norm = np.linalg.norm(n)
    if norm < 1e-9:
        return None
    return {"point": p0, "normal": n / norm}


def _hyp_sphere(pts, normals, rng):
    i = rng.choice(len(pts), 4, replace=False)
    p = pts[i]
    a = np.hstack([p * 2, np.ones((4, 1))])
    b = (p ** 2).sum(axis=1)
    try:
        sol = np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        return None
    center = sol[:3]
    r2 = sol[3] + (center ** 2).sum()
    if r2 <= 0:
        return None
    return {"center": center, "radius": float(np.sqrt(r2))}


def _hyp_cylinder(pts, normals, rng):
    """Eixo pelo produto vetorial de 2 normais; círculo por 3 pontos projetados."""
    i = rng.choice(len(pts), 2, replace=False)
    n0, n1 = normals[i]
    axis = np.cross(n0, n1)
    norm = np.linalg.norm(axis)
    if norm < 1e-3:
        return None
    axis /= norm
    # base 2D no plano perpendicular ao eixo
    u = _unit(np.cross(axis, n0))
    v = np.cross(axis, u)
    j = rng.choice(len(pts), 3, replace=False)
    p2 = np.column_stack([pts[j] @ u, pts[j] @ v])
    circ = _circle_3pts(p2)
    if circ is None:
        return None
    c2, r = circ
    if not (0.05 < r < 1e4):
        return None
    center = c2[0] * u + c2[1] * v  # ponto do eixo (componente axial livre)
    return {"point": center, "axis": axis, "radius": r}


def _hyp_cone(pts, normals, rng):
    i = rng.choice(len(pts), 3, replace=False)
    p, n = pts[i], normals[i]
    try:
        apex = np.linalg.solve(n, (n * p).sum(axis=1))
    except np.linalg.LinAlgError:
        return None
    d = p - apex
    norms = np.linalg.norm(d, axis=1)
    if (norms < 1e-9).any():
        return None
    axis = (d / norms[:, None]).mean(axis=0)
    an = np.linalg.norm(axis)
    if an < 1e-6:
        return None
    axis /= an
    half = float(np.mean([np.arccos(np.clip(abs(_unit(dd) @ axis), 0, 1))
                          for dd in d]))
    if not (0.02 < half < 1.4):
        return None
    return {"apex": apex, "axis": axis, "half_angle_deg": float(np.degrees(half))}


_HYPS = {"plane": _hyp_plane, "sphere": _hyp_sphere,
         "cylinder": _hyp_cylinder, "cone": _hyp_cone}


def _ransac(pts, normals, kind, tol, iters=800, max_radius=None):
    rng = np.random.default_rng(_RNG_SEED)
    best, best_count = None, 0
    make = _HYPS[kind]
    for _ in range(iters):
        hyp = make(pts, normals, rng)
        if hyp is None:
            continue
        if max_radius is not None and hyp.get("radius", 0) > max_radius:
            continue  # raio maior que a peça = plano disfarçado
        count = int((np.abs(_dist(kind, pts, hyp)) <= tol).sum())
        if count > best_count:
            best, best_count = hyp, count
    if best is None or best_count < 10:
        raise ValueError(f"RANSAC não encontrou {kind} com inliers suficientes "
                         f"(melhor: {best_count})")
    return best


# ---------------------------------------------------------------- refino

def _refine(pts, kind, hyp):
    """Refina params nos pontos dados (já filtrados para inliers)."""
    if kind == "plane":
        centroid = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - centroid, full_matrices=False)
        n = vt[2] if vt[2] @ np.asarray(hyp["normal"]) > 0 else -vt[2]
        return {"point": centroid, "normal": n}

    if kind == "sphere":
        def res(x):
            return _sphere_dist(pts, x[:3], abs(x[3]))
        x0 = np.concatenate([hyp["center"], [hyp["radius"]]])
        sol = least_squares(res, x0, method="lm", max_nfev=200)
        return {"center": sol.x[:3], "radius": float(abs(sol.x[3]))}

    if kind == "cylinder":
        def res(x):
            return _cyl_dist(pts, x[:3], _unit(x[3:6]), abs(x[6]))
        x0 = np.concatenate([hyp["point"], hyp["axis"], [hyp["radius"]]])
        sol = least_squares(res, x0, max_nfev=400)
        a = _unit(sol.x[3:6])
        p = sol.x[:3]
        h = (pts - p) @ a
        p = p + a * float(h.mean())  # ancora no centro da nuvem
        if a[2] < 0 or (abs(a[2]) < 1e-6 and (a[0] < 0 or (a[0] == 0 and a[1] < 0))):
            a = -a  # orientação canônica
        return {"point": p, "axis": a, "radius": float(abs(sol.x[6])),
                "height": float(h.max() - h.min())}

    if kind == "cone":
        half0 = np.radians(hyp["half_angle_deg"])
        def res(x):
            return _cone_dist(pts, x[:3], _unit(x[3:6]), np.clip(x[6], 0.02, 1.4))
        x0 = np.concatenate([hyp["apex"], hyp["axis"], [half0]])
        sol = least_squares(res, x0, max_nfev=400)
        a = _unit(sol.x[3:6])
        half = float(np.clip(sol.x[6], 0.02, 1.4))
        return {"apex": sol.x[:3], "axis": a,
                "half_angle_deg": float(np.degrees(half))}

    raise ValueError(kind)


# ------------------------------------------------- fitting com restrição

def _fit_constrained(pts, kind, axis, tol):
    """Best fit com direção travada (botões Vertical/Horizontal do M2S).

    plane: normal fixa em `axis` -> só o offset é ajustado (RANSAC 1D).
    cylinder: eixo fixo em `axis` -> círculo 2D na projeção perpendicular.
    """
    axis = _unit(np.asarray(axis, float))
    rng = np.random.default_rng(_RNG_SEED)
    if kind == "plane":
        d = pts @ axis
        best_off, best_count = None, 0
        for off in rng.choice(d, min(200, len(d)), replace=False):
            count = int((np.abs(d - off) <= tol).sum())
            if count > best_count:
                best_off, best_count = off, count
        if best_off is None or best_count < 10:
            raise ValueError("plano restrito: inliers insuficientes")
        inl = np.abs(d - best_off) <= tol
        off = float(d[inl].mean())
        return {"point": axis * off, "normal": axis}

    if kind == "cylinder":
        u = _unit(np.cross(axis, [1.0, 0, 0])
                  if abs(axis[0]) < 0.9 else np.cross(axis, [0, 1.0, 0]))
        v = np.cross(axis, u)
        p2 = np.column_stack([pts @ u, pts @ v])
        best, best_count = None, 0
        for _ in range(400):
            j = rng.choice(len(p2), 3, replace=False)
            circ = _circle_3pts(p2[j])
            if circ is None:
                continue
            c2, r = circ
            dist = np.abs(np.linalg.norm(p2 - c2, axis=1) - r)
            count = int((dist <= tol).sum())
            if count > best_count:
                best, best_count = (c2, r), count
        if best is None or best_count < 10:
            raise ValueError("cilindro restrito: inliers insuficientes")
        c2, r = best
        inl = np.abs(np.linalg.norm(p2 - c2, axis=1) - r) <= tol
        def res(x):
            return np.linalg.norm(p2[inl] - x[:2], axis=1) - abs(x[2])
        sol = least_squares(res, np.concatenate([c2, [r]]), method="lm",
                            max_nfev=200)
        c2, r = sol.x[:2], float(abs(sol.x[2]))
        center = c2[0] * u + c2[1] * v
        h = (pts - center) @ axis
        return {"point": center + axis * float(h.mean()), "axis": axis,
                "radius": r, "height": float(h.max() - h.min())}

    raise ValueError(f"restrição de eixo não suportada para {kind}")


# ---------------------------------------------------------------- API

def fit_primitive(mesh: trimesh.Trimesh, kind: str, region: dict | None = None,
                  tolerance_mm: float = 0.15,
                  constraint_axis: list | None = None) -> dict:
    """Ajusta uma primitiva na região. kind: plane|sphere|cylinder|cone|auto.

    constraint_axis trava a direção (normal do plano / eixo do cilindro)."""
    mask = region_vertex_mask(mesh, region)
    pts = mesh.vertices[mask].astype(float)
    normals = np.asarray(mesh.vertex_normals)[mask]
    if len(pts) > 20000:  # RANSAC não precisa de tudo
        rng = np.random.default_rng(_RNG_SEED)
        sub = rng.choice(len(pts), 20000, replace=False)
        pts, normals = pts[sub], normals[sub]

    max_radius = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))  # diagonal

    if constraint_axis is not None:
        if kind not in ("plane", "cylinder"):
            raise ValueError("constraint_axis só vale para plane ou cylinder")
        params = _fit_constrained(pts, kind, constraint_axis, tolerance_mm)
        dist = _dist(kind, pts, params)
        inl = np.abs(dist) <= tolerance_mm
        out = {"kind": kind, "constrained": True,
               "inlier_fraction": round(float(inl.mean()), 4),
               "rms_mm": round(float(np.sqrt((dist[inl] ** 2).mean())), 4)
               if inl.any() else None,
               "points_used": int(len(pts))}
        for key, val in params.items():
            out[key] = ([round(float(x), 4) for x in val]
                        if isinstance(val, np.ndarray) else round(float(val), 4))
        return out

    kinds = ["plane", "cylinder", "sphere", "cone"] if kind == "auto" else [kind]
    results = []
    for k in kinds:
        try:
            hyp = _ransac(pts, normals, k, tolerance_mm, max_radius=max_radius)
            params = hyp
            # refina 2x: inliers -> refino -> inliers novos -> refino
            for _ in range(2):
                inl = np.abs(_dist(k, pts, params)) <= tolerance_mm
                if inl.sum() < 10:
                    raise ValueError("inliers insuficientes no refino")
                params = _refine(pts[inl], k, params)
            if params.get("radius", 0) > max_radius:
                raise ValueError("refino divergiu para raio gigante")
            dist = _dist(k, pts, params)
            inl = np.abs(dist) <= tolerance_mm
            frac = float(inl.mean())
            rms = float(np.sqrt((dist[inl] ** 2).mean())) if inl.any() else 1e9
            results.append((k, params, frac, rms))
        except (ValueError, np.linalg.LinAlgError):
            continue
    if not results:
        raise ValueError(f"nenhuma primitiva ajustou na região (tol {tolerance_mm} mm)")

    # melhor = maior fração de inliers; empate decide pelo menor rms.
    # plano ganha bônus leve: cilindro de raio gigante "explica" plano também.
    def score(r):
        k, _, frac, rms = r
        return (-(frac + (0.02 if k == "plane" else 0.0)), rms)
    results.sort(key=score)
    k, params, frac, rms = results[0]

    out = {"kind": k, "inlier_fraction": round(frac, 4),
           "rms_mm": round(rms, 4), "points_used": int(len(pts))}
    for key, val in params.items():
        if isinstance(val, np.ndarray):
            out[key] = [round(float(x), 4) for x in val]
        else:
            out[key] = round(float(val), 4)
    return out
