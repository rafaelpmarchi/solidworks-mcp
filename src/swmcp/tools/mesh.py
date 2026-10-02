"""Tools de engenharia reversa: malha de scanner 3D -> geometria no SolidWorks.

O processamento pesado roda no MOTOR (engine/swengine), um subprocesso com
ambiente próprio — a malha nunca passa pelo MCP, só caminhos e metadados.
Backend preferido: WSL/Ubuntu (Python 3.12 + Open3D); fallback: venv Windows.

As operações são funções de módulo (op_*) para serem reutilizadas tanto pelas
tools MCP (register) quanto pelo painel HTTP do taskpane (swmcp.chat). O estado
da malha ativa fica em ARQUIVO (%TEMP%/swengine/state.json) para o painel e o
servidor MCP — processos diferentes — enxergarem a mesma sessão de trabalho.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENGINE_DIR = _REPO_ROOT / "engine"
_ENGINE_PY = _ENGINE_DIR / ".venv" / "Scripts" / "python.exe"
_WORKDIR = Path(tempfile.gettempdir()) / "swengine"
_STATE_FILE = _WORKDIR / "state.json"
_WSL_DISTRO = "Ubuntu"

# cache por processo (backend não muda durante a vida do processo)
_backend_cache: list[str | None] = [None]


# ------------------------------------------------------------ estado em disco

def _load_state() -> dict[str, Any]:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mesh": None, "labels": None}


def _save_state(state: dict[str, Any]) -> None:
    _WORKDIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False),
                           encoding="utf-8")


def _active_mesh() -> str:
    state = _load_state()
    if not state.get("mesh"):
        raise RuntimeError("nenhuma malha ativa — use mesh_import primeiro")
    return state["mesh"]


_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _matmul4(a: list[float], b: list[float]) -> list[float]:
    """a·b de matrizes 4x4 em lista de 16 (por linha). Sem numpy: o venv do
    servidor não tem."""
    return [sum(a[4 * i + k] * b[4 * k + j] for k in range(4))
            for i in range(4) for j in range(4)]


def _compose_transform(state: dict[str, Any], matrix: list[float]) -> None:
    """Acumula no estado a transformação ORIGINAL → malha ativa (a que
    mesh_apply_to_sw aplica ao corpo de malha do SolidWorks)."""
    atual = state.get("transform") or _IDENTITY
    state["transform"] = _matmul4([float(v) for v in matrix], atual)


def _work(name: str) -> str:
    _WORKDIR.mkdir(parents=True, exist_ok=True)
    return str(_WORKDIR / f"{uuid.uuid4().hex[:8]}_{name}")


# ------------------------------------------------------- caminhos win <-> wsl

def _win_to_wsl(path: str) -> str:
    """C:\\foo\\bar -> /mnt/c/foo/bar."""
    p = str(path).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        return f"/mnt/{p[0].lower()}{p[2:]}"
    return p


def _wsl_to_win(path: str) -> str:
    """/mnt/c/foo/bar -> C:\\foo\\bar (deixa outros caminhos em paz)."""
    if path.startswith("/mnt/") and len(path) > 6 and path[6] == "/":
        return f"{path[5].upper()}:{path[6:]}".replace("/", "\\")
    return path


def _detect_backend() -> str:
    """'wsl' se o ambiente Linux do motor existir (Open3D), senão 'windows'.

    Forçável com a env var SWMCP_ENGINE_BACKEND=wsl|windows."""
    import os
    forced = os.environ.get("SWMCP_ENGINE_BACKEND", "").lower()
    if forced in ("wsl", "windows"):
        return forced
    try:
        proc = subprocess.run(
            ["wsl", "-d", _WSL_DISTRO, "--", "sh", "-c",
             "test -x \"$HOME/.swengine-env/bin/python\""],
            capture_output=True, timeout=30)
        if proc.returncode == 0:
            return "wsl"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "windows"


def _backend() -> str:
    if _backend_cache[0] is None:
        _backend_cache[0] = _detect_backend()
    return _backend_cache[0]


_PATH_KEYS = {"mesh", "out", "labels_out", "png", "reference", "out_step",
              "viewer_bin", "labels"}


def _translate_args(args: dict) -> dict:
    """Converte os campos de caminho para o filesystem do WSL."""
    out = {}
    for k, v in args.items():
        if k in _PATH_KEYS and isinstance(v, str):
            out[k] = _win_to_wsl(v)
        elif k == "region" and isinstance(v, dict):
            reg = dict(v)
            for sub in ("labels", "mask"):
                if sub in reg and isinstance(reg[sub], dict) and "path" in reg[sub]:
                    reg[sub] = {**reg[sub],
                                "path": _win_to_wsl(reg[sub]["path"])}
            out[k] = reg
        else:
            out[k] = v
    return out


def _translate_result(obj: Any) -> Any:
    """Converte caminhos /mnt/x de volta para o Windows no resultado."""
    if isinstance(obj, str):
        return _wsl_to_win(obj)
    if isinstance(obj, dict):
        return {k: _translate_result(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_translate_result(v) for v in obj]
    return obj


# ------------------------------------------------------------------- o motor

def _engine(command: str, args: dict) -> dict:
    """Chama o motor por subprocesso; levanta RuntimeError com o erro dele.

    Backend 'wsl': Python 3.12 + Open3D num ambiente Linux isolado.
    Backend 'windows': venv engine/.venv (fallback, sem Open3D)."""
    if _backend() == "wsl":
        cmd = ["wsl", "-d", _WSL_DISTRO, "--", "bash",
               _win_to_wsl(str(_ENGINE_DIR / "wsl-run.sh")), command]
        args = _translate_args(args)
        cwd = None
    else:
        if not _ENGINE_PY.exists():
            raise RuntimeError(
                f"motor não instalado ({_ENGINE_PY}) e WSL indisponível. "
                "Crie o venv: cd engine && py -3.13 -m venv .venv && "
                ".venv\\Scripts\\pip install trimesh numpy scipy matplotlib "
                "rtree pillow networkx build123d")
        cmd = [str(_ENGINE_PY), "-m", "swengine", command]
        cwd = str(_ENGINE_DIR)
    proc = subprocess.run(
        cmd, input=json.dumps(args), capture_output=True, text=True,
        cwd=cwd, timeout=600,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # o OpenCascade imprime estatísticas no stdout antes do JSON do CLI —
        # o resultado verdadeiro é a última linha que parseia como objeto
        out = None
        for line in reversed(proc.stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    out = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if out is None:
            raise RuntimeError(
                f"motor falhou (exit {proc.returncode}): "
                f"{proc.stderr[-800:] or proc.stdout[-800:]}") from None
    if not out.get("ok"):
        raise RuntimeError(f"motor: {out.get('erro')}")
    out.pop("ok", None)
    out.pop("trace", None)
    return _translate_result(out)


def _resolve_region(region: dict | None) -> dict | None:
    if region and region.get("active"):
        # "região ativa": a seleção pintada no viewer, se houver; senão tudo
        state = _load_state()
        mask = state.get("selection_mask")
        return {"mask": {"path": mask}} if mask else None
    if region and "labels" in region and "path" not in region["labels"]:
        state = _load_state()
        if not state.get("labels"):
            raise RuntimeError("rode mesh_segment antes de usar region por labels")
        region = {**region,
                  "labels": {**region["labels"], "path": state["labels"]}}
    return region


# ------------------------------------------------- operações (motor, sem SW)

def op_import(path: str) -> dict[str, Any]:
    info = _engine("info", {"mesh": path})
    _save_state({"mesh": path, "labels": None, "original": path,
                 "transform": list(_IDENTITY)})
    return {"mesh": path, **info}


def op_info() -> dict[str, Any]:
    return _engine("info", {"mesh": _active_mesh()})


def op_status() -> dict[str, Any]:
    """Estado da sessão de engenharia reversa (para o painel)."""
    state = _load_state()
    return {"mesh": state.get("mesh"), "original": state.get("original"),
            "tem_labels": bool(state.get("labels")),
            "regioes": state.get("regioes") or [],
            "viewer_bin": state.get("viewer_bin"),
            "selection_mask": state.get("selection_mask"),
            "backend": _backend()}


def op_decimate(target_faces: int) -> dict[str, Any]:
    out = _work("decimated.stl")
    r = _engine("decimate", {"mesh": _active_mesh(), "out": out,
                             "target_faces": target_faces})
    state = _load_state()
    state.update({"mesh": out, "labels": None, "regioes": None})
    _save_state(state)
    return r


def op_smooth(iterations: int = 10) -> dict[str, Any]:
    out = _work("smoothed.stl")
    r = _engine("smooth", {"mesh": _active_mesh(), "out": out,
                           "iterations": iterations})
    state = _load_state()
    state.update({"mesh": out, "labels": None, "regioes": None})
    _save_state(state)
    return r


def op_flip() -> dict[str, Any]:
    out = _work("flipped.stl")
    r = _engine("flip", {"mesh": _active_mesh(), "out": out})
    state = _load_state()
    state.update({"mesh": out, "labels": None, "regioes": None})
    _save_state(state)
    return r


def op_export(out_path: str) -> dict[str, Any]:
    return _engine("export", {"mesh": _active_mesh(), "out": out_path})


def op_align(mode: str = "pca", region: dict | None = None,
             reference: str | None = None,
             inlier_mm: float = 0.5, axis_hint: list | None = None,
             z_origin: str = "centroid") -> dict[str, Any]:
    out = _work("aligned.stl")
    args: dict[str, Any] = {"mesh": _active_mesh(), "out": out,
                            "mode": mode, "region": _resolve_region(region)}
    if mode == "to_reference":
        if not reference:
            raise RuntimeError("mode=to_reference exige reference_stl "
                               "(ou use mode=to_cad para exportar o documento ativo)")
        args["reference"] = reference
        args["inlier_mm"] = inlier_mm
    if mode == "axis":
        args["axis_hint"] = axis_hint
        args["z_origin"] = z_origin
    r = _engine("align", args)
    state = _load_state()
    state.update({"mesh": out, "labels": None, "regioes": None})
    _compose_transform(state, r["matrix"])
    if mode == "to_reference":
        state["cad_stl"] = reference
        ext = r.get("referencia_extents_mm") or []
        if ext and max(ext) < 0.1 * max(r.get("extents_mm", [1])):
            r["aviso"] = ("a referência é ~25x menor que o scan: o STL do CAD "
                          "provavelmente saiu em polegadas — confira as "
                          "unidades de exportação STL do SolidWorks")
    _save_state(state)
    return r


def op_align_to_cad(session: SwSession, region: dict | None = None,
                    inlier_mm: float = 0.5) -> dict[str, Any]:
    """Exporta o documento ativo do SolidWorks em STL (temporário) e registra
    o scan nele."""
    stl = _work("cad.stl")
    exp = session.run(lambda app: o.save_as(app, stl, True))
    r = op_align("to_reference", region, stl, inlier_mm)
    r["cad_stl"] = exp["path"]
    return r


def op_segment(radius_mm: float = 3.0, smooth_threshold_deg: float = 8.0,
               min_region_vertices: int = 50) -> dict[str, Any]:
    labels_out = _work("labels.npy")
    r = _engine("segment", {"mesh": _active_mesh(), "labels_out": labels_out,
                            "radius_mm": radius_mm,
                            "smooth_threshold_deg": smooth_threshold_deg,
                            "min_region_vertices": min_region_vertices})
    state = _load_state()
    state["labels"] = labels_out
    state["regioes"] = r.get("regioes_lisas", [])
    _save_state(state)
    return r


def op_unroll(region: dict | None = None, method: str = "auto",
              seam_deg: float = 0.0, tol_mm: float = 0.15) -> dict[str, Any]:
    out = _work("unrolled.stl")
    return _engine("unroll", {"mesh": _active_mesh(),
                              "region": _resolve_region(region),
                              "method": method, "seam_deg": seam_deg,
                              "tol_mm": tol_mm, "out": out})


def op_unroll_to_sketch(session: SwSession, region: dict | None = None,
                        method: str = "auto", seam_deg: float = 0.0,
                        tol_mm: float = 0.15) -> dict[str, Any]:
    r = op_unroll(region, method, seam_deg, tol_mm)
    drawn = {"line": 0, "arc": 0, "spline": 0}

    def draw(app):
        for loop in r["contorno"]:
            for e in loop["entities"]:
                if e["type"] == "line":
                    m.sketch_line(app, e["p1"][0], e["p1"][1],
                                  e["p2"][0], e["p2"][1])
                    drawn["line"] += 1
                elif e["type"] == "arc":
                    m.sketch_arc_center(app, e["center"][0], e["center"][1],
                                        e["p1"][0], e["p1"][1],
                                        e["p2"][0], e["p2"][1], 1)
                    drawn["arc"] += 1
                else:
                    pts = e["points"]
                    m.sketch_spline(app, pts[::max(1, len(pts) // 60)])
                    drawn["spline"] += 1

    session.run(draw)
    r["desenhado"] = drawn
    r.pop("contorno", None)
    return r


def op_viewerpack(target_faces: int = 80000) -> dict[str, Any]:
    state = _load_state()
    out = _work("viewer.bin")
    r = _engine("viewerpack", {"mesh": _active_mesh(), "out": out,
                               "target_faces": target_faces,
                               "labels": state.get("labels")})
    state["viewer_bin"] = r["bin"]
    _save_state(state)
    return r


def op_save_selection(indices: list[int]) -> dict[str, Any]:
    state = _load_state()
    if not state.get("viewer_bin"):
        raise RuntimeError("gere o viewer primeiro (viewerpack)")
    out = _work("selecao.npy")
    r = _engine("savemask", {"mesh": _active_mesh(),
                             "viewer_bin": state["viewer_bin"],
                             "indices": indices, "out": out})
    state["selection_mask"] = r["mask"]
    _save_state(state)
    return r


def op_sketch3d(session: SwSession,
                curves_mm: list[list[list[float]]]) -> dict[str, Any]:
    feat = session.run(lambda app: m.sketch_3d_splines(app, curves_mm))
    return {"sketch3d": feat, "curvas": len(curves_mm)}


def op_freeform_commit(ctrl: dict, out_step: str | None = None) -> dict[str, Any]:
    return _engine("freeform_step", {"ctrl": ctrl,
                                     "out_step": out_step or _work("editado.step")})


def op_symmetry(max_score_mm: float | None = None) -> dict[str, Any]:
    return _engine("symmetry", {"mesh": _active_mesh(),
                                "max_score_mm": max_score_mm})


def op_fit(kind: str = "auto", region: dict | None = None,
           tolerance_mm: float = 0.15,
           constraint_axis: list | None = None) -> dict[str, Any]:
    return _engine("fit", {"mesh": _active_mesh(), "kind": kind,
                           "region": _resolve_region(region),
                           "tolerance_mm": tolerance_mm,
                           "constraint_axis": constraint_axis})


def op_section(axis: str, positions: list[float],
               tol_mm: float = 0.1) -> dict[str, Any]:
    return _engine("section", {"mesh": _active_mesh(), "axis": axis,
                               "positions": positions, "tol_mm": tol_mm})


def op_freeform(out_step: str, region: dict | None = None,
                grid: tuple[int, int] = (40, 40),
                tol_mm: float = 0.05, extend_mm: float = 0.0) -> dict[str, Any]:
    return _engine("freeform", {"mesh": _active_mesh(),
                                "region": _resolve_region(region),
                                "out_step": out_step,
                                "grid": list(grid), "tol_mm": tol_mm,
                                "extend_mm": extend_mm})


def op_axis(region: dict | None = None, axis_hint: list | None = None) -> dict[str, Any]:
    return _engine("axis", {"mesh": _active_mesh(), "region": _resolve_region(region),
                            "axis_hint": axis_hint})


def op_revolve_profile(axis_point: list | None = None, axis_dir: list | None = None,
                       region: dict | None = None, min_coverage: float = 0.4,
                       tol_mm: float = 0.1, cell_mm: float = 0.25,
                       thickness_mm: float | None = None) -> dict[str, Any]:
    return _engine("revolve_profile", {
        "mesh": _active_mesh(), "axis_point": axis_point or [0, 0, 0],
        "axis_dir": axis_dir or [0, 0, 1], "region": _resolve_region(region),
        "min_coverage": min_coverage, "tol_mm": tol_mm, "cell_mm": cell_mm,
        "thickness_mm": thickness_mm})


def op_detect_holes(axis_point: list | None = None, axis_dir: list | None = None,
                    min_diameter_mm: float = 1.0, group_tol_mm: float = 0.4,
                    angle_tol_deg: float = 1.0,
                    region: dict | None = None) -> dict[str, Any]:
    return _engine("holes", {
        "mesh": _active_mesh(), "axis_point": axis_point or [0, 0, 0],
        "axis_dir": axis_dir or [0, 0, 1], "min_diameter_mm": min_diameter_mm,
        "group_tol_mm": group_tol_mm, "angle_tol_deg": angle_tol_deg,
        "region": _resolve_region(region)})


def op_deviation(reference_stl: str | None = None, primitive: dict | None = None,
                 region: dict | None = None, max_dist_mm: float = 5.0,
                 scale_mm: float | None = None,
                 pass_fail_tol_mm: float | None = None) -> dict[str, Any]:
    if not reference_stl and not primitive:
        reference_stl = _load_state().get("cad_stl")
        if not reference_stl:
            raise RuntimeError("passe reference_stl (malha) ou primitive (fit) "
                               "— ou alinhe antes com mesh_align(mode='to_cad'), "
                               "que deixa o STL do CAD como referência padrão")
    png = _work("deviation.png")
    args: dict[str, Any] = {"mesh": _active_mesh(), "png": png,
                            "max_dist_mm": max_dist_mm}
    if reference_stl:
        args["reference"] = reference_stl
    if primitive:
        args["primitive"] = primitive
        args["region"] = _resolve_region(region)
    if scale_mm is not None:
        args["scale_mm"] = scale_mm
    if pass_fail_tol_mm is not None:
        args["pass_fail_tol_mm"] = pass_fail_tol_mm
    return _engine("deviation", args)


# ------------------------------------------- operações que tocam o SolidWorks

def op_section_to_sketch(session: SwSession, axis: str, position_mm: float,
                         tol_mm: float = 0.1,
                         max_polyline_points: int = 60) -> dict[str, Any]:
    r = op_section(axis, [position_mm], tol_mm)
    sec = r["sections"][0]
    if "aviso" in sec:
        return {"desenhado": 0, "aviso": sec["aviso"]}
    drawn = {"line": 0, "arc": 0, "spline": 0,
             "circle": 0, "slot": 0, "rectangle": 0}

    def draw_entities(app, entities):
        for e in entities:
            if e["type"] == "line":
                m.sketch_line(app, e["p1"][0], e["p1"][1],
                              e["p2"][0], e["p2"][1])
                drawn["line"] += 1
            elif e["type"] == "arc":
                m.sketch_arc_center(app, e["center"][0], e["center"][1],
                                    e["p1"][0], e["p1"][1],
                                    e["p2"][0], e["p2"][1], 1)
                drawn["arc"] += 1
            else:
                pts = e["points"]
                step = max(1, len(pts) // max_polyline_points)
                m.sketch_spline(app, pts[::step])
                drawn["spline"] += 1

    def draw(app):
        for loop in sec["loops"]:
            shape = loop.get("shape")
            # formas reconhecidas viram entidade NATIVA do SolidWorks
            if shape and shape["shape"] == "circle":
                m.sketch_circle(app, shape["center"][0], shape["center"][1],
                                2.0 * shape["radius"])
                drawn["circle"] += 1
            elif shape and shape["shape"] == "slot":
                m.sketch_slot(app, shape["c1"][0], shape["c1"][1],
                              shape["c2"][0], shape["c2"][1], shape["width"])
                drawn["slot"] += 1
            elif shape and shape["shape"] == "rectangle" and shape["axis_aligned"]:
                m.sketch_rectangle(app, shape["min"][0], shape["min"][1],
                                   shape["max"][0], shape["max"][1])
                drawn["rectangle"] += 1
            else:
                draw_entities(app, loop["entities"])

    session.run(draw)
    reconhecidas = [loop["shape"]["shape"] for loop in sec["loops"]
                    if loop.get("shape")]
    return {"desenhado": drawn, "loops": len(sec["loops"]),
            "formas_reconhecidas": reconhecidas, "plane": sec["plane"]}


def op_primitive_to_sw(session: SwSession, primitive: dict) -> dict[str, Any]:
    # sem numpy de propósito: o venv do servidor MCP não tem numpy (só o do
    # motor tem) — e aqui é só produto escalar.
    import math
    kind = primitive.get("kind")
    axes = {"x": ((1.0, 0.0, 0.0), "Plano direito"),
            "y": ((0.0, 1.0, 0.0), "Plano frontal"),
            "z": ((0.0, 0.0, 1.0), "Plano superior")}

    def dot(a, b):
        return sum(float(x) * float(y) for x, y in zip(a, b))

    def closest_axis(v):
        n = math.sqrt(dot(v, v))
        v = [float(x) / n for x in v]
        for name, (ax, plane) in axes.items():
            if abs(dot(v, ax)) > 0.9986:  # ~3 graus
                return name, ax, plane
        return None

    if kind == "plane":
        hit = closest_axis(primitive["normal"])
        if not hit:
            return {"aviso": "normal oblíqua aos eixos — use run_sw_script "
                             "para plano por 3 pontos", "primitive": primitive}
        name, ax, plane = hit
        offset = dot(primitive["point"], ax)
        feat = session.run(lambda app: m.reference_plane_offset(
            app, plane, abs(offset), flip=offset < 0))
        return {"feature": feat, "base": plane, "offset_mm": round(offset, 4)}

    if kind == "cylinder":
        hit = closest_axis(primitive["axis"])
        if not hit:
            return {"aviso": "eixo oblíquo — use run_sw_script",
                    "primitive": primitive}
        name, ax, plane = hit
        p = [float(x) for x in primitive["point"]]
        height = float(primitive.get("height", 0.0))
        base = [pi - ai * height / 2.0 for pi, ai in zip(p, ax)]
        offset = dot(base, ax)
        uv_idx = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}[name]
        cx, cy = float(p[uv_idx[0]]), float(p[uv_idx[1]])
        dia = 2.0 * float(primitive["radius"])

        def build(app):
            if abs(offset) > 1e-6:
                new_plane = m.reference_plane_offset(app, plane, abs(offset),
                                                     flip=offset < 0)
                name_feat = m.insert_sketch(app, new_plane)
            else:
                name_feat = m.insert_sketch(app, plane)
            m.sketch_circle(app, cx, cy, dia)
            return name_feat

        sketch = session.run(build)
        return {"sketch": sketch, "centro_mm": [round(cx, 4), round(cy, 4)],
                "diametro_mm": round(dia, 4),
                "altura_para_extrudar_mm": round(height, 4)}

    return {"aviso": f"kind '{kind}' sem materialização direta — use os "
                     "parâmetros com as tools de modelagem ou run_sw_script",
            "primitive": primitive}


def _v_sub(a, b):
    return [float(x) - float(y) for x, y in zip(a, b)]


def _v_cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _v_unit(a):
    n = sum(x * x for x in a) ** 0.5
    if n < 1e-12:
        raise RuntimeError("vetor nulo")
    return [x / n for x in a]


def radial_in_plane(axis_dir: list[float], plane_normal: list[float]) -> list[float]:
    """Direção radial que fica DENTRO do plano do esboço (⊥ ao eixo e à
    normal do plano), com sinal para o lado +X (ou +Y) do modelo."""
    a = _v_unit(axis_dir)
    n = _v_unit(plane_normal)
    if abs(sum(x * y for x, y in zip(a, n))) > 0.01:
        raise RuntimeError("o plano do esboço não contém o eixo da peça — use um "
                           "plano que passe pelo eixo (com a peça alinhada em Z: "
                           "'Plano superior' ou 'Plano direito')")
    r = _v_unit(_v_cross(n, a))
    if r[0] < -1e-9 or (abs(r[0]) <= 1e-9 and r[1] < 0):
        r = [-x for x in r]
    return r


def profile_model_points(axis_point: list[float], axis_dir: list[float],
                         radial: list[float], verts_rz: list[list[float]]) -> list[list[float]]:
    """(r, z) do perfil → pontos da peça (mm): ponto do eixo + r·radial + z·eixo."""
    a = _v_unit(axis_dir)
    return [[axis_point[i] + r * radial[i] + z * a[i] for i in range(3)]
            for r, z in verts_rz]


def _sketch_normal(app) -> list[float]:
    """Normal do esboço ativo em coordenadas da peça (pela transformada)."""
    o = m.model_to_sketch_mm(app, [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
    # o 3º valor de cada eixo da peça no esboço é a componente na normal
    return [o[1][2] - o[0][2], o[2][2] - o[0][2], o[3][2] - o[0][2]]


def op_revolve_profile_to_sw(session: SwSession, profile: dict, plane: str,
                             fillets: bool = False) -> dict[str, Any]:
    """Desenha o perfil (r, z) num esboço NOVO no plano dado + a linha de
    centro no eixo. Fecha com o perfil fechado do motor (scan dos dois lados)
    ou com closed_vertices_rz (thickness_mm); aberto fica aberto (revolve de
    perfil aberto só sai como superfície/parede fina)."""
    axis_point = profile["axis_point"]
    axis_dir = profile["axis_dir"]
    fechado = profile.get("closed")
    verts = profile.get("closed_vertices_rz") if not fechado else None
    usar_fechamento = verts is not None
    verts = verts or profile["vertices_rz"]
    zs = [z for _, z in verts]
    resultado: dict[str, Any] = {}

    def draw(app):
        sketch = m.insert_sketch(app, plane)
        normal = _sketch_normal(app)
        radial = radial_in_plane(axis_dir, normal)
        pts = m.model_to_sketch_mm(app, profile_model_points(axis_point, axis_dir, radial, verts))
        fora = max(abs(p[2]) for p in pts)
        if fora > 0.01:
            raise RuntimeError(f"o perfil sai {fora:.3f} mm do plano do esboço")
        p2 = [[round(p[0], 6), round(p[1], 6)] for p in pts]
        poly = m.sketch_polyline(app, p2, close=bool(fechado or usar_fechamento))
        eixo = m.model_to_sketch_mm(app, profile_model_points(
            axis_point, axis_dir, radial, [[0.0, min(zs) - 5.0], [0.0, max(zs) + 5.0]]))
        m.sketch_line(app, eixo[0][0], eixo[0][1], eixo[1][0], eixo[1][1], centerline=True)
        feitos, falhas = [], []
        if fillets:
            for f in profile.get("fillets") or []:
                i = f["vertex"]
                if i >= len(p2):
                    continue
                try:
                    _sketch_corner_fillet(app, p2[i], f["radius_mm"])
                    feitos.append({"vertex": i, "radius_mm": f["radius_mm"]})
                except Exception as exc:  # noqa: BLE001 — filete é extra; o perfil fica
                    falhas.append({"vertex": i, "erro": str(exc)[:200]})
        resultado.update({"sketch": sketch, "plane": plane, "radial_dir": radial,
                          "polyline": poly, "fillets_applied": feitos,
                          "fillets_failed": falhas,
                          "closed": bool(fechado or usar_fechamento)})

    session.run(draw)
    if not resultado["closed"]:
        resultado["aviso"] = ("perfil ABERTO (scan de um lado só): passe thickness_mm "
                              "para fechar com uma parede estimada antes do revolve")
    return resultado


def _sketch_corner_fillet(app, corner_mm: list[float], radius_mm: float) -> None:
    """Concordância no canto do esboço ativo que cai em corner_mm."""
    from swmcp.com import units
    from swmcp.com.invoke import com_call, com_get
    from swmcp.com.session import cast_to

    model = cast_to(com_get(app, "ActiveDoc"), "IModelDoc2")
    skm = com_get(model, "SketchManager")
    sketch = cast_to(com_get(skm, "ActiveSketch"), "ISketch")
    alvo = None
    for raw in com_call(sketch, "GetSketchPoints2") or []:
        p = cast_to(raw, "ISketchPoint")
        if (abs(units.to_mm(com_get(p, "X")) - corner_mm[0]) < 1e-3
                and abs(units.to_mm(com_get(p, "Y")) - corner_mm[1]) < 1e-3):
            alvo = p
            break
    if alvo is None:
        raise RuntimeError(f"canto {corner_mm} não achado no esboço")
    com_call(model, "ClearSelection2", True)
    com_call(alvo, "Select4", False, None)
    # swConstrainedCornerAction_KeepGeometry = 1: mantém a geometria
    seg = com_call(skm, "CreateFillet", units.from_mm(radius_mm), 1)
    com_call(model, "ClearSelection2", True)
    if not seg:
        raise RuntimeError("CreateFillet recusou (raio maior que as linhas permitem?)")


def op_holes_to_sw(session: SwSession, holes: dict, diameters: list[float] | None = None,
                   tol_mm: float = 0.4) -> dict[str, Any]:
    """Desenha os furos com parede (has_wall) no esboço ATIVO, que precisa ser
    perpendicular ao eixo. diameters filtra (± tol_mm)."""
    alvos = [h for h in holes["holes"] if h["has_wall"]]
    if diameters:
        alvos = [h for h in alvos if any(abs(h["diameter_mm"] - d) <= tol_mm for d in diameters)]
    if not alvos:
        return {"desenhados": 0, "aviso": "nenhum furo (com parede) para desenhar"}
    a = _v_unit(holes["axis_dir"])

    def draw(app):
        normal = _sketch_normal(app)
        if abs(abs(sum(x * y for x, y in zip(_v_unit(normal), a))) - 1.0) > 1e-3:
            raise RuntimeError("o esboço ativo não é perpendicular ao eixo dos furos — "
                               "abra o esboço numa face/plano normal ao eixo")
        pts = m.model_to_sketch_mm(app, [h["center_xyz"] for h in alvos])
        return m.sketch_circles(app, [[p[0], p[1], h["diameter_mm"]]
                                      for p, h in zip(pts, alvos)])

    r = session.run(draw)
    return {"desenhados": r["circles"], "centers_mm": r["centers_mm"]}


def op_apply_to_sw(session: SwSession, body_name: str = "") -> dict[str, Any]:
    """Aplica ao corpo de malha do SolidWorks a transformação acumulada
    original → malha ativa (mesh_align & cia.), para o scan no SW e o motor
    ficarem no mesmo sistema."""
    from swmcp.com.wrappers import bodies as b

    state = _load_state()
    t = state.get("transform")
    if not t:
        raise RuntimeError("sessão sem transformação registrada — reimporte a malha "
                           "(mesh_import) e alinhe de novo")
    if max(abs(x - y) for x, y in zip(t, _IDENTITY)) < 1e-9:
        return {"aviso": "a malha ativa ainda não foi alinhada — nada a mover"}
    info = op_info()
    esperado = info["bounds_min_mm"] + info["bounds_max_mm"]
    r = session.run(lambda app: b.move_body_by_matrix(app, t, body_name, esperado))
    r["original"] = state.get("original")
    return r


def op_deviation_active_doc(session: SwSession, bodies: list[str] | None = None,
                            **kw) -> dict[str, Any]:
    """Desvio da malha ativa contra o documento aberto, SEM realinhar: o STL
    sai nas coordenadas da peça (só os corpos pedidos, se vierem)."""
    stl = _work("doc.stl")
    session.run(lambda app: o.export_stl(app, stl, bodies, True))
    r = op_deviation(reference_stl=stl, **kw)
    r["reference_stl"] = stl
    return r


# ----------------------------------------------------------------- tools MCP

def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def mesh_import(path: str) -> dict[str, Any]:
        """Carrega uma malha de scanner 3D (STL/OBJ/PLY, unidades em mm) e a
        torna a malha ativa das demais tools mesh_*. Retorna estatísticas
        (vértices, faces, caixa envolvente). Não altera o SolidWorks."""
        return op_import(path)

    @mcp.tool()
    def mesh_info() -> dict[str, Any]:
        """Estatísticas da malha ativa (mm): vértices, faces, caixa envolvente,
        estanqueidade, área e volume."""
        return op_info()

    @mcp.tool()
    def mesh_decimate(target_faces: int) -> dict[str, Any]:
        """Reduz a malha ativa para ~target_faces triângulos (acelera todo o
        resto; 200000 preserva bem detalhe de peça mecânica). A malha reduzida
        vira a ativa; o arquivo original não é tocado."""
        return op_decimate(target_faces)

    @mcp.tool()
    def mesh_align(mode: str = "pca", region: dict | None = None,
                   reference_stl: str | None = None,
                   inlier_mm: float = 0.5, axis_hint: list | None = None,
                   z_origin: str = "centroid") -> dict[str, Any]:
        """Alinha a malha ativa e a torna a ativa. mode:
        'axis' — PEÇA DE REVOLUÇÃO: acha o eixo pela geometria das normais
          (toda reta normal de uma superfície de revolução corta o eixo; furos
          fora do centro e orelhas viram outliers) e o leva para Z com o
          ponto do eixo na origem. Devolve 'eixo' com inlier_area_fraction,
          rms_mm e eigen_ratio (< 3 = eixo mal determinado). axis_hint dá o
          sentido de +Z; z_origin: 'centroid' | 'min' (peça em Z ≥ 0) | 'max'.
          Use em vez de 'pca' em disco/flange/cubo: o PCA erra o centro.
        'to_cad' — registra o scan NO DOCUMENTO ABERTO do SolidWorks (exporta
          um STL temporário do modelo e faz best-fit rígido PCA + ICP): a
          malha passa a viver no sistema de coordenadas do desenho, e daí
          seções, primitivas e mesh_deviation_map (que passa a usar esse STL
          como referência padrão) saem direto sobre o CAD. Devolve 'registro'
          com rms/p95/inlier_fraction (fração do scan a menos de inlier_mm
          do CAD) antes e depois — inlier baixo = peça diferente do modelo ou
          registro preso num mínimo local; 'region' restringe os pontos do
          scan usados (ex.: só as faces usinadas, {"labels": {...}}).
        'to_reference' — o mesmo contra um STL dado em reference_stl.
        'pca' (eixos principais -> XYZ, centroide na origem), 'bbox' (caixa
        mínima orientada, canto em 0,0,0) ou 'plane_to_xy' (ajusta um plano na
        'region' e o leva para Z=0 com normal +Z — assenta a face usinada de
        referência). region: {"box": {"min":[x,y,z],"max":[x,y,z]}} |
        {"axis_range": {"axis":"z","min":a,"max":b}} | {"seed": {"point":
        [x,y,z],"radius":r}} | {"labels": {"value": N}}."""
        if mode == "to_cad":
            return op_align_to_cad(session, region, inlier_mm)
        return op_align(mode, region, reference_stl, inlier_mm, axis_hint, z_origin)

    @mcp.tool()
    def mesh_revolve_profile(min_coverage: float = 0.4, tol_mm: float = 0.1,
                             thickness_mm: float | None = None,
                             region: dict | None = None,
                             axis_point: list | None = None,
                             axis_dir: list | None = None,
                             draw: bool = False, plane: str = "Plano superior",
                             fillets: bool = False) -> dict[str, Any]:
        """Perfil de REVOLUÇÃO (r, z) da malha ativa em torno do eixo (padrão:
        Z pela origem — rode mesh_align(mode='axis') antes). Só entram as
        superfícies vistas em >= min_coverage da volta (furos e orelhas ficam
        de fora; onde duas superfícies se alternam na volta fica a de maior
        cobertura). Devolve vertices_rz (polilinha de CANTOS VIVOS, retas
        reajustadas), fillets (raio de concordância estimado por canto),
        rms_mm/p95_mm da curva contra a polilinha e closed. Scan de um lado só
        sai ABERTO: thickness_mm fecha com uma parede de espessura constante
        (closed_vertices_rz — é ESTIMATIVA, confira a espessura real).
        draw=True cria um esboço em `plane` (tem que conter o eixo) com o
        perfil de cantos vivos + linha de centro, pronto para revolve.
        fillets=True põe também as concordâncias no esboço — DESLIGADO por
        padrão: em 02/10/2026 o SolidWorks caiu (mfc140u.dll) na cotagem
        automática do revolve sobre um perfil de eixo vertical com essas
        concordâncias. Prefira filetar as arestas depois (fillet_circular_edges)."""
        r = op_revolve_profile(axis_point, axis_dir, region, min_coverage, tol_mm,
                               thickness_mm=thickness_mm)
        if draw:
            r["desenho"] = op_revolve_profile_to_sw(session, r, plane, fillets)
        return r

    @mcp.tool()
    def mesh_detect_holes(min_diameter_mm: float = 1.0, group_tol_mm: float = 0.4,
                          angle_tol_deg: float = 1.0, region: dict | None = None,
                          axis_point: list | None = None,
                          axis_dir: list | None = None, draw: bool = False,
                          draw_diameters: list[float] | None = None) -> dict[str, Any]:
        """Furos passantes vistos ao longo do eixo (padrão Z pela origem —
        alinhe com mesh_align antes). O Ø sai do ajuste de círculo nas
        PAREDES do furo (o contorno do vazio sozinho erra ~0,4 mm); vazio sem
        parede é lacuna de scan (adesivo de alvo, reflexo): has_wall=False,
        fora dos grupos. groups_by_size agrupa por Ø + raio; groups_by_circle
        só por raio (furação mista num mesmo PCD); cada grupo traz pattern:
        posições na volta, passo, ângulo inicial e quais posições FALTAM.
        draw=True desenha os furos com parede no esboço ATIVO (perpendicular
        ao eixo); draw_diameters filtra quais Ø desenhar."""
        r = op_detect_holes(axis_point, axis_dir, min_diameter_mm, group_tol_mm,
                            angle_tol_deg, region)
        if draw:
            r["desenho"] = op_holes_to_sw(session, r, draw_diameters, group_tol_mm)
        return r

    @mcp.tool()
    def mesh_apply_to_sw(body_name: str = "") -> dict[str, Any]:
        """Leva o corpo de malha do SolidWorks (o scan importado no documento
        ativo) para o MESMO sistema da malha ativa do motor, aplicando a
        transformação acumulada desde o mesh_import (mesh_align & cia.) com
        features Mover/Copiar corpo (giro X, Y, Z e translação). body_name
        vazio = o maior corpo. Confere a caixa final contra a da malha ativa
        (box_error_mm/ok). Altera o documento ativo."""
        return op_apply_to_sw(session, body_name)

    @mcp.tool()
    def mesh_segment(radius_mm: float = 3.0, smooth_threshold_deg: float = 8.0,
                     min_region_vertices: int = 50) -> dict[str, Any]:
        """Separa regiões LISAS (usinadas: flange, mancal, furo) do resto
        (superfície bruta de fundição) pela variação local das normais.
        Retorna as regiões com label, centroide e caixa — use o label em
        mesh_fit_primitive via region={"labels": {"value": N}}."""
        return op_segment(radius_mm, smooth_threshold_deg, min_region_vertices)

    @mcp.tool()
    def mesh_unroll(region: dict | None = None, method: str = "auto",
                    seam_deg: float = 0.0, to_sketch: bool = False) -> dict[str, Any]:
        """Planifica (roll/unroll) a malha ativa ou uma região: cilindro/cone
        têm desenvolvimento EXATO (costura em seam_deg; desvio do scan vira
        relevo); superfície de dupla curvatura usa LSCM aproximado com
        relatório de distorção — chapa real estica, o aviso diz quanto.
        to_sketch=True desenha o contorno da planificação no sketch ativo do
        SolidWorks (pronto para corte). method: auto|cylinder|cone|lscm."""
        if to_sketch:
            return op_unroll_to_sketch(session, region, method, seam_deg)
        return op_unroll(region, method, seam_deg)

    @mcp.tool()
    def mesh_symmetry_plane(max_score_mm: float | None = None) -> dict[str, Any]:
        """Detecta o plano de simetria da malha ativa (PCA + refino por
        espelhamento). Retorna ponto/normal em mm, score_mm (mediana do desvio
        espelhado) e 'simetrica' (score dentro do limite; padrão 1% da
        diagonal). Peça automotiva quase sempre tem — alinhe nele e modele
        metade + espelho."""
        return op_symmetry(max_score_mm)

    @mcp.tool()
    def mesh_fit_primitive(kind: str = "auto", region: dict | None = None,
                           tolerance_mm: float = 0.15,
                           constraint_axis: list | None = None) -> dict[str, Any]:
        """Ajusta uma primitiva (RANSAC + refino) na região da malha ativa.
        kind: plane | cylinder | sphere | cone | auto. Retorna parâmetros em
        mm/graus + inlier_fraction e rms_mm (qualidade do ajuste). region:
        mesmas formas de mesh_align, mais {"labels": {"value": N}} vindo de
        mesh_segment. Dica: alinhe a malha antes; primitivas saem no sistema
        de coordenadas da malha ativa. constraint_axis (ex.: [0,0,1]) trava a
        normal do plano ou o eixo do cilindro nessa direção (fit restrito,
        como os botões Vertical/Horizontal do QuickSurface)."""
        return op_fit(kind, region, tolerance_mm, constraint_axis)

    @mcp.tool()
    def mesh_section_to_sketch(axis: str, position_mm: float,
                               tol_mm: float = 0.1,
                               max_polyline_points: int = 60) -> dict[str, Any]:
        """Corta a malha ativa com um plano perpendicular a 'axis' (x|y|z) na
        cota position_mm e DESENHA o contorno no sketch ATIVO do SolidWorks
        (linhas e arcos onde o ajuste fecha na tolerância; spline no resto).
        Abra antes um sketch num plano equivalente ao corte (create_sketch em
        plano offset na mesma cota). Coordenadas 2D do corte = (u,v) do plano
        da seção, retornadas junto para conferência."""
        return op_section_to_sketch(session, axis, position_mm, tol_mm,
                                    max_polyline_points)

    @mcp.tool()
    def mesh_primitive_to_sw(primitive: dict) -> dict[str, Any]:
        """Materializa no SolidWorks uma primitiva ajustada (dict retornado por
        mesh_fit_primitive). plane com normal ~paralela a X/Y/Z vira plano de
        referência offset; cylinder com eixo ~paralelo a X/Y/Z vira sketch com
        círculo no plano da base (pronto para extrudar com a 'height' do fit).
        Casos oblíquos: use run_sw_script. Exige a malha alinhada (mesh_align)
        para os eixos da malha coincidirem com os do documento."""
        return op_primitive_to_sw(session, primitive)

    @mcp.tool()
    def mesh_freeform_to_step(out_step: str, region: dict | None = None,
                              grid_u: int = 40, grid_v: int = 40,
                              tol_mm: float = 0.05,
                              extend_mm: float = 0.0) -> dict[str, Any]:
        """Ajusta uma superfície B-spline numa região FREEFORM da malha ativa
        (parede/nervura de fundição) e grava um STEP com a superfície — importe
        no SolidWorks com Inserir > Recurso > Importado ou abrindo o STEP.
        extend_mm estende a superfície além da região (continua a borda) para
        ela sobrar da peça e servir de ferramenta de RECORTE (Cortar com
        superfície). Funciona em região tipo 'altura sobre um plano'; se
        dobrar demais, divida em patches (region por box/labels). Retorna
        desvio rms/p95/max do ajuste contra os pontos do scan. NÃO sobrescreve
        arquivo existente sem o usuário pedir."""
        return op_freeform(out_step, region, (grid_u, grid_v), tol_mm, extend_mm)

    @mcp.tool()
    def mesh_deviation_map(reference_stl: str | None = None,
                           primitive: dict | None = None,
                           region: dict | None = None,
                           max_dist_mm: float = 5.0,
                           scale_mm: float | None = None,
                           pass_fail_tol_mm: float | None = None,
                           bodies: list[str] | None = None) -> dict[str, Any]:
        """Mapa de desvio da malha ativa contra uma referência: um STL exportado
        do modelo reconstruído (export_stl) OU uma primitiva ajustada.
        reference_stl='active_doc' exporta o documento aberto NAS COORDENADAS
        DA PEÇA (sem realinhar — é a medida honesta do modelo como está;
        bodies escolhe os corpos, senão vão todos os visíveis: oculte a malha
        de scan do documento, senão ela vira a referência).
        Gera PNG com 4 vistas (vermelho = scan acima, azul = abaixo, cinza =
        SEM DADO — lacuna de scan não é interpolada) + estatísticas (rms, p95).
        scale_mm fixa a escala de cor (ex.: 0.5 para ±0,5 mm).
        pass_fail_tol_mm ativa o modo Passa/Falha: verde = dentro de ±tol,
        gradiente até 5x a tolerância, e retorna 'dentro_tolerancia'."""
        if reference_stl == "active_doc":
            return op_deviation_active_doc(
                session, bodies, region=region, max_dist_mm=max_dist_mm,
                scale_mm=scale_mm, pass_fail_tol_mm=pass_fail_tol_mm)
        return op_deviation(reference_stl, primitive, region, max_dist_mm,
                            scale_mm, pass_fail_tol_mm)
