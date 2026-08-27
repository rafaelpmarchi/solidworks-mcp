"""Região freeform da malha -> superfície B-spline -> STEP (Fase 3).

Para paredes/nervuras de fundição onde primitiva não serve. A região é
parametrizada projetando no plano médio (SVD), reamostrada em grade regular
e ajustada com GeomAPI_PointsToBSplineSurface (OpenCascade via build123d).
Semi-automático por definição: funciona bem em patch "tipo altura sobre um
plano" (height-field); região que dobra sobre si mesma precisa ser dividida.
"""

from __future__ import annotations

import numpy as np
import trimesh
from scipy.interpolate import griddata

from .region import region_vertex_mask


def _extract_ctrl(surf) -> dict:
    """Grade de controle + nós da B-spline (para o editor do viewer)."""
    nu, nv = surf.NbUPoles(), surf.NbVPoles()
    poles = [[[round(float(c), 4) for c in
               (surf.Pole(i + 1, j + 1).X(), surf.Pole(i + 1, j + 1).Y(),
                surf.Pole(i + 1, j + 1).Z())]
              for j in range(nv)] for i in range(nu)]
    return {
        "poles": poles,
        "udeg": surf.UDegree(), "vdeg": surf.VDegree(),
        "uknots": [round(float(surf.UKnot(i + 1)), 8)
                   for i in range(surf.NbUKnots())],
        "vknots": [round(float(surf.VKnot(i + 1)), 8)
                   for i in range(surf.NbVKnots())],
        "umults": [surf.UMultiplicity(i + 1) for i in range(surf.NbUKnots())],
        "vmults": [surf.VMultiplicity(i + 1) for i in range(surf.NbVKnots())],
    }


