"""Peça de revolução sintética: eixo, perfil e furos em padrão (sem scanner)."""

import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from swengine import align, revolution  # noqa: E402

RNG = np.random.default_rng(11)
NOISE = 0.02

# perfil (r, z) fechado de um "disco de freio" simplificado: furo Ø50,
# flange plana, cone de ~32° e aba externa
PROFILE = [(25.0, -6.0), (25.0, 0.0), (55.0, 0.0), (75.0, 12.5), (90.0, 12.5),
           (90.0, 7.0), (75.0, 7.0), (55.0, -6.0)]


def _pose():
    rot = trimesh.transformations.random_rotation_matrix(RNG.random(3))
    rot[:3, 3] = [12.0, -7.5, 30.0]
    return rot


def _noisy(mesh):
    mesh = mesh.copy()
    mesh.vertices += RNG.normal(0, NOISE, mesh.vertices.shape)
    return mesh


@pytest.fixture(scope="module")
def revolved():
    """Sólido de revolução fino (malha densa), posto numa pose qualquer."""
    # o revolve do trimesh trata a lista como polilinha ABERTA: repete o 1º
    # ponto para ter a face de baixo
    m = trimesh.creation.revolve(np.array(PROFILE + PROFILE[:1]), sections=360)
    m = m.subdivide()
    pose = _pose()
    m.apply_transform(pose)
    return _noisy(m), pose


def _plate_with_holes():
    """Placa Ø120 × 6 com furo central Ø30 e 7 furos Ø10 no PCD 80 (8
    posições a cada 45° a partir de 10°, a de 190° vazia)."""
    from scipy.spatial import Delaunay

    furos = [(0.0, 0.0, 15.0)]
    for k in range(8):
        if k == 4:
            continue
        ang = np.radians(10 + 45 * k)
        furos.append((40 * np.cos(ang), 40 * np.sin(ang), 5.0))
    pts = [[60 * np.cos(t), 60 * np.sin(t)] for t in np.linspace(0, 2 * np.pi, 720, endpoint=False)]
    for cx, cy, r in furos:
        n = max(90, int(2 * np.pi * r / 0.4))
        pts += [[cx + r * np.cos(t), cy + r * np.sin(t)] for t in np.linspace(0, 2 * np.pi, n, endpoint=False)]
    g = np.mgrid[-60:60:1.2, -60:60:1.2].reshape(2, -1).T
    ok = np.hypot(g[:, 0], g[:, 1]) < 59.5
    for cx, cy, r in furos:
        ok &= np.hypot(g[:, 0] - cx, g[:, 1] - cy) > r + 0.5
    pts = np.vstack([pts, g[ok]])
    tri = Delaunay(pts).simplices
    c = pts[tri].mean(1)
    keep = np.hypot(c[:, 0], c[:, 1]) < 60
    for cx, cy, r in furos:
        keep &= np.hypot(c[:, 0] - cx, c[:, 1] - cy) > r
    m = trimesh.creation.extrude_triangulation(pts, tri[keep], 6.0)
    m.merge_vertices()
    # paredes dos furos e a borda com faixas finas (o scan tem pontos lá)
    m = m.subdivide_to_size(1.0)
    return m


@pytest.fixture(scope="module")
def plate():
    m = _plate_with_holes()
    pose = _pose()
    m.apply_transform(pose)
    return _noisy(m), pose


def _axis_from_pose(pose):
    return pose[:3, 3].copy(), pose[:3, 2].copy()


def _dist_point_line(p, c, a):
    d = np.asarray(p) - c
    return float(np.linalg.norm(d - a * (d @ a)))


def test_eixo_do_solido_de_revolucao(revolved):
    mesh, pose = revolved
    c, a = _axis_from_pose(pose)
    r = revolution.fit_axis(mesh)
    ang = np.degrees(np.arccos(abs(np.dot(r["axis_dir"], a))))
    assert ang < 0.2
    assert _dist_point_line(r["axis_point"], c, a) < 0.05
    assert r["aviso"] is None


def test_eixo_da_placa_ignora_os_furos_fora_do_centro(plate):
    mesh, pose = plate
    c, a = _axis_from_pose(pose)
    r = revolution.fit_axis(mesh)
    ang = np.degrees(np.arccos(abs(np.dot(r["axis_dir"], a))))
    assert ang < 0.3
    assert _dist_point_line(r["axis_point"], c, a) < 0.1


def test_align_axis_leva_o_eixo_para_z(revolved):
    mesh, pose = revolved
    m, info = align.align_axis(mesh, z_origin="min")
    out = align.apply_alignment(mesh, m)
    # na origem e de pé: o furo Ø50 fica centrado e a peça começa em Z=0
    xy = out.vertices[:, :2]
    bore = np.abs(np.hypot(xy[:, 0], xy[:, 1]) - 25.0) < 0.1
    assert abs(xy[bore].mean(0)).max() < 0.1
    assert abs(out.bounds[0][2]) < 0.1
    assert abs(out.extents[2] - 18.5) < 0.2


def test_perfil_recupera_os_cantos(revolved):
    mesh, pose = revolved
    c, a = _axis_from_pose(pose)
    r = revolution.revolve_profile(mesh, c, a, min_coverage=0.4)
    v = np.array(r["vertices_rz"])
    assert r["closed"]
    assert r["rms_mm"] < 0.05
    # cada canto do perfil de origem tem um vértice a menos de 0,3 mm
    for p in PROFILE:
        assert np.min(np.linalg.norm(v - p, axis=1)) < 0.3, p


def test_fechamento_por_espessura():
    # um lado só (L invertido): a parede interna fica 5 mm para dentro
    verts = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 10.0]])
    normais = np.array([[0.0, 1.0], [-1.0, 0.0]])
    poly, aviso = revolution._offset_closure(verts, normais, 5.0)
    assert aviso is None
    inner = poly[len(verts):-1][::-1]
    assert np.allclose(inner, [[0, -5], [25, -5], [25, 10]], atol=1e-9)


def test_furos_padrao_e_furo_que_falta(plate):
    mesh, pose = plate
    c, a = _axis_from_pose(pose)
    r = revolution.detect_holes(mesh, c, a)
    reais = [h for h in r["holes"] if h["has_wall"]]
    centro = [h for h in reais if h["radius_from_axis_mm"] < 1]
    assert len(centro) == 1 and abs(centro[0]["diameter_mm"] - 30.0) < 0.15
    grupo = next(g for g in r["groups_by_size"] if abs(g.get("diameter_mm", 0) - 10) < 0.2)
    assert grupo["count"] == 7
    assert abs(grupo["pcd_mm"] - 80.0) < 0.1
    pat = grupo["pattern"]
    assert pat["positions"] == 8 and abs(pat["pitch_deg"] - 45.0) < 1e-6
    assert len(pat["missing"]) == 1


def test_padrao_angular():
    p = revolution._angular_pattern([27.4, 87.4, 147.4, 207.4, 327.4], 1.0)
    assert p["positions"] == 6 and p["missing"] == [4]
    assert abs(p["start_deg"] - 27.4) < 0.01
    assert revolution._angular_pattern([0.0, 10.0, 77.0], 0.2)["positions"] > 36
