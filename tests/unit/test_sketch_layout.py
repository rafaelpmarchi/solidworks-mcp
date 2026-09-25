"""Plano de relações e cotas para pontos soltos (posição de furo)."""

from swmcp.domain.sketch_layout import plan_points


def test_par_de_furos_da_coluna():
    # coluna da prateleira: x=-22,5 (sketch invertido), par em 17,5 e 32,5
    lay = plan_points([(-22.5, 32.5), (-22.5, 17.5)])
    assert lay.columns == [[1, 0]]                     # uma coluna, ordenada por Y
    assert lay.rows == [[0], [1]]
    assert lay.horizontal_chain == [(None, 1)]         # 22,5 da origem, no furo rente ao pé
    assert lay.vertical_chain == [(None, 1), (1, 0)]   # 17,5 da origem, depois 15
    assert lay.at_origin == []


def test_quatro_furos_da_bandeja():
    pts = [(16.5, -17.5), (16.5, -32.5), (971.5, -17.5), (971.5, -32.5)]
    lay = plan_points(pts)
    assert sorted(map(sorted, lay.columns)) == [[0, 1], [2, 3]]
    assert sorted(map(sorted, lay.rows)) == [[0, 2], [1, 3]]
    # 16,5 da origem e 955 entre colunas
    assert lay.horizontal_chain == [(None, 0), (0, 2)]
    # linha mais perto da origem primeiro (17,5), depois 15
    assert lay.vertical_chain == [(None, 0), (0, 1)]


def test_cadeia_para_os_dois_lados_da_origem():
    lay = plan_points([(-50, 0.5), (10, 0.5), (80, 0.5)])
    assert lay.horizontal_chain == [(None, 1), (1, 2), (1, 0)]


def test_ponto_na_origem_nao_ganha_cota():
    lay = plan_points([(0, 0), (0, 20)])
    assert lay.at_origin == [0]
    assert lay.horizontal_chain == []                  # a coluna está na origem
    assert lay.vertical_chain == [(0, 1)]
    assert lay.vertical_to_origin == []                # já presa pela coincidência


def test_coluna_no_eixo_x0_prende_por_relacao():
    lay = plan_points([(0, 10), (0, 25)])
    assert lay.horizontal_chain == []
    assert lay.vertical_to_origin == [0]
    assert lay.vertical_chain == [(None, 0), (0, 1)]
