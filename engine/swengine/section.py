"""Seções transversais da malha viradas em entidades 2D (linha/arco/polilinha).

Cada seção corta a malha com um plano, encadeia os segmentos em polilinhas,
divide por quebras de direção e ajusta linha ou arco por trecho. A saída são
entidades no plano da seção (coordenadas 2D u,v em mm) prontas para virar
sketch no SolidWorks.
"""

from __future__ import annotations

import numpy as np
import trimesh

_AXES = {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0]), "z": np.array([0, 0, 1.0])}


def _plane_frame(normal: np.ndarray, origin: np.ndarray):
    """Base (u, v) ortonormal no plano da seção."""
    n = normal / np.linalg.norm(normal)
    u = np.cross([0.0, 0.0, 1.0], n)
    if np.linalg.norm(u) < 1e-6:
        u = np.cross([0.0, 1.0, 0.0], n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v


def _to_2d(pts3, origin, u, v):
    d = pts3 - origin
    return np.column_stack([d @ u, d @ v])


def _fit_circle(pts2):
    """Ajuste algébrico de círculo (Kåsa). Retorna (center, radius, rms)."""
    a = np.column_stack([pts2 * 2, np.ones(len(pts2))])
    b = (pts2 ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    center = sol[:2]
    r = float(np.sqrt(sol[2] + (center ** 2).sum()))
    rms = float(np.sqrt(((np.linalg.norm(pts2 - center, axis=1) - r) ** 2).mean()))
    return center, r, rms


def _fit_line(pts2):
    centroid = pts2.mean(axis=0)
    _, _, vt = np.linalg.svd(pts2 - centroid, full_matrices=False)
    direction = vt[0]
    t = (pts2 - centroid) @ direction
    rms = float(np.sqrt((((pts2 - centroid) @ vt[1]) ** 2).mean()))
    p1 = centroid + direction * t.min()
    p2 = centroid + direction * t.max()
    return p1, p2, rms


def _split_polyline(pts2, angle_break_deg=25.0, min_pts=4):
    """Divide a polilinha onde a direção muda bruscamente (cantos)."""
    if len(pts2) < 2 * min_pts:
        return [pts2]
    seg = np.diff(pts2, axis=0)
    norm = np.linalg.norm(seg, axis=1)
    ok = norm > 1e-9
    dirs = np.zeros_like(seg)
    dirs[ok] = seg[ok] / norm[ok, None]
    cos = np.clip((dirs[:-1] * dirs[1:]).sum(axis=1), -1, 1)
    turn = np.degrees(np.arccos(cos))
    breaks = np.flatnonzero(turn > angle_break_deg) + 1
    pieces, start = [], 0
    for b in breaks:
        if b - start >= min_pts:
            pieces.append(pts2[start:b + 1])
            start = b
    if len(pts2) - start >= min_pts:
        pieces.append(pts2[start:])
    return pieces or [pts2]


def _entity_from_piece(pts2, tol_mm):
    """Classifica um trecho como line, arc ou polyline."""
    p1, p2, line_rms = _fit_line(pts2)
    if line_rms <= tol_mm:
        return {"type": "line", "p1": p1.tolist(), "p2": p2.tolist(),
                "rms_mm": round(line_rms, 4)}
    if len(pts2) >= 5:
        center, r, circ_rms = _fit_circle(pts2)
        if circ_rms <= tol_mm and r < 10000:
            return {"type": "arc",
                    "center": center.tolist(), "radius": round(r, 4),
                    "p1": pts2[0].tolist(), "p2": pts2[-1].tolist(),
                    "mid": pts2[len(pts2) // 2].tolist(),
                    "rms_mm": round(circ_rms, 4)}
    step = max(1, len(pts2) // 100)  # spline: no máximo ~100 pontos
    return {"type": "polyline", "points": pts2[::step].tolist(),
            "rms_mm": None}


def _merge_collinear(entities: list[dict], closed: bool,
                     join_tol_mm: float = 0.5) -> list[dict]:
    """Funde linhas colineares consecutivas (o início do loop pode cair no
    meio de uma aresta e parti-la em duas). Em loop fechado, funde também a
    última com a primeira."""
    def try_merge(a, b):
        if a["type"] != "line" or b["type"] != "line":
            return None
        da = np.asarray(a["p2"], float) - np.asarray(a["p1"], float)
        db = np.asarray(b["p2"], float) - np.asarray(b["p1"], float)
        na, nb = np.linalg.norm(da), np.linalg.norm(db)
        if na < 1e-9 or nb < 1e-9:
            return None
        # emenda com folga: os extremos vêm de fits independentes
        contiguas = np.linalg.norm(
            np.asarray(a["p2"], float) - np.asarray(b["p1"], float)) < join_tol_mm
        if contiguas and float((da / na) @ (db / nb)) > 0.9995:
            return {"type": "line", "p1": a["p1"], "p2": b["p2"],
                    "rms_mm": max(a.get("rms_mm") or 0, b.get("rms_mm") or 0)}
        return None

    out: list[dict] = []
    for e in entities:
        merged = try_merge(out[-1], e) if out else None
        if merged is not None:
            out[-1] = merged
        else:
            out.append(e)
    if closed and len(out) >= 2:
        merged = try_merge(out[-1], out[0])
        if merged is not None:
            out[0] = merged
            out.pop()
    return out


def recognize_loop(entities: list[dict], closed: bool,
                   tol_mm: float = 0.1) -> dict | None:
    """Reconhece forma de alto nível num contorno fechado (estilo QuickSurface
    'Complex 2D shapes recognition'): circle, rectangle, slot ou polígono
    regular. None se não casar com nada — fica o desenho entidade a entidade.
    """
    if not closed or not entities:
        return None
    tipos = sorted(e["type"] for e in entities)
    lines = [e for e in entities if e["type"] == "line"]
    arcs = [e for e in entities if e["type"] == "arc"]
    if any(e["type"] == "polyline" for e in entities):
        return None

    def comprimento(e):
        return float(np.linalg.norm(np.asarray(e["p2"]) - np.asarray(e["p1"])))

    def direcao(e):
        d = np.asarray(e["p2"], float) - np.asarray(e["p1"], float)
        n = np.linalg.norm(d)
        return d / n if n > 1e-9 else d

    # círculo: um arco só fechando o loop, ou arcos concêntricos de mesmo raio
    if not lines and arcs:
        centers = np.array([a["center"] for a in arcs])
        radii = np.array([a["radius"] for a in arcs])
        if (np.ptp(radii) <= 2 * tol_mm
                and np.linalg.norm(np.ptp(centers, axis=0)) <= 4 * tol_mm):
            c = centers.mean(axis=0)
            return {"shape": "circle",
                    "center": [round(float(x), 4) for x in c],
                    "radius": round(float(radii.mean()), 4)}

    # slot: 2 linhas paralelas iguais + 2 arcos com raio ~ metade da largura
    if len(lines) == 2 and len(arcs) == 2:
        d0, d1 = direcao(lines[0]), direcao(lines[1])
        paralelas = abs(abs(float(d0 @ d1)) - 1.0) < 0.02
        iguais = abs(comprimento(lines[0]) - comprimento(lines[1])) <= 4 * tol_mm
        r0, r1 = arcs[0]["radius"], arcs[1]["radius"]
        if paralelas and iguais and abs(r0 - r1) <= 2 * tol_mm:
            c0 = np.asarray(arcs[0]["center"], float)
            c1 = np.asarray(arcs[1]["center"], float)
            width = float(r0 + r1)
            return {"shape": "slot",
                    "c1": [round(float(x), 4) for x in c0],
                    "c2": [round(float(x), 4) for x in c1],
                    "width": round(width, 4)}

    # só linhas: retângulo ou polígono regular
    if lines and not arcs and len(lines) >= 3:
        n = len(lines)
        comp = np.array([comprimento(e) for e in lines])
        dirs = [direcao(e) for e in lines]
        if n == 4:
            perp01 = abs(float(dirs[0] @ dirs[1])) < 0.03
            par02 = abs(abs(float(dirs[0] @ dirs[2])) - 1.0) < 0.02
            par13 = abs(abs(float(dirs[1] @ dirs[3])) - 1.0) < 0.02
            if perp01 and par02 and par13:
                pts = np.array([e["p1"] for e in lines] + [e["p2"] for e in lines])
                lo, hi = pts.min(axis=0), pts.max(axis=0)
                eixo_alinhado = bool(
                    abs(abs(float(dirs[0][0])) - 1.0) < 0.02
                    or abs(abs(float(dirs[0][1])) - 1.0) < 0.02)
                return {"shape": "rectangle",
                        "min": [round(float(x), 4) for x in lo],
                        "max": [round(float(x), 4) for x in hi],
                        "axis_aligned": eixo_alinhado}
        if n >= 5 and np.ptp(comp) <= 4 * tol_mm:
            # polígono regular: lados iguais e vértices equidistantes do centro
            pts = np.array([e["p1"] for e in lines])
            centro = pts.mean(axis=0)
            raios = np.linalg.norm(pts - centro, axis=1)
            if np.ptp(raios) <= 4 * tol_mm:
                return {"shape": "polygon", "sides": n,
                        "center": [round(float(x), 4) for x in centro],
                        "circumradius": round(float(raios.mean()), 4)}
    return None


def section(mesh: trimesh.Trimesh, axis: str | list, positions: list[float],
            tol_mm: float = 0.1, angle_break_deg: float = 25.0) -> list[dict]:
    """Seções perpendiculares a `axis` nas cotas `positions` (mm).

    axis: "x"|"y"|"z" ou vetor [i,j,k]. Retorna uma entrada por seção com
    entidades 2D no frame (origin, u, v) do plano.
    """
    normal = _AXES[axis.lower()] if isinstance(axis, str) else np.asarray(axis, float)
    normal = normal / np.linalg.norm(normal)
    out = []
    for pos in positions:
        origin = normal * float(pos)
        sec = mesh.section(plane_origin=origin, plane_normal=normal)
        entry = {"position_mm": float(pos),
                 "plane": {"origin": origin.tolist(), "normal": normal.tolist()},
                 "loops": []}
        if sec is None:
            entry["aviso"] = "plano não intercepta a malha"
            out.append(entry)
            continue
        u, v = _plane_frame(normal, origin)
        entry["plane"]["u"] = u.tolist()
        entry["plane"]["v"] = v.tolist()
        for line in sec.discrete:  # cada loop/curva como sequência de pontos 3D
            pts2 = _to_2d(np.asarray(line), origin, u, v)
            closed = bool(np.linalg.norm(pts2[0] - pts2[-1]) < 1e-6)
            entities = _merge_collinear(
                [_entity_from_piece(p, tol_mm)
                 for p in _split_polyline(pts2, angle_break_deg)], closed)
            loop = {"closed": closed, "entities": entities}
            shape = recognize_loop(entities, closed, tol_mm)
            if shape:
                loop["shape"] = shape
            entry["loops"].append(loop)
        out.append(entry)
    return out


def radial_sections(mesh: trimesh.Trimesh, axis_point: list, axis_dir: list,
                    count: int, tol_mm: float = 0.1) -> list[dict]:
    """`count` seções passando pelo eixo dado, espaçadas igualmente em ângulo."""
    p0 = np.asarray(axis_point, float)
    a = np.asarray(axis_dir, float)
    a /= np.linalg.norm(a)
    ref = np.cross(a, [0.0, 0.0, 1.0])
    if np.linalg.norm(ref) < 1e-6:
        ref = np.cross(a, [0.0, 1.0, 0.0])
    ref /= np.linalg.norm(ref)
    out = []
    for i in range(count):
        ang = np.pi * i / count  # 0..180° (plano corta os dois lados)
        normal = ref * np.cos(ang) + np.cross(a, ref) * np.sin(ang)
        sec = mesh.section(plane_origin=p0, plane_normal=normal)
        entry = {"angle_deg": round(float(np.degrees(ang)), 2),
                 "plane": {"origin": p0.tolist(), "normal": normal.tolist()},
                 "loops": []}
        if sec is None:
            entry["aviso"] = "plano não intercepta a malha"
            out.append(entry)
            continue
        u, v = _plane_frame(normal, p0)
        entry["plane"]["u"] = u.tolist()
        entry["plane"]["v"] = v.tolist()
        for line in sec.discrete:
            pts2 = _to_2d(np.asarray(line), p0, u, v)
            closed = bool(np.linalg.norm(pts2[0] - pts2[-1]) < 1e-6)
            entities = _merge_collinear(
                [_entity_from_piece(p, tol_mm) for p in _split_polyline(pts2)],
                closed)
            loop = {"closed": closed, "entities": entities}
            shape = recognize_loop(entities, closed, tol_mm)
            if shape:
                loop["shape"] = shape
            entry["loops"].append(loop)
        out.append(entry)
    return out
