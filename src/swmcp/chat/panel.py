"""Rotas do painel Scan→Sólido (estilo QuickSurface) do taskpane.

Executam as operações DIRETO (sem LLM): botão apertado -> motor/SolidWorks.
Todas retornam dict; erro vira {"error": "..."} com status 400.
O estado da malha ativa é compartilhado com o servidor MCP via arquivo
(ver swmcp.tools.mesh)."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any

from swmcp.tools import mesh as mops

_session = None
_session_lock = threading.Lock()


def _sw_session():
    """SwSession preguiçosa — só conecta no SolidWorks quando um botão
    que toca o SW é usado."""
    global _session
    with _session_lock:
        if _session is None:
            from swmcp.com.session import SwSession
            _session = SwSession()
    return _session


def pick_file(kind: str = "mesh") -> dict[str, Any]:
    """Diálogo nativo de abrir arquivo (roda em STA via PowerShell)."""
    filters = {
        "mesh": "Malhas 3D|*.stl;*.obj;*.ply|Todos os arquivos|*.*",
        "step": "STEP|*.step;*.stp|Todos os arquivos|*.*",
    }
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
        f"$d.Filter = '{filters.get(kind, filters['mesh'])}'; "
        "if ($d.ShowDialog() -eq 'OK') { $d.FileName }")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", script],
        capture_output=True, text=True, timeout=300)
    path = (proc.stdout or "").strip()
    return {"path": path or None}


def _save_dialog() -> str | None:
    """Diálogo nativo de salvar (STL/OBJ/PLY)."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.SaveFileDialog; "
        "$d.Filter = 'STL|*.stl|OBJ|*.obj|PLY|*.ply'; "
        "if ($d.ShowDialog() -eq 'OK') { $d.FileName }")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", script],
        capture_output=True, text=True, timeout=300)
    return (proc.stdout or "").strip() or None


def handle(route: str, body: dict[str, Any]) -> dict[str, Any]:
    """Despacha uma rota POST /mesh/<route> para a operação correspondente."""
    if route == "status":
        return mops.op_status()
    if route == "pick-file":
        return pick_file(body.get("kind", "mesh"))
    if route == "import":
        return mops.op_import(body["path"])
    if route == "info":
        return mops.op_info()
    if route == "decimate":
        return mops.op_decimate(int(body.get("target_faces", 200000)))
    if route == "smooth":
        return mops.op_smooth(int(body.get("iterations", 10)))
    if route == "flip":
        return mops.op_flip()
    if route == "export":
        path = body.get("path") or _save_dialog()
        if not path:
            return {"cancelado": True}
        return mops.op_export(path)
    if route == "align":
        return mops.op_align(body.get("mode", "pca"), body.get("region"))
    if route == "segment":
        return mops.op_segment(
            float(body.get("radius_mm", 3.0)),
            float(body.get("smooth_threshold_deg", 8.0)),
            int(body.get("min_region_vertices", 50)))
    if route == "viewerpack":
        return mops.op_viewerpack(int(body.get("target_faces", 80000)))
    if route == "savemask":
        return mops.op_save_selection(body["indices"])
    if route == "sketch3d":
        return mops.op_sketch3d(_sw_session(), body["curves"])
    if route == "freeform-commit":
        return mops.op_freeform_commit(body["ctrl"], body.get("out_step"))
    if route == "unroll":
        return mops.op_unroll(body.get("region"), body.get("method", "auto"),
                              float(body.get("seam_deg", 0.0)),
                              float(body.get("tol_mm", 0.15)))
    if route == "unroll-sketch":
        return mops.op_unroll_to_sketch(
            _sw_session(), body.get("region"), body.get("method", "auto"),
            float(body.get("seam_deg", 0.0)), float(body.get("tol_mm", 0.15)))
    if route == "symmetry":
        return mops.op_symmetry(body.get("max_score_mm"))
    if route == "fit":
        return mops.op_fit(body.get("kind", "auto"), body.get("region"),
                           float(body.get("tolerance_mm", 0.15)),
                           body.get("constraint_axis"))
    if route == "section-sketch":
        return mops.op_section_to_sketch(
            _sw_session(), body["axis"], float(body["position_mm"]),
            float(body.get("tol_mm", 0.1)))
    if route == "primitive-sw":
        return mops.op_primitive_to_sw(_sw_session(), body["primitive"])
    if route == "freeform":
        out_step = body.get("out_step") or mops._work("freeform.step")
        return mops.op_freeform(
            out_step, body.get("region"),
            (int(body.get("grid_u", 40)), int(body.get("grid_v", 40))),
            float(body.get("tol_mm", 0.05)),
            float(body.get("extend_mm", 0.0)))
    if route == "deviation":
        return mops.op_deviation(
            body.get("reference_stl"), body.get("primitive"),
            body.get("region"), float(body.get("max_dist_mm", 5.0)),
            body.get("scale_mm"), body.get("pass_fail_tol_mm"))
    raise ValueError(f"rota desconhecida: {route}")


def serve_file(path: str) -> tuple[bytes, str] | None:
    """Serve um arquivo do diretório de trabalho do motor (PNG do desvio).
    Restrito ao workdir para não virar leitura arbitrária de disco."""
    p = Path(path).resolve()
    workdir = mops._WORKDIR.resolve()
    if not str(p).startswith(str(workdir)) or not p.is_file():
        return None
    ctype = {"png": "image/png", "stl": "model/stl",
             "step": "application/step"}.get(p.suffix.lstrip(".").lower(),
                                             "application/octet-stream")
    return p.read_bytes(), ctype
