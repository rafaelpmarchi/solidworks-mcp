"""Referências de montagem ao vivo: mate por geometria, listar, replicar e
substituir (exige SolidWorks).

Chapa 100x50x10 com dois furos Ø10 e um pino Ø10x30. O pino é posicionado no
furo 1 por concêntrico + coincidente escolhendo as entidades pela geometria;
replicate_component leva o pino para o furo 2 seguindo as mesmas referências;
replace_component troca o arquivo da cópia. Arquivos na pasta temporária do
pytest; tudo é fechado no fim.
"""

import shutil

import pytest

from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import SwSession, cast_to
from swmcp.com.wrappers import assembly as a
from swmcp.com.wrappers import assembly_refs as r
from swmcp.com.wrappers import holes as h
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()


def _title(app):
    return com_call(cast_to(com_get(app, "ActiveDoc"), "IModelDoc2"), "GetTitle")


def _save(app, path):
    model = cast_to(com_get(app, "ActiveDoc"), "IModelDoc2")
    assert com_call(cast_to(com_get(model, "Extension"), "IModelDocExtension"),
                    "SaveAs3", str(path), 0, 1, None, None, 0, 0)


def test_mate_listar_replicar_substituir(session, tmp_path):
    abertos = []
    try:
        def pecas(app):
            o.new_document(app, "part")
            m.insert_sketch(app, "Plano superior")
            m.sketch_rectangle(app, 0, 0, 100, -50)
            m.extrude(app, 10)
            h.hole_wizard(app, 25, 10, 25, 10, diameter_mm=10, through_all=True,
                          model_positions_mm=[[25, 10, 25], [75, 10, 25]])
            _save(app, tmp_path / "chapa.SLDPRT")
            abertos.append(_title(app))
            o.new_document(app, "part")
            m.insert_sketch(app, "Plano superior")
            m.sketch_circle(app, 0, 0, 10)
            m.extrude(app, 30)
            _save(app, tmp_path / "pino.SLDPRT")
            abertos.append(_title(app))
        session.run(pecas)
        shutil.copy(tmp_path / "pino.SLDPRT", tmp_path / "pino2.SLDPRT")

        def monta(app):
            o.new_document(app, "assembly")
            abertos.append(_title(app))
            chapa = a.insert_component(app, str(tmp_path / "chapa.SLDPRT"), 0, 0, 0, fixed=True)["component"]
            pino = a.insert_component(app, str(tmp_path / "pino.SLDPRT"), 27, 14, 24)["component"]
            # concêntrico: cilindro do pino × furo 1, achados pela geometria
            r.select_component_entity(app, pino, "face", [27, 20, 24], [0, 1, 0], radius_mm=5)
            r.select_component_entity(app, chapa, "face", [25, 5, 25], [0, 1, 0], radius_mm=5, append=True)
            a.add_mate(app, "concentric")
            # coincidente: fundo do pino × topo da chapa
            r.select_component_entity(app, pino, "face", [25, 14, 25], [0, 1, 0])
            r.select_component_entity(app, chapa, "face", [50, 10, 40], [0, 1, 0], append=True)
            a.add_mate(app, "coincident", alignment="anti_aligned")
            origem = r.component_transform(app, pino)["origin_mm"]
            mates = r.list_mates(app, pino)
            copia = r.replicate_component(app, pino, [[50, 0, 0]])
            nome_copia = copia["copies"][0]["component"]
            troca = r.replace_component(app, nome_copia, str(tmp_path / "pino2.SLDPRT"))
            depois = r.component_transform(app, troca["replaced"][0]["component"])["origin_mm"]
            return origem, mates, copia, troca, depois, a.check_interference(app)
        origem, mates, copia, troca, depois, interf = session.run(monta)

        assert origem == pytest.approx([25, 10, 25], abs=1e-3)
        assert sorted(mt["type"] for mt in mates) == ["coincident", "concentric"]
        assert all(len(mt["entities"]) == 2 for mt in mates)
        c = copia["copies"][0]
        assert c["mates_ok"] == 2 and c["moved_mm"] == 0 and not c["rotated"]
        assert copia["mate_errors"] == []
        assert troca["replaced"][0]["same_place"] and troca["mate_errors"] == []
        assert depois == pytest.approx([75, 10, 25], abs=1e-3)
        assert interf == []
    finally:
        for titulo in reversed(abertos):
            session.run(lambda app, t=titulo: com_call(app, "CloseDoc", t))
        # a troca carregou o pino2 sem ele ter sido aberto por nós
        session.run(lambda app: com_call(app, "CloseDoc", "pino2.SLDPRT"))
