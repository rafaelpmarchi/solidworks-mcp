"""Invocação fail-fast: com_error vira ComCallError com contexto completo."""

import pytest
import pywintypes

from swmcp.com.invoke import ComCallError, com_call, com_get

RPC_UNAVAILABLE = -2147023174  # 0x800706BA


class FakeCom:
    """Objeto que imita um proxy COM para os testes."""

    def ok(self, x):
        return x + 1

    def quebra(self, *args):
        raise pywintypes.com_error(-2147352567, "Exception occurred.", (0, "SldWorks", "detalhe do servidor", None, 0, RPC_UNAVAILABLE), None)

    @property
    def prop_quebrada(self):
        raise pywintypes.com_error(RPC_UNAVAILABLE, "RPC server unavailable", None, None)


def test_sucesso_retorna_valor():
    assert com_call(FakeCom(), "ok", 41) == 42


def test_falha_vira_comcallerror_com_metodo_e_hresult():
    with pytest.raises(ComCallError) as info:
        com_call(FakeCom(), "quebra", "arg1", 2)
    err = info.value
    assert err.target == "quebra"
    assert "arg1" in err.args_repr
    assert err.hresult == RPC_UNAVAILABLE  # excepinfo[5] prevalece
    assert "0x800706BA" in str(err)
    assert "detalhe do servidor" in str(err)


def test_metodo_inexistente_nao_e_mascarado():
    # getattr defensivo é proibido (RNF-01): atributo errado é bug nosso
    with pytest.raises(AttributeError):
        com_call(FakeCom(), "nao_existe")


def test_is_disconnected_reconhece_hresults_de_queda():
    with pytest.raises(ComCallError) as info:
        com_get(FakeCom(), "prop_quebrada")
    assert info.value.is_disconnected


def test_erro_generico_nao_e_disconnected():
    err = ComCallError("m", (), -2147352567, "x")
    assert not err.is_disconnected
