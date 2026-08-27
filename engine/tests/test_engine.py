"""Testes do motor com malhas sintéticas (sem SolidWorks, sem scanner)."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from swengine import align, deviation, fit, mesh_io, section, segment  # noqa: E402
from swengine.region import region_vertex_mask  # noqa: E402

RNG = np.random.default_rng(3)
NOISE = 0.02  # mm, ~ruído do Raptor Pro


# ------------------------------------------------------------- fixtures

def _reproject_cylinder(mesh, radius, height):
    r_xy = np.linalg.norm(mesh.vertices[:, :2], axis=1)
    lateral = (np.abs(mesh.vertices[:, 2]) < height / 2 - 0.01) & (r_xy > 1.0)
    mesh.vertices[lateral, :2] *= (radius / r_xy[lateral])[:, None]
    return mesh


@pytest.fixture(scope="module")
def cylinder_mesh():
    c = trimesh.creation.cylinder(radius=25.0, height=80.0, sections=96)
    c = _reproject_cylinder(c.subdivide().subdivide(), 25.0, 80.0)
    c.vertices += RNG.normal(0, NOISE, c.vertices.shape)
    c.merge_vertices()
    return c


@pytest.fixture(scope="module")
def sphere_mesh():
    s = trimesh.creation.icosphere(subdivisions=4, radius=12.5)
    s.vertices += RNG.normal(0, NOISE, s.vertices.shape)
    return s


@pytest.fixture(scope="module")
def cast_block():
    """Bloco 60x40x20 com o topo 'fundido' (rugoso) e o resto usinado."""
    b = trimesh.creation.box(extents=[60.0, 40.0, 20.0])
    for _ in range(4):
        b = b.subdivide()
    b.merge_vertices()
    top = b.vertices[:, 2] > 9.9
    bump = np.sin(b.vertices[top, 0] * 2.1) * np.cos(b.vertices[top, 1] * 1.7)
    b.vertices[top, 2] += 0.6 * bump + RNG.normal(0, 0.15, top.sum())
    b.vertices += RNG.normal(0, NOISE, b.vertices.shape)
    return b


# ------------------------------------------------------------- mesh_io

def test_info_and_units_warning(cylinder_mesh, tmp_path):
    p = tmp_path / "c.stl"
    cylinder_mesh.export(p)
    m = mesh_io.load_mesh(str(p))
    info = mesh_io.mesh_info(m)
    assert info["faces"] > 1000
    assert abs(info["extents_mm"][2] - 80.0) < 0.5
    tiny = trimesh.creation.box(extents=[0.05, 0.05, 0.08])  # "metros"
    assert "aviso_unidade" in mesh_io.mesh_info(tiny)


def test_decimate(cylinder_mesh):
    out = mesh_io.decimate(cylinder_mesh, 2000)
    assert len(out.faces) <= 2200
    assert abs(out.extents[2] - cylinder_mesh.extents[2]) < 1.0


# ------------------------------------------------------------- region

def test_region_masks(cylinder_mesh):
    full = region_vertex_mask(cylinder_mesh, None)
    assert full.all()
    top = region_vertex_mask(cylinder_mesh,
                             {"axis_range": {"axis": "z", "min": 39.5}})
    assert 0 < top.sum() < len(full)
    with pytest.raises(ValueError):
        region_vertex_mask(cylinder_mesh,
                           {"axis_range": {"axis": "z", "min": 500}})


# ------------------------------------------------------------- align

def test_align_pca_recenters(cylinder_mesh):
    moved = cylinder_mesh.copy()
    moved.apply_transform(trimesh.transformations.euler_matrix(0.4, 0.9, 0.2))
    moved.apply_translation([100.0, -50.0, 30.0])
    out, matrix = align.align(moved, "pca")
    assert np.abs(out.vertices.mean(axis=0)).max() < 1.0
    # eixo do cilindro (maior variância... altura 80 > diâmetro 50) vira X
    assert abs(out.extents[0] - 80.0) < 1.0


def test_align_plane_to_xy(cast_block):
    moved = cast_block.copy()
    moved.apply_transform(trimesh.transformations.euler_matrix(0.3, 0.1, 0.0))
    out, _ = align.align(moved, "plane_to_xy",
                         region={"axis_range": {"axis": "z", "min": -100,
                                                "max": 100}})
    # alguma face plana assentou em z=0; extents preservados
    assert abs(sorted(out.extents)[0] - 20.0) < 2.5


# ------------------------------------------------------------- fit

def test_fit_cylinder(cylinder_mesh):
    r = fit.fit_primitive(cylinder_mesh, "cylinder", tolerance_mm=0.15)
    assert abs(r["radius"] - 25.0) < 0.05
    assert abs(abs(r["axis"][2]) - 1.0) < 1e-3
    assert abs(r["height"] - 80.0) < 1.0
    assert r["rms_mm"] < 0.05


def test_fit_sphere(sphere_mesh):
    r = fit.fit_primitive(sphere_mesh, "sphere", tolerance_mm=0.15)
    assert abs(r["radius"] - 12.5) < 0.05
    assert np.abs(np.asarray(r["center"])).max() < 0.1


def test_fit_plane_region(cylinder_mesh):
    r = fit.fit_primitive(
        cylinder_mesh, "plane",
        region={"axis_range": {"axis": "z", "min": 39.8}}, tolerance_mm=0.15)
    assert abs(abs(r["normal"][2]) - 1.0) < 1e-3
    assert abs(r["point"][2] - 40.0) < 0.1


def test_fit_auto_prefers_plane_on_flat(cylinder_mesh):
    r = fit.fit_primitive(
        cylinder_mesh, "auto",
        region={"axis_range": {"axis": "z", "min": 39.8}}, tolerance_mm=0.15)
    assert r["kind"] == "plane"


def test_fit_constrained_cylinder(cylinder_mesh):
    # malha levemente rotacionada; eixo travado em Z ignora a rotação do fit
    moved = cylinder_mesh.copy()
    moved.apply_transform(trimesh.transformations.euler_matrix(0.01, 0.01, 0))
    r = fit.fit_primitive(moved, "cylinder", tolerance_mm=0.3,
                          constraint_axis=[0, 0, 1])
    assert r["constrained"]
    assert r["axis"] == [0.0, 0.0, 1.0]
    assert abs(r["radius"] - 25.0) < 0.2


def test_fit_constrained_plane(cylinder_mesh):
    r = fit.fit_primitive(
        cylinder_mesh, "plane",
        region={"axis_range": {"axis": "z", "min": 39.8}},
        tolerance_mm=0.15, constraint_axis=[0, 0, 1])
    assert r["constrained"] and abs(r["point"][2] - 40.0) < 0.1


def test_deviation_pass_fail(cylinder_mesh, tmp_path):
    signed = deviation.deviation_to_primitive(
        cylinder_mesh,
        {"kind": "cylinder", "point": [0, 0, 0], "axis": [0, 0, 1],
         "radius": 25.0}, max_dist_mm=2.0)
    png = tmp_path / "pf.png"
    r = deviation.render_deviation(cylinder_mesh, signed, str(png),
                                   pass_fail_tol_mm=0.1)
    assert png.exists()
    assert r["dentro_tolerancia"] > 0.95  # ruído 0.02 << tol 0.1


def test_fit_rejects_garbage():
    noise = trimesh.Trimesh(
        vertices=RNG.uniform(-50, 50, (300, 3)),
        faces=np.arange(300).reshape(100, 3), process=False)
    with pytest.raises(ValueError):
        fit.fit_primitive(noise, "cylinder", tolerance_mm=0.05)


# ------------------------------------------------------------- segment

def test_segment_separates_machined_from_cast(cast_block):
    labels, stats = segment.segment(cast_block, radius_mm=3.0,
                                    smooth_threshold_deg=8.0)
    assert len(stats) >= 3  # fundo + laterais lisas
    # a maior região lisa não deve conter o topo rugoso
    biggest = stats[0]["label"]
    zs = cast_block.vertices[labels == biggest][:, 2]
    assert zs.max() < 10.5  # topo rugoso (z~10+bump) ficou fora


# ------------------------------------------------------------- section

def test_section_circle(cylinder_mesh):
    out = section.section(cylinder_mesh, "z", [0.0], tol_mm=0.1)
    loops = out[0]["loops"]
    assert len(loops) == 1 and loops[0]["closed"]
    arcs = [e for e in loops[0]["entities"] if e["type"] == "arc"]
    assert arcs and abs(arcs[0]["radius"] - 25.0) < 0.1


def test_section_rectangle(cast_block):
    out = section.section(cast_block, "z", [0.0], tol_mm=0.15)
    ents = out[0]["loops"][0]["entities"]
    lines = [e for e in ents if e["type"] == "line"]
    assert len(lines) >= 4


def test_section_recognizes_circle(cylinder_mesh):
    out = section.section(cylinder_mesh, "z", [0.0], tol_mm=0.1)
    shape = out[0]["loops"][0].get("shape")
    assert shape and shape["shape"] == "circle"
    assert abs(shape["radius"] - 25.0) < 0.1


def test_section_recognizes_rectangle(cast_block):
    out = section.section(cast_block, "z", [0.0], tol_mm=0.15)
    shape = out[0]["loops"][0].get("shape")
    assert shape and shape["shape"] == "rectangle"
    assert shape["axis_aligned"]
    assert abs((shape["max"][0] - shape["min"][0]) - 60.0) < 0.5


def test_recognize_slot_and_hexagon():
    # slot: 2 linhas paralelas + 2 arcos de meia-largura
    slot = [
        {"type": "line", "p1": [0, 5], "p2": [30, 5]},
        {"type": "line", "p1": [30, -5], "p2": [0, -5]},
        {"type": "arc", "center": [30, 0], "radius": 5.0,
         "p1": [30, 5], "p2": [30, -5]},
        {"type": "arc", "center": [0, 0], "radius": 5.0,
         "p1": [0, -5], "p2": [0, 5]},
    ]
    r = section.recognize_loop(slot, closed=True)
    assert r and r["shape"] == "slot" and abs(r["width"] - 10.0) < 0.1

    # hexágono regular circunscrito em raio 10
    ang = np.linspace(0, 2 * np.pi, 7)[:-1]
    verts = np.column_stack([10 * np.cos(ang), 10 * np.sin(ang)])
    hexa = [{"type": "line", "p1": verts[i].tolist(),
             "p2": verts[(i + 1) % 6].tolist()} for i in range(6)]
    r = section.recognize_loop(hexa, closed=True)
    assert r and r["shape"] == "polygon" and r["sides"] == 6
    assert abs(r["circumradius"] - 10.0) < 0.1


def test_section_miss(cylinder_mesh):
    out = section.section(cylinder_mesh, "z", [500.0])
    assert "aviso" in out[0]


# ------------------------------------------------------------- deviation

def test_deviation_to_primitive(cylinder_mesh, tmp_path):
    signed = deviation.deviation_to_primitive(
        cylinder_mesh,
        {"kind": "cylinder", "point": [0, 0, 0], "axis": [0, 0, 1],
         "radius": 25.0}, max_dist_mm=2.0)
    stats = deviation.deviation_stats(signed)
    assert stats["rms_mm"] < 0.1          # lateral no ruído
    assert stats["cobertura"] < 1.0       # tampas viram 'sem dado', não zero
    png = tmp_path / "dev.png"
    r = deviation.render_deviation(cylinder_mesh, signed, str(png))
    assert png.exists() and r["png"] == str(png)


def test_deviation_mesh_to_mesh(cylinder_mesh):
    ref = cylinder_mesh.copy()
    scan = cylinder_mesh.copy()
    scan.apply_translation([0.3, 0.0, 0.0])  # desvio conhecido
    signed = deviation.deviation_to_mesh(scan, ref, max_dist_mm=5.0)
    stats = deviation.deviation_stats(signed)
    assert stats["cobertura"] > 0.99
    assert 0.05 < stats["rms_mm"] < 0.4


# ------------------------------------------------------------- unroll

@pytest.fixture(scope="module")
def open_cylinder_shell():
    """Casca cilíndrica aberta (sem tampas): grade theta x h, r=30, h=100."""
    nt, nh = 96, 20
    theta = np.linspace(0, 2 * np.pi, nt, endpoint=False)
    hs = np.linspace(0, 100.0, nh)
    T, H = np.meshgrid(theta, hs, indexing="ij")
    v = np.column_stack([30 * np.cos(T).ravel(), 30 * np.sin(T).ravel(),
                         H.ravel()])
    faces = []
    for i in range(nt):
        for j in range(nh - 1):
            a = i * nh + j
            b = ((i + 1) % nt) * nh + j
            faces += [[a, b, a + 1], [b, b + 1, a + 1]]
    return trimesh.Trimesh(vertices=v, faces=np.array(faces), process=False)


def test_unroll_cylinder_exact(open_cylinder_shell):
    from swengine import unroll
    r = unroll.unroll(open_cylinder_shell, method="cylinder")
    assert r["metodo"] == "cylinder"
    # largura da chapa = 2*pi*r (menos 1 passo da grade cortado na costura)
    assert abs(r["dimensoes_mm"][0] - 2 * np.pi * 30) < 30 * 2 * np.pi / 96 * 2
    assert abs(r["dimensoes_mm"][1] - 100.0) < 0.5
    assert r["distorcao_max_pct"] < 0.5  # desenvolvimento exato


def test_unroll_lscm_flat_patch(cast_block):
    from swengine import unroll
    r = unroll.unroll(cast_block, region={"axis_range": {"axis": "z",
                                                         "max": -9.9}},
                      method="lscm")
    # fundo plano 60x40: LSCM deve devolver ~o mesmo retângulo
    dims = sorted(r["dimensoes_mm"])
    assert abs(dims[1] - 60.0) < 2.0 and abs(dims[0] - 40.0) < 2.0
    assert r["distorcao_media_pct"] < 1.0


# ------------------------------------------------------------- symmetry

def test_symmetry_cylinder(cylinder_mesh):
    from swengine import symmetry
    r = symmetry.find_symmetry_plane(cylinder_mesh)
    assert r["simetrica"]
    assert r["score_mm"] < 0.2


def test_symmetry_detects_asymmetric():
    from swengine import symmetry
    rng = np.random.default_rng(5)
    # bloco com protuberância num canto só — sem plano de simetria decente
    b = trimesh.creation.box(extents=[40.0, 30.0, 20.0])
    for _ in range(3):
        b = b.subdivide()
    b.merge_vertices()
    quadrante = ((b.vertices[:, 0] > 0) & (b.vertices[:, 1] > 0)
                 & (b.vertices[:, 2] > 9.9))
    b.vertices[quadrante, 2] += 8.0
    r = symmetry.find_symmetry_plane(b, max_score_mm=0.1)
    assert not r["simetrica"]


# ------------------------------------------------------------- freeform

def test_freeform_to_step(cast_block, tmp_path):
    pytest.importorskip("OCP")
    from swengine import freeform
    step = tmp_path / "topo.step"
    r = freeform.fit_freeform(
        cast_block, {"axis_range": {"axis": "z", "min": 9.0}}, str(step),
        grid=(30, 30), tol_mm=0.1)
    assert step.exists() and step.stat().st_size > 1000
    assert r["desvio_rms_mm"] < 0.5   # parede de fundição: tolerância frouxa
    assert r["cobertura_grade"] > 0.5


def test_freeform_extends_boundaries(cast_block, tmp_path):
    pytest.importorskip("OCP")
    from swengine import freeform
    step = tmp_path / "ext.step"
    r = freeform.fit_freeform(
        cast_block, {"axis_range": {"axis": "z", "min": 9.0}}, str(step),
        grid=(30, 30), tol_mm=0.1, extend_mm=10.0)
    assert step.exists()
    assert r["extensao_mm"] == 10.0
    # topo do bloco tem ~60x40; com +10 mm por lado o span cresce ~20
    assert r["span_uv_mm"][0] > 75.0
    assert r["cobertura_grade"] > 0.5  # extensão não conta como lacuna


def test_freeform_rejects_closed_region(cylinder_mesh, tmp_path):
    pytest.importorskip("OCP")
    from swengine import freeform
    with pytest.raises(ValueError, match="height-field|dobra"):
        freeform.fit_freeform(cylinder_mesh, None,
                              str(tmp_path / "x.step"))


# ------------------------------------------------------------- viewer

def test_viewerpack_and_savemask(cylinder_mesh, tmp_path):
    import struct
    from swengine import viewer
    binp = tmp_path / "v.bin"
    r = viewer.pack(cylinder_mesh, str(binp), target_faces=2000)
    assert binp.exists() and r["faces"] <= 2600
    with open(binp, "rb") as f:
        magic, nv, nf = struct.unpack("<III", f.read(12))
    assert magic == viewer.MAGIC and nv == r["vertices"]

    # seleciona os 200 primeiros vértices do viewer -> máscara na malha cheia
    mask_p = tmp_path / "m.npy"
    s = viewer.save_mask(cylinder_mesh, str(binp), list(range(200)), str(mask_p))
    mask = np.load(mask_p)
    assert len(mask) == len(cylinder_mesh.vertices)
    assert 0 < mask.sum() < len(mask)

    # a máscara funciona como região
    from swengine.region import region_vertex_mask
    vm = region_vertex_mask(cylinder_mesh, {"mask": {"path": str(mask_p)}})
    assert vm.sum() == mask.sum()


def test_freeform_ctrl_roundtrip(cast_block, tmp_path):
    pytest.importorskip("OCP")
    from swengine import freeform
    step1 = tmp_path / "a.step"
    r = freeform.fit_freeform(
        cast_block, {"axis_range": {"axis": "z", "min": 9.0}}, str(step1),
        grid=(24, 24), tol_mm=0.1)
    ctrl = r["ctrl"]
    assert len(ctrl["poles"]) >= 4 and ctrl["udeg"] >= 3
    # edita um polo e reconstrói o STEP a partir da grade
    ctrl["poles"][2][2][2] += 1.5
    step2 = tmp_path / "b.step"
    r2 = freeform.build_step_from_ctrl(ctrl, str(step2))
    assert step2.exists() and step2.stat().st_size > 1000
    assert r2["poles"] == [len(ctrl["poles"]), len(ctrl["poles"][0])]


# ------------------------------------------------------------- CLI

def test_cli_roundtrip(cylinder_mesh, tmp_path):
    stl = tmp_path / "c.stl"
    cylinder_mesh.export(stl)
    p = subprocess.run([sys.executable, "-m", "swengine", "fit"],
                       input=json.dumps({"mesh": str(stl), "kind": "cylinder"}),
                       capture_output=True, text=True, cwd=str(ENGINE_DIR))
    out = json.loads(p.stdout)
    assert out["ok"] and abs(out["radius"] - 25.0) < 0.05


def test_cli_error_is_json(tmp_path):
    p = subprocess.run([sys.executable, "-m", "swengine", "info"],
                       input=json.dumps({"mesh": str(tmp_path / "nao_existe.stl")}),
                       capture_output=True, text=True, cwd=str(ENGINE_DIR))
    out = json.loads(p.stdout)
    assert out["ok"] is False and "erro" in out
