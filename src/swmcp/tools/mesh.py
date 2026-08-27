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
    _save_state({"mesh": path, "labels": None, "original": path})
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


def op_align(mode: str = "pca", region: dict | None = None) -> dict[str, Any]:
    out = _work("aligned.stl")
    r = _engine("align", {"mesh": _active_mesh(), "out": out,
                          "mode": mode, "region": _resolve_region(region)})
    state = _load_state()
    state.update({"mesh": out, "labels": None, "regioes": None})
    _save_state(state)
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


def op_deviation(reference_stl: str | None = None, primitive: dict | None = None,
                 region: dict | None = None, max_dist_mm: float = 5.0,
                 scale_mm: float | None = None,
                 pass_fail_tol_mm: float | None = None) -> dict[str, Any]:
    if not reference_stl and not primitive:
        raise RuntimeError("passe reference_stl (malha) ou primitive (fit)")
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
    import numpy as np
    kind = primitive.get("kind")
    axes = {"x": (np.array([1.0, 0, 0]), "Plano direito"),
            "y": (np.array([0, 1.0, 0]), "Plano frontal"),
            "z": (np.array([0, 0, 1.0]), "Plano superior")}

    def closest_axis(v):
        v = np.asarray(v, float)
        v = v / np.linalg.norm(v)
        for name, (ax, plane) in axes.items():
            if abs(float(v @ ax)) > 0.9986:  # ~3 graus
                return name, ax, plane
        return None

    if kind == "plane":
        hit = closest_axis(primitive["normal"])
        if not hit:
            return {"aviso": "normal oblíqua aos eixos — use run_sw_script "
                             "para plano por 3 pontos", "primitive": primitive}
        name, ax, plane = hit
        offset = float(np.asarray(primitive["point"], float) @ ax)
        feat = session.run(lambda app: m.reference_plane_offset(
            app, plane, abs(offset), flip=offset < 0))
        return {"feature": feat, "base": plane, "offset_mm": round(offset, 4)}

    if kind == "cylinder":
        hit = closest_axis(primitive["axis"])
        if not hit:
            return {"aviso": "eixo oblíquo — use run_sw_script",
                    "primitive": primitive}
        name, ax, plane = hit
        p = np.asarray(primitive["point"], float)
        height = float(primitive.get("height", 0.0))
        base = p - ax * height / 2.0
        offset = float(base @ ax)
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
    def mesh_align(mode: str = "pca", region: dict | None = None) -> dict[str, Any]:
        """Alinha a malha ativa ao sistema de coordenadas de trabalho e a torna
        a ativa. mode: 'pca' (eixos principais -> XYZ, centroide na origem),
        'bbox' (caixa mínima orientada, canto em 0,0,0) ou 'plane_to_xy'
        (ajusta um plano na 'region' e o leva para Z=0 com normal +Z — ideal
        para assentar a face usinada de referência). region (opcional):
        {"box": {"min":[x,y,z],"max":[x,y,z]}} | {"axis_range": {"axis":"z",
        "min":a,"max":b}} | {"seed": {"point":[x,y,z],"radius":r}}."""
        return op_align(mode, region)

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
                           pass_fail_tol_mm: float | None = None) -> dict[str, Any]:
        """Mapa de desvio da malha ativa contra uma referência: um STL exportado
        do modelo reconstruído (export_document) OU uma primitiva ajustada.
        Gera PNG com 4 vistas (vermelho = scan acima, azul = abaixo, cinza =
        SEM DADO — lacuna de scan não é interpolada) + estatísticas (rms, p95).
        scale_mm fixa a escala de cor (ex.: 0.5 para ±0,5 mm).
        pass_fail_tol_mm ativa o modo Passa/Falha: verde = dentro de ±tol,
        gradiente até 5x a tolerância, e retorna 'dentro_tolerancia'."""
        return op_deviation(reference_stl, primitive, region, max_dist_mm,
                            scale_mm, pass_fail_tol_mm)
