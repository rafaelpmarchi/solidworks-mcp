"""Integração com SolidWorks real (gate da Fase 0).

Exige SolidWorks instalado; se não houver instância aberta, UMA é iniciada
(visível). Rodar com: pytest tests/integration -m integration
"""

import pytest

from swmcp.com.session import SwSession

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session():
    s = SwSession()
    yield s
    s.close()  # fecha o worker; NÃO fecha o SolidWorks do usuário


def test_status_reporta_versao_e_docs(session):
    status = session.status()
    assert status["connected"] is True
    assert status["revision"].count(".") == 2
    assert status["year"] is None or status["year"] >= 2015
    assert isinstance(status["open_documents"], list)


def test_status_duas_vezes_reusa_conexao(session):
    a = session.status()
    b = session.status()
    assert a["revision"] == b["revision"]
