"""Pórtico, canal inclinado, esboço em face, validação, leitura de furos, pastas,
propriedades e rascunho — ao vivo (exige SolidWorks).

Só peças descartáveis, fechadas sem salvar; a única gravação é num tmp_path.
Bloco de 100×100×80 com um ressalto de 0,5 mm na face +Y que o rebaixo do
pórtico invade — o caso do 3-50200-92000 que deixava uma aba de ressalto.
"""

import math
import os

import pytest

from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import SwSession
from swmcp.com.wrappers import channels as ch
from swmcp.com.wrappers import edit as e
from swmcp.com.wrappers import holes as h
from swmcp.com.wrappers import inspect as i
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o
from swmcp.com.wrappers import repair as r
from swmcp.com.wrappers import script as sc
from swmcp.com.wrappers import sketch_define as sd
from swmcp.com.wrappers import validate as v
from swmcp.domain import ports

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


def _titulo(session):
    return session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))


@pytest.fixture
def bloco(session):
    """Bloco 100×100×80 (Z de 0 a 80 ou de -80 a 0) com ressalto 0,5 na face +Y."""
    session.run(lambda app: o.new_document(app, "part"))
    titulo = _titulo(session)
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    session.run(lambda app: m.sketch_rectangle(app, -50, -50, 50, 50))
    session.run(sd.fully_define_sketch)          # como a tool extrude faz
    session.run(lambda app: m.extrude(app, 80.0))
    caixa = session.run(lambda app: h.measure_bodies(app))[0]["box_mm"]
    z0, z1 = caixa[2], caixa[5]
    zm = (z0 + z1) / 2
    face_y = [0, 50, zm]
    session.run(lambda app: ch.sketch_on_face(
        app, face_y, rectangles_mm=[[[-40, 50, zm - 20], [0, 50, zm + 20]]]))
    session.run(sd.fully_define_sketch)
    session.run(lambda app: m.extrude(app, 0.5))
    nome_ressalto = session.run(lambda app: com_call(ch._last_feature(app), "Name"))
    yield {"title": titulo, "z0": z0, "z1": z1, "zm": zm, "pad": nome_ressalto}
    session.run(lambda app: com_call(app, "CloseDoc", titulo))


def test_ressalto_por_coordenadas_da_peca(session, bloco):
    caixa = session.run(lambda app: h.measure_bodies(app))[0]["box_mm"]
    assert caixa[4] == pytest.approx(50.5)       # ressalto 0,5 só na face +Y
    assert caixa[1] == pytest.approx(-50.0)


def test_ponto_fora_do_plano_da_face_e_recusado(session, bloco):
    with pytest.raises(Exception, match="do plano do esboço"):
        session.run(lambda app: ch.sketch_on_face(
            app, [20, 50, bloco["zm"]], circles_mm=[[20, 45, bloco["zm"], 10]]))
    aberto = session.run(lambda app: com_get(com_get(m._model(m._active_doc(app)), "SketchManager"),
                                             "ActiveSketch"))
    assert aberto is None


def test_portico_corta_o_ressalto_e_canal_inclinado_chega_no_portico(session, bloco):
    zm = bloco["zm"]
    antes = session.run(lambda app: h._volume_mm3(app))
    p = session.run(lambda app: ch.port_hole(app, [5, 50, zm], "G3/4", "P G3/4 teste",
                                             spot_depth_mm=1, channel_diameter_mm=11.75,
                                             channel_length_mm=60))
    assert p["feature"] == "P G3/4 teste" and p["sketch_fully_defined"]
    # o rebaixo Ø33 atravessa o ressalto: a face cilíndrica vai de y=50,5 até 49
    rebaixo = session.run(lambda app: i.list_faces(app, "cylinder", 33.0))
    assert len(rebaixo) == 1
    assert rebaixo[0]["box_mm"][4] == pytest.approx(50.5) and rebaixo[0]["box_mm"][1] == pytest.approx(49.0)
    # o mesmo perfil, mas começando na face (s=0) em vez de 5 mm fora
    dentro = ports.profile_volume_mm3([(0, 0), (0, 16.5), *ports.port_profile(
        "G3/4", 1, None, 11.75, 60)[2:]])
    removido = antes - session.run(lambda app: h._volume_mm3(app))
    aba = 0.5 * 16.5 ** 2 * math.pi  # teto: metade do rebaixo por cima do ressalto
    assert dentro - 1 < removido < dentro + aba

    c = session.run(lambda app: ch.angled_channel(app, [-20, -50, zm], 7.0, "Canal Ø7 teste",
                                                  target_mm=[5, -5, zm]))
    assert c["plane_created"] is True and c["removed_mm3"] > 0
    assert c["length_mm"] == pytest.approx(math.hypot(25, 45) + 1.5)

    val = session.run(lambda app: v.validate_model(app))
    assert val["ok"], val["problems"]
    assert val["sketches_not_fully_defined"] == []

    # pastas: ressalto + pórtico, e o canal
    org = session.run(lambda app: r.organize_tree(app, [
        {"name": "Face +Y", "features": [bloco["pad"], "P G3/4 teste"]},
        {"name": "Canais", "features": ["Canal Ø7 teste"]}]))
    assert org["ok"] and [f["name"] for f in org["folders"]] == ["Face +Y", "Canais"], org
    val = session.run(lambda app: v.validate_model(app))
    assert val["ok"], val


