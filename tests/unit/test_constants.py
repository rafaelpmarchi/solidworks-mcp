"""Constantes: mapeamento de versão e decodificação de bitmasks."""

from swmcp.com import constants


def test_revision_para_ano():
    assert constants.revision_to_year("33.2.0") == 2025
    assert constants.revision_to_year("23.0.0") == 2015
    assert constants.revision_to_year("lixo") is None


def test_decode_bits_conhecidos_e_desconhecidos():
    nomes = constants.decode_bits(0x3, constants.FILE_LOAD_ERRORS)
    assert "swGenericError" in nomes
    assert "swFileNotFoundError" in nomes

    nomes = constants.decode_bits(0x40000, constants.FILE_LOAD_ERRORS)
    assert nomes == ["bits não mapeados: 0x40000"]


def test_decode_bits_zero_e_vazio():
    assert constants.decode_bits(0, constants.FILE_LOAD_WARNINGS) == []
