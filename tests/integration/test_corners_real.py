"""Cantos de abertura ao vivo: chapa com fenda → filete em todos os cantos (exige SolidWorks).

Cria uma peça descartável e fecha sem salvar. Nunca toca em arquivo do usuário.
"""

import pytest

from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import SwSession
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


@pytest.fixture
def chapa_com_fenda(session):
    """Chapa 100×50×2 no plano frontal com uma fenda 30×10 passante; devolve o nome do corte."""
    session.run(lambda app: o.new_document(app, "part"))
    title = session.run(lambda app: com_call(com_get(app, "ActiveDoc"), "GetTitle"))
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    session.run(lambda app: m.sketch_rectangle(app, 0.0, 0.0, 100.0, 50.0))
    session.run(lambda app: m.extrude(app, 2.0))
    session.run(lambda app: m.insert_sketch(app, "Plano frontal"))
    session.run(lambda app: m.sketch_rectangle(app, 35.0, 20.0, 65.0, 30.0))
    corte = session.run(lambda app: m.extrude(app, 2.0, cut=True, through_all=True))
    yield corte
    session.run(lambda app: com_call(app, "CloseDoc", title))


def test_fileta_os_quatro_cantos_da_fenda_e_nao_repete(session, chapa_com_fenda):
    preview = session.run(lambda app: m.fillet_opening_corners(app, chapa_com_fenda, 2.0, preview=True))
    assert preview["fillet"] is None
    assert preview["corners"] == 4
    assert preview["thickness_mm"] == [2.0]

    feito = session.run(lambda app: m.fillet_opening_corners(app, chapa_com_fenda, 2.0))
    assert feito["corners"] == 4
    assert feito["fillet_faces"] == 4
    assert feito["error_code"] == 0

    # os cantos agora são bordas tangentes do filete: nada sobra para filetar
    with pytest.raises(ComCallError, match="nenhum canto vivo"):
        session.run(lambda app: m.fillet_opening_corners(app, chapa_com_fenda, 2.0))


def test_regiao_fora_da_fenda_nao_acha_canto(session, chapa_com_fenda):
    r = session.run(lambda app: m.fillet_opening_corners(
        app, chapa_com_fenda, 1.0, region_mm=[0, -1, 0, 10, 3, 10], preview=True))
    assert r["corners"] == 0
    assert r["skipped"].get("fora_da_regiao") == 4