def build_step_from_ctrl(ctrl: dict, out_step: str) -> dict:
    """Reconstrói a B-spline a partir da grade de controle (possivelmente
    editada no viewer) e grava o STEP."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.Geom import Geom_BSplineSurface
    from OCP.gp import gp_Pnt
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

    poles = ctrl["poles"]
    nu, nv = len(poles), len(poles[0])
    arr = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            x, y, z = poles[i][j]
            arr.SetValue(i + 1, j + 1, gp_Pnt(float(x), float(y), float(z)))

    def _reals(vals):
        a = TColStd_Array1OfReal(1, len(vals))
        for k, v in enumerate(vals):
            a.SetValue(k + 1, float(v))
        return a

    def _ints(vals):
        a = TColStd_Array1OfInteger(1, len(vals))
        for k, v in enumerate(vals):
            a.SetValue(k + 1, int(v))
        return a

    surf = Geom_BSplineSurface(
        arr, _reals(ctrl["uknots"]), _reals(ctrl["vknots"]),
        _ints(ctrl["umults"]), _ints(ctrl["vmults"]),
        int(ctrl["udeg"]), int(ctrl["vdeg"]), False, False)
    face = BRepBuilderAPI_MakeFace(surf, 1e-6).Face()
    writer = STEPControl_Writer()
    writer.Transfer(face, STEPControl_AsIs)
    if writer.Write(out_step) != IFSelect_RetDone:
        raise RuntimeError(f"falha ao escrever STEP em {out_step}")
    return {"step": out_step, "poles": [nu, nv]}


def fit_freeform(mesh: trimesh.Trimesh, region: dict | None, out_step: str,
                 grid: tuple[int, int] = (40, 40), tol_mm: float = 0.05,
                 max_degree: int = 8, extend_mm: float = 0.0) -> dict:
    """extend_mm > 0 estende a superfície além da região (como o 'Fit Surface'
    do QuickSurface) para ela sobrar da peça e servir de ferramenta de recorte
    (trim) no SolidWorks. A extensão continua os valores da borda (vizinho
    mais próximo) e é suavizada pelo ajuste B-spline."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.GeomAbs import GeomAbs_C2
    from OCP.GeomAPI import (GeomAPI_PointsToBSplineSurface,
                             GeomAPI_ProjectPointOnSurf)
    from OCP.gp import gp_Pnt
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TColgp import TColgp_Array2OfPnt

    mask = region_vertex_mask(mesh, region)
    pts = mesh.vertices[mask].astype(float)
    if len(pts) < 100:
        raise ValueError(f"região com só {len(pts)} vértices — freeform precisa "
                         "de pelo menos 100")

    # plano médio -> parametrização (u, v, w)
    centroid = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - centroid, full_matrices=False)
    u_dir, v_dir, w_dir = vt[0], vt[1], vt[2]
    local = (pts - centroid) @ np.vstack([u_dir, v_dir, w_dir]).T
    w_span = float(local[:, 2].max() - local[:, 2].min())
    uv_span = float(min(np.ptp(local[:, 0]), np.ptp(local[:, 1])))
    if w_span > 0.8 * uv_span:
        raise ValueError(
            "região dobra demais sobre o plano médio (não é height-field) — "
            "divida em patches menores")

    # grade regular em (u,v); células sem dado preenchidas por vizinho e avisadas
    nu, nv = int(grid[0]), int(grid[1])
    margin = 1e-6
    ext = max(0.0, float(extend_mm))
    u_lo, u_hi = local[:, 0].min(), local[:, 0].max()
    v_lo, v_hi = local[:, 1].min(), local[:, 1].max()
    us = np.linspace(u_lo - ext + margin, u_hi + ext - margin, nu)
    vs = np.linspace(v_lo - ext + margin, v_hi + ext - margin, nv)
    U, V = np.meshgrid(us, vs, indexing="ij")
    W_lin = griddata(local[:, :2], local[:, 2], (U, V), method="linear")
    holes = np.isnan(W_lin)
    # cobertura conta só o miolo (dentro da caixa dos dados) — a extensão é
    # intencional, não lacuna de scan
    core = ((U >= u_lo) & (U <= u_hi) & (V >= v_lo) & (V <= v_hi))
    coverage = float(1.0 - holes[core].mean()) if core.any() else 0.0
    if holes.any():
        W_near = griddata(local[:, :2], local[:, 2], (U, V), method="nearest")
        W_lin[holes] = W_near[holes]

    # grade -> mundo -> OCC
    world = (centroid[None, None, :]
             + U[..., None] * u_dir + V[..., None] * v_dir
             + W_lin[..., None] * w_dir)
    arr = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            p = world[i, j]
            arr.SetValue(i + 1, j + 1, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))

    fitter = GeomAPI_PointsToBSplineSurface()
    fitter.Init(arr, 3, int(max_degree), GeomAbs_C2, float(tol_mm))
    surf = fitter.Surface()

    # desvio do ajuste contra os pontos reais da região (amostra)
    rng = np.random.default_rng(7)
    sample = pts[rng.choice(len(pts), min(400, len(pts)), replace=False)]
    devs = []
    for p in sample:
        proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*[float(x) for x in p]), surf)
        if proj.NbPoints():
            devs.append(proj.LowerDistance())
    devs = np.asarray(devs)

    face = BRepBuilderAPI_MakeFace(surf, 1e-6).Face()
    writer = STEPControl_Writer()
    writer.Transfer(face, STEPControl_AsIs)
    if writer.Write(out_step) != IFSelect_RetDone:
        raise RuntimeError(f"falha ao escrever STEP em {out_step}")

    out = {
        "step": out_step,
        "ctrl": _extract_ctrl(surf),
        "grade": [nu, nv],
        "extensao_mm": round(ext, 2),
        "span_uv_mm": [round(float(us[-1] - us[0]), 2),
                       round(float(vs[-1] - vs[0]), 2)],
        "graus": [surf.UDegree(), surf.VDegree()],
        "polos": [surf.NbUPoles(), surf.NbVPoles()],
        "cobertura_grade": round(coverage, 4),
        "pontos_regiao": int(len(pts)),
        "desvio_rms_mm": round(float(np.sqrt((devs ** 2).mean())), 4),
        "desvio_p95_mm": round(float(np.percentile(devs, 95)), 4),
        "desvio_max_mm": round(float(devs.max()), 4),
    }
    if coverage < 0.9:
        out["aviso"] = (f"só {coverage * 100:.0f}% da grade tinha dado de scan — "
                        "bordas preenchidas por vizinho; confira o desvio")
    return out