def test_eixo_fora_da_peca_nao_deixa_nada(session, bloco):
    antes = session.run(lambda app: m.list_planes(app))
    with pytest.raises(Exception, match="não removeu material"):
        session.run(lambda app: ch.angled_channel(app, [300, 300, bloco["zm"]], 7.0, "fora",
                                                  direction=[1, 0, 0], length_mm=10))
    assert session.run(lambda app: m.list_planes(app)) == antes
    assert session.run(lambda app: i.check_rebuild_errors(app))["clean"]


def test_dump_holes_da_posicao_na_peca(session, bloco):
    topo = bloco["z1"] if abs(bloco["z1"]) > abs(bloco["z0"]) else bloco["z0"]
    session.run(lambda app: h.hole_wizard(app, 0, 0, topo, 15, size="M8x1.25", hole_type="tap",
                                          thread_depth_mm=12,
                                          model_positions_mm=[[20, 30, topo], [-20, -30, topo]]))
    furos = session.run(lambda app: v.dump_holes(app))
    assert len(furos) == 1
    pos = sorted(furos[0]["positions_mm"])
    assert pos == [pytest.approx([-20, -30, topo], abs=1e-3), pytest.approx([20, 30, topo], abs=1e-3)]
    entra = furos[0]["drill_direction"]
    assert abs(entra[2]) == pytest.approx(1.0) and math.copysign(1, entra[2]) == -math.copysign(1, topo)


def test_lote_relata_por_item_e_vista_da_face(session, bloco, tmp_path):
    zm = bloco["zm"]
    lote = session.run(lambda app: ch.batch_holes(app, [
        {"kind": "port", "face_point_mm": [-30, -50, zm], "size": "G1/4", "name": "S G1/4 lote",
         "spot_depth_mm": 5.5},
        {"kind": "channel", "start_mm": [0, 0, 9999], "diameter_mm": 5, "name": "ruim",
         "direction": [0, 0, 1], "length_mm": 5},
        {"kind": "wizard", "face_x_mm": 50, "face_y_mm": 0, "face_z_mm": zm, "depth_mm": 10,
         "diameter_mm": 6, "name": "Ø6 lote", "model_positions_mm": [[50, 10, zm]]},
    ]))
    assert [it["ok"] for it in lote["items"]] == [True, False, True], lote
    val = session.run(lambda app: v.validate_model(app))
    assert val["ok"], val
    foto = session.run(lambda app: o.view_face(app, [0, -1, 0], str(tmp_path / "face.png")))
    assert os.path.getsize(foto["path"]) > 1000


def test_copia_propriedades_de_outra_peca(session, tmp_path):
    session.run(lambda app: o.new_document(app, "part"))
    fonte = _titulo(session)
    session.run(lambda app: e.set_custom_property(app, "Cliente", "Siemens Energy"))
    caminho = str(tmp_path / "fonte.SLDPRT")
    session.run(lambda app: o.save_as(app, caminho))
    session.run(lambda app: com_call(app, "CloseDoc", os.path.basename(caminho)))
    session.run(lambda app: o.new_document(app, "part"))
    alvo = _titulo(session)
    try:
        res = session.run(lambda app: e.copy_properties_from(app, caminho))
        assert [c["name"] for c in res["copied"]] == ["Cliente"]
        assert _titulo(session) == alvo          # a fonte fechou e o alvo voltou a ser o ativo
    finally:
        session.run(lambda app: com_call(app, "CloseDoc", alvo))
    assert fonte


def test_rascunho_nao_toca_no_documento_ativo(session, bloco):
    antes = session.run(lambda app: m.list_planes(app))
    res = session.run(lambda app: sc.run_script(app, (
        "com_call(doc, 'ClearSelection2', True)\n"
        "result = [com_call(doc, 'GetTitle'), len(tree_order())]"), scratch=True))
    assert res["ok"] and res["result"][0] != bloco["title"]
    assert _titulo(session) == bloco["title"]
    assert session.run(lambda app: m.list_planes(app)) == antes
