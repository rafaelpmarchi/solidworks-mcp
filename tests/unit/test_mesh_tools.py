"""Tools mesh_* registradas e ponte com o motor íntegra (sem SolidWorks)."""

from __future__ import annotations

import pytest

from swmcp.tools import mesh

# tetraedro ASCII mínimo: 4 facetas, extents 1x1x1
_TETRA_STL = "solid t\n" + "".join(
    "facet normal 0 0 0\nouter loop\n"
    + "".join(f"vertex {v[0]} {v[1]} {v[2]}\n" for v in tri)
    + "endloop\nendfacet\n"
    for tri in [
        [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
        [(0, 0, 0), (1, 0, 0), (0, 0, 1)],
        [(0, 0, 0), (0, 1, 0), (0, 0, 1)],
        [(1, 0, 0), (0, 1, 0), (0, 0, 1)],
    ]) + "endsolid t\n"


def _engine_disponivel() -> bool:
    return mesh._backend() in ("wsl", "windows") and (
        mesh._backend() == "wsl" or mesh._ENGINE_PY.exists())


def test_mesh_tools_registradas():
    from swmcp.server import build_server

    server = build_server()
    nomes = set(getattr(server, "_tool_manager")._tools.keys()) if hasattr(
        server, "_tool_manager") else None
    if nomes is None:
        pytest.skip("estrutura interna do MCPServer mudou — só valida o build")
    esperadas = {"mesh_import", "mesh_info", "mesh_decimate", "mesh_align",
                 "mesh_segment", "mesh_fit_primitive", "mesh_section_to_sketch",
                 "mesh_primitive_to_sw", "mesh_freeform_to_step",
                 "mesh_deviation_map"}
    assert esperadas <= nomes


def test_traducao_de_caminhos():
    assert mesh._win_to_wsl(r"C:\Users\peron\scan.ply") == "/mnt/c/Users/peron/scan.ply"
    assert mesh._win_to_wsl(r"D:\dados\a b\m.stl") == "/mnt/d/dados/a b/m.stl"
    assert mesh._wsl_to_win("/mnt/c/Temp/out.stl") == r"C:\Temp\out.stl"
    # ida e volta é identidade
    p = r"C:\Temp\swengine\abc_dev.png"
    assert mesh._wsl_to_win(mesh._win_to_wsl(p)) == p
    # caminho não-/mnt fica intacto
    assert mesh._wsl_to_win("relativo/x.stl") == "relativo/x.stl"


def test_translate_args_e_result():
    args = mesh._translate_args({
        "mesh": r"C:\a\m.stl", "tolerance_mm": 0.1,
        "region": {"labels": {"path": r"C:\a\l.npy", "value": 2}}})
    assert args["mesh"] == "/mnt/c/a/m.stl"
    assert args["region"]["labels"]["path"] == "/mnt/c/a/l.npy"
    assert args["tolerance_mm"] == 0.1
    r = mesh._translate_result({"png": "/mnt/c/t/d.png",
                                "lista": ["/mnt/c/x", 5], "rms_mm": 0.02})
    assert r["png"] == r"C:\t\d.png"
    assert r["lista"] == [r"C:\x", 5]


def test_active_mesh_exige_import(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh, "_STATE_FILE", tmp_path / "state.json")
    with pytest.raises(RuntimeError, match="mesh_import"):
        mesh._active_mesh()


def test_estado_compartilhado_em_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh, "_STATE_FILE", tmp_path / "state.json")
    mesh._save_state({"mesh": r"C:\scan.ply", "labels": None})
    # outro "processo" (releitura do arquivo) enxerga a mesma malha ativa
    assert mesh._load_state()["mesh"] == r"C:\scan.ply"
    assert mesh._active_mesh() == r"C:\scan.ply"


def test_panel_rotas(monkeypatch):
    from swmcp.chat import panel

    monkeypatch.setattr(mesh, "op_status", lambda: {"mesh": None})
    monkeypatch.setattr(mesh, "op_fit",
                        lambda kind, region, tol, constraint_axis=None:
                        {"kind": kind, "tol": tol})
    assert panel.handle("status", {}) == {"mesh": None}
    r = panel.handle("fit", {"kind": "cylinder", "tolerance_mm": 0.2})
    assert r == {"kind": "cylinder", "tol": 0.2}
    with pytest.raises(ValueError, match="desconhecida"):
        panel.handle("nao-existe", {})


def test_panel_serve_file_restrito(tmp_path, monkeypatch):
    from swmcp.chat import panel

    monkeypatch.setattr(mesh, "_WORKDIR", tmp_path)
    dentro = tmp_path / "dev.png"
    dentro.write_bytes(b"png!")
    body, ctype = panel.serve_file(str(dentro))
    assert body == b"png!" and ctype == "image/png"
    # fora do workdir: recusa (segurança — sem leitura arbitrária de disco)
    fora = tmp_path.parent / "segredo.txt"
    fora.write_text("x")
    assert panel.serve_file(str(fora)) is None


def test_engine_erro_vira_runtime_error(tmp_path):
    if not _engine_disponivel():
        pytest.skip("nenhum backend do motor nesta máquina")
    with pytest.raises(RuntimeError, match="motor"):
        mesh._engine("info", {"mesh": str(tmp_path / "nao_existe.stl")})


def test_engine_info_roundtrip(tmp_path):
    if not _engine_disponivel():
        pytest.skip("nenhum backend do motor nesta máquina")
    stl = tmp_path / "tetra.stl"
    stl.write_text(_TETRA_STL)
    info = mesh._engine("info", {"mesh": str(stl)})
    assert info["faces"] == 4
    assert info["extents_mm"] == [1.0, 1.0, 1.0]
