"""Corpos, STL nas coordenadas da peça, corte com retry e círculos em lote — ao vivo.

Peça descartável fechada sem salvar: disco Ø100 × 10 (Plano frontal, +Z) com
6 furos Ø8 no PCD 70. Tudo que a engenharia reversa da aranha de disco de
freio (02/10/2026) fez por run_sw_script.
"""

import math
import struct

import pytest

from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import SwSession
from swmcp.com.wrappers import bodies as b
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o
from swmcp.com.wrappers import script as s
from swmcp.domain.placement import rotation_matrix

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session():
    sess = SwSession()
    yield sess
    sess.close()


@pytest.fixture
def disco(session):
    session.run(lambda app: o.new_document(app, "part"))
    titulo = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    session.run(lambda app: m.sketch_circle(app, 0, 0, 100))
    session.run(lambda app: m.extrude(app, 10))
    yield titulo
    session.run(lambda app: com_call(app, "CloseDoc", titulo))


def _furos(session) -> dict:
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    circ = session.run(lambda app: m.sketch_circles(
        app, [{"r": 35, "angle_deg": 30 + 60 * k, "d": 8} for k in range(6)]))
    # no corte o sentido padrão é contra a normal (-Z): lá não há material,
    # o SolidWorks recusa e a tentativa do outro lado tem que valer
    corte = session.run(lambda app: m.extrude_detail(app, 10, cut=True, through_all=True))
    return {"circ": circ, "corte": corte}


def test_circulos_em_lote_e_corte_que_troca_de_lado(session, disco):
    r = _furos(session)
    assert r["circ"]["circles"] == 6
    assert r["circ"]["centers_mm"][0] == pytest.approx([35 * math.cos(math.radians(30)), 17.5])
    assert r["corte"]["reverse_direction_used"] is True
    assert "aviso" in r["corte"]
    corpos = session.run(b.list_bodies)
    assert len(corpos) == 1 and corpos[0]["faces"] == 3 + 6


def test_stl_nas_coordenadas_da_peca(session, disco, tmp_path):
    stl = tmp_path / "disco.stl"
    session.run(lambda app: o.export_stl(app, str(stl), overwrite=True))
    data = stl.read_bytes()
    n = struct.unpack("<I", data[80:84])[0]
    xs, zs = [], []
    for k in range(n):
        v = struct.unpack("<12f", data[84 + 50 * k: 84 + 50 * k + 48])
        xs += v[3::3]
        zs += v[5::3]
    # sem a translação para o octante positivo: centrado em X, base em Z=0
    assert min(xs) == pytest.approx(-50, abs=0.05)
    assert max(xs) == pytest.approx(50, abs=0.05)
    assert min(zs) == pytest.approx(0, abs=1e-3) and max(zs) == pytest.approx(10, abs=1e-3)


def test_mover_corpo_por_matriz_e_voltar(session, disco):
    rot = rotation_matrix((24.2, -10.5, 164.4))
    t = (113.4, 195.5, 375.4)
    mat = [*rot[0], t[0], *rot[1], t[1], *rot[2], t[2], 0, 0, 0, 1]
    ida = session.run(lambda app: b.move_body_by_matrix(app, mat))
    assert len(ida["features"]) == 4
    # inversa: Rᵀ e -Rᵀt
    rt = [[rot[j][i] for j in range(3)] for i in range(3)]
    ti = [-sum(rt[i][j] * t[j] for j in range(3)) for i in range(3)]
    inv = [*rt[0], ti[0], *rt[1], ti[1], *rt[2], ti[2], 0, 0, 0, 1]
    volta = session.run(lambda app: b.move_body_by_matrix(
        app, inv, ida["body"], expected_box_mm=ida["box_before_mm"], tolerance_mm=0.01))
    assert volta["ok"], volta


def test_giro_de_90_em_x(session, disco):
    mat = [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1]  # Rx(90): y' = -z, z' = y
    r = session.run(lambda app: b.move_body_by_matrix(
        app, mat, expected_box_mm=[-50, -10, -50, 50, 0, 50], tolerance_mm=0.01))
    assert r["ok"], r
    assert r["features"] and len(r["features"]) == 1


def test_superficie_do_lado_de_cima(session, disco):
    _furos(session)
    r = session.run(lambda app: b.surface_from_faces(app, hide_source=True,
                                                     feature_name="Lado escaneado"))
    assert r["faces_selected"] == r["faces_total"] - 1  # só a de baixo fica fora
    assert r["feature"] == "Lado escaneado"
    corpos = session.run(b.list_bodies)
    sup = [c for c in corpos if c["type"] == "surface"]
    sol = [c for c in corpos if c["type"] == "solid"]
    assert len(sup) == 1 and sup[0]["visible"]
    assert not sol[0]["visible"]


def test_visibilidade_por_padrao(session, disco):
    r = session.run(lambda app: b.set_body_visibility(app, visible=False, body_type="solid"))
    assert len(r["changed"]) == 1
    assert not session.run(b.list_bodies)[0]["visible"]
    session.run(lambda app: b.set_body_visibility(app, visible=True, pattern="*"))
    assert session.run(b.list_bodies)[0]["visible"]


def test_script_sem_dialogo_de_cota(session, disco):
    antes = session.run(lambda app: com_call(app, "GetUserPreferenceToggle", 10))
    r = session.run(lambda app: s.run_script(
        app, "result = app.GetUserPreferenceToggle(10)"))
    assert r["ok"] and r["result"] is False
    assert session.run(lambda app: com_call(app, "GetUserPreferenceToggle", 10)) == antes
