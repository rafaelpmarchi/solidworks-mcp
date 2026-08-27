"""Ponte CLI: JSON entra por arquivo/stdin, JSON sai por stdout.

Uso:  python -m swengine <comando> [--json caminho.json]
Sem --json, lê os argumentos JSON do stdin. A malha NUNCA passa pelo JSON —
só caminhos de arquivo. Saída: {"ok": true, ...} ou {"ok": false, "erro": "..."}.

Comandos:
  info      {"mesh": path}
  decimate  {"mesh": path, "out": path, "target_faces": int}
  smooth    {"mesh": path, "out": path, "iterations"?: int}
  flip      {"mesh": path, "out": path}
  export    {"mesh": path, "out": path}   (formato pela extensão)
  align     {"mesh": path, "out": path, "mode": "pca|bbox|plane_to_xy|matrix",
             "region"?: {...}, "matrix"?: [16 floats]}
  segment   {"mesh": path, "labels_out": path(.npy), "radius_mm"?,
             "smooth_threshold_deg"?, "min_region_vertices"?}
  fit       {"mesh": path, "kind": "plane|sphere|cylinder|cone|auto",
             "region"?: {...}, "tolerance_mm"?}
  section   {"mesh": path, "axis": "x|y|z"|[i,j,k], "positions": [mm...],
             "tol_mm"?, "angle_break_deg"?}
  radial    {"mesh": path, "axis_point": [xyz], "axis_dir": [ijk],
             "count": int, "tol_mm"?}
  symmetry  {"mesh": path, "max_score_mm"?: float}
  viewerpack {"mesh": path, "out": path(.bin), "target_faces"?, "labels"?: path}
  savemask  {"mesh": path, "viewer_bin": path, "indices": [...], "out": path(.npy)}
  freeform_step {"ctrl": {poles/knots/mults/degs}, "out_step": path}
  unroll    {"mesh": path, "region"?, "method"?: auto|cylinder|cone|lscm,
             "seam_deg"?, "tol_mm"?, "out"?: path da malha plana}
  freeform  {"mesh": path, "out_step": path, "region"?: {...},
             "grid"?: [nu,nv], "tol_mm"?, "max_degree"?}
  deviation {"mesh": path, "png": path, "reference"?: path,
             "primitive"?: {fit dict}, "region"?: {...},
             "max_dist_mm"?, "scale_mm"?}
"""

from __future__ import annotations

import json
import sys
import traceback

import numpy as np


