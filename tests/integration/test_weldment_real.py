"""Weldment ao vivo: perfis, membro estrutural, lista de corte (exige SolidWorks).

Cria peças descartáveis e fecha sem salvar. Nunca toca em arquivo do usuário.
"""

import pytest

from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import SwSession
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o
from swmcp.com.wrappers import weldment as w

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


@pytest.fixture
def peca_descartavel(session):
    session.run(lambda app: o.new_document(app, "part"))
    title = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    yield title
    session.run(lambda app: com_call(app, "CloseDoc", title))


def _sketch_l(session):
    sk = session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    session.run(lambda app: m.sketch_line(app, 0, 0, 300, 0))
    session.run(lambda app: m.sketch_line(app, 300, 0, 300, 200))
    session.run(m.exit_sketch)
    return sk


def test_lista_perfis_iso_traz_tamanhos(session):
    r = session.run(lambda app: w.list_profiles(app, "iso"))
    tipos = {p["type"]: p["sizes"] for p in r["profiles"]}
    assert "square tube" in tipos
    assert "20 x 20 x 2" in tipos["square tube"]


def test_membro_miter_gera_lista_de_corte_a_45(session, peca_descartavel):
    sk = _sketch_l(session)
    r = session.run(lambda app: w.insert_structural_member(app, "iso", "square tube", "20 x 20 x 2", sk, corner="miter"))
    assert r["feature"].startswith("square tube")
    assert r["segments"] == ["Linha1", "Linha2"]

    cl = session.run(lambda app: w.get_cut_list(app))
    assert cl["is_weldment"] and cl["total_bodies"] == 2
    comprimentos = sorted(i["length"] for i in cl["items"])
    assert comprimentos == [210.0, 310.0]  # miter: comprimento externo = sketch + meia largura
    assert {i["angle1_deg"] for i in cl["items"]} | {i["angle2_deg"] for i in cl["items"]} == {0.0, 45.0}


def test_membro_butt1_deixa_primeiro_segmento_inteiro(session, peca_descartavel):
    sk = _sketch_l(session)
    session.run(lambda app: w.insert_structural_member(app, "iso", "square tube", "20 x 20 x 2", sk, corner="butt1"))
    cl = session.run(lambda app: w.get_cut_list(app))
    assert sorted(i["length"] for i in cl["items"]) == [190.0, 310.0]


def test_tamanho_inexistente_lista_os_disponiveis(session, peca_descartavel):
    sk = _sketch_l(session)
    with pytest.raises(ComCallError, match="21.3 x 2.3"):
        session.run(lambda app: w.insert_structural_member(app, "iso", "pipe", "99 x 9", sk))
