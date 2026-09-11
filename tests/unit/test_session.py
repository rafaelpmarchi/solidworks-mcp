"""Sessão: reconexão sob demanda quando o SolidWorks cai (RNF-07)."""

import pytest
import pywintypes

from swmcp.com import session as session_mod
from swmcp.com.session import SwSession, doc_type_for_path
from swmcp.com.worker import ComWorker

RPC_UNAVAILABLE = -2147023174


class DeadApp:
    """Imita um proxy cujo processo SolidWorks morreu."""

    @property
    def Visible(self):
        raise pywintypes.com_error(RPC_UNAVAILABLE, "RPC server unavailable", None, None)


class AliveApp:
    Visible = True


@pytest.fixture
def worker():
    w = ComWorker(init=lambda: None, teardown=lambda: None)
    yield w
    w.close()


def test_reconecta_quando_app_morreu(worker, monkeypatch):
    alive = AliveApp()
    monkeypatch.setattr(session_mod, "_connect", lambda: alive)
    s = SwSession(worker)
    s._app = DeadApp()

    resultado = s.run(lambda app: app)
    assert resultado is alive
    assert s._app is alive


def test_conecta_na_primeira_chamada(worker, monkeypatch):
    alive = AliveApp()
    chamadas = []

    def fake_connect():
        chamadas.append(1)
        return alive

    monkeypatch.setattr(session_mod, "_connect", fake_connect)
    s = SwSession(worker)
    assert s.run(lambda app: app) is alive
    assert s.run(lambda app: app) is alive
    assert len(chamadas) == 1  # segunda chamada reusa a conexão


def test_doc_type_por_extensao():
    assert doc_type_for_path("C:/x/peca.SLDPRT") == 1
    assert doc_type_for_path("C:/x/desenho.slddrw") == 3
    with pytest.raises(ValueError, match="extensão não suportada"):
        doc_type_for_path("C:/x/arquivo.pdf")


class _FakeDoc:
    def __init__(self, title, path, read_only=False):
        self._title, self._path, self._ro = title, path, read_only

    def GetType(self):
        return 1

    def GetPathName(self):
        return self._path

    def GetTitle(self):
        return self._title

    def GetSaveFlag(self):
        return False

    def IsOpenedReadOnly(self):
        return self._ro


class _FakeApp:
    RevisionNumber = "31.5.0"

    def __init__(self, docs):
        self._docs = docs
        self.ActiveDoc = docs[0]

    def GetDocuments(self):
        return tuple(self._docs)


def test_status_esconde_perfis_de_biblioteca():
    peca = _FakeDoc("Peça1.SLDPRT", r"C:\x\Peça1.SLDPRT")
    perfil = _FakeDoc("pipe.sldlfp", r"C:\SW\data\weldment profiles\iso\pipe.sldlfp", read_only=True)
    st = session_mod._read_status(_FakeApp([peca, perfil, perfil]))
    assert [d["title"] for d in st["open_documents"]] == ["Peça1.SLDPRT"]
    assert st["library_documents_hidden"] == 2
    assert st["active_document"]["title"] == "Peça1.SLDPRT"
    assert st["year"] == 2023