def _run(command: str, a: dict) -> dict:
    from . import align as align_mod
    from . import deviation as dev_mod
    from . import fit as fit_mod
    from . import mesh_io
    from . import section as sec_mod
    from . import segment as seg_mod

    if command == "info":
        mesh = mesh_io.load_mesh(a["mesh"])
        return mesh_io.mesh_info(mesh)

    if command == "decimate":
        mesh = mesh_io.load_mesh(a["mesh"])
        out = mesh_io.decimate(mesh, int(a["target_faces"]))
        mesh_io.save_mesh(out, a["out"])
        return {"out": a["out"], **mesh_io.mesh_info(out)}

    if command == "smooth":
        mesh = mesh_io.load_mesh(a["mesh"])
        out = mesh_io.smooth(mesh, int(a.get("iterations", 10)))
        mesh_io.save_mesh(out, a["out"])
        return {"out": a["out"], **mesh_io.mesh_info(out)}

    if command == "flip":
        mesh = mesh_io.load_mesh(a["mesh"])
        mesh.invert()
        mesh_io.save_mesh(mesh, a["out"])
        return {"out": a["out"], **mesh_io.mesh_info(mesh)}

    if command == "export":
        mesh = mesh_io.load_mesh(a["mesh"])
        mesh_io.save_mesh(mesh, a["out"])  # formato pela extensão
        return {"out": a["out"], "faces": int(len(mesh.faces))}

    if command == "align":
        mesh = mesh_io.load_mesh(a["mesh"])
        out, matrix = align_mod.align(mesh, a["mode"], a.get("region"),
                                      a.get("matrix"))
        mesh_io.save_mesh(out, a["out"])
        return {"out": a["out"], "matrix": np.round(matrix, 8).ravel().tolist(),
                **mesh_io.mesh_info(out)}

    if command == "segment":
        mesh = mesh_io.load_mesh(a["mesh"])
        labels, stats = seg_mod.segment(
            mesh,
            radius_mm=float(a.get("radius_mm", 3.0)),
            smooth_threshold_deg=float(a.get("smooth_threshold_deg", 8.0)),
            min_region_vertices=int(a.get("min_region_vertices", 50)),
        )
        np.save(a["labels_out"], labels)
        return {"labels_out": a["labels_out"], "regioes_lisas": stats,
                "vertices_rugosos": int((labels == 0).sum())}

    if command == "fit":
        mesh = mesh_io.load_mesh(a["mesh"])
        return fit_mod.fit_primitive(mesh, a["kind"], a.get("region"),
                                     float(a.get("tolerance_mm", 0.15)),
                                     a.get("constraint_axis"))

    if command == "section":
        mesh = mesh_io.load_mesh(a["mesh"])
        return {"sections": sec_mod.section(
            mesh, a["axis"], [float(p) for p in a["positions"]],
            tol_mm=float(a.get("tol_mm", 0.1)),
            angle_break_deg=float(a.get("angle_break_deg", 25.0)))}

    if command == "radial":
        mesh = mesh_io.load_mesh(a["mesh"])
        return {"sections": sec_mod.radial_sections(
            mesh, a["axis_point"], a["axis_dir"], int(a["count"]),
            tol_mm=float(a.get("tol_mm", 0.1)))}

    if command == "viewerpack":
        from . import viewer as viewer_mod
        mesh = mesh_io.load_mesh(a["mesh"])
        labels = None
        if a.get("labels"):
            labels = np.load(a["labels"])
        return viewer_mod.pack(mesh, a["out"],
                               int(a.get("target_faces", 80000)), labels)

    if command == "savemask":
        from . import viewer as viewer_mod
        mesh = mesh_io.load_mesh(a["mesh"])
        return viewer_mod.save_mask(mesh, a["viewer_bin"], a["indices"],
                                    a["out"])

    if command == "freeform_step":
        from . import freeform as ff_mod
        return ff_mod.build_step_from_ctrl(a["ctrl"], a["out_step"])

    if command == "unroll":
        from . import unroll as unroll_mod
        mesh = mesh_io.load_mesh(a["mesh"])
        return unroll_mod.unroll(
            mesh, a.get("region"), a.get("method", "auto"),
            float(a.get("seam_deg", 0.0)), float(a.get("tol_mm", 0.15)),
            a.get("out"))

    if command == "symmetry":
        from . import symmetry as sym_mod
        mesh = mesh_io.load_mesh(a["mesh"])
        return sym_mod.find_symmetry_plane(mesh, a.get("max_score_mm"))

    if command == "freeform":
        from . import freeform as ff_mod
        mesh = mesh_io.load_mesh(a["mesh"])
        return ff_mod.fit_freeform(
            mesh, a.get("region"), a["out_step"],
            grid=tuple(a.get("grid", [40, 40])),
            tol_mm=float(a.get("tol_mm", 0.05)),
            max_degree=int(a.get("max_degree", 8)),
            extend_mm=float(a.get("extend_mm", 0.0)))

    if command == "deviation":
        mesh = mesh_io.load_mesh(a["mesh"])
        max_dist = float(a.get("max_dist_mm", 5.0))
        if a.get("reference"):
            ref = mesh_io.load_mesh(a["reference"])
            signed = dev_mod.deviation_to_mesh(mesh, ref, max_dist)
        elif a.get("primitive"):
            signed = dev_mod.deviation_to_primitive(
                mesh, a["primitive"], a.get("region"), max_dist)
        else:
            raise ValueError("deviation exige 'reference' (malha) ou 'primitive'")
        scale = a.get("scale_mm")
        pf = a.get("pass_fail_tol_mm")
        return dev_mod.render_deviation(
            mesh, signed, a["png"], None if scale is None else float(scale),
            pass_fail_tol_mm=None if pf is None else float(pf))

    raise ValueError(f"comando desconhecido: {command}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(json.dumps({"ok": False, "erro": "uso: swengine <comando> [--json f]"}))
        return 2
    command = argv[0]
    try:
        if len(argv) >= 3 and argv[1] == "--json":
            with open(argv[2], encoding="utf-8") as f:
                args = json.load(f)
        else:
            raw = sys.stdin.read().strip()
            args = json.loads(raw) if raw else {}
        result = _run(command, args)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001 — fronteira do processo
        print(json.dumps({"ok": False, "erro": f"{type(e).__name__}: {e}",
                          "trace": traceback.format_exc(limit=5)},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
