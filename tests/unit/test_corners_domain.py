"""Cantos de abertura (domínio puro): escolha das arestas que atravessam a chapa."""

import pytest

from swmcp.domain.corners import EdgeCandidate, select_corner_edges

N = (0.0, 1.0, 0.0)  # chapa no plano XZ, 2 mm de espessura em Y
PLANE_Y = (0.0, 1.0, 0.0)
SIDE_X = (1.0, 0.0, 0.0)
SIDE_Z = (0.0, 0.0, 1.0)


def canto(x, z, faces=(SIDE_X, SIDE_Z)):
    return EdgeCandidate(start=(x, 0.0, z), end=(x, 2.0, z), plate_normal=N, face_normals=faces)


def test_escolhe_so_arestas_retas_que_atravessam_a_espessura():
    cands = [
        canto(0.0, 0.0),
        EdgeCandidate(start=(0.0, 0.0, 0.0), end=(30.0, 0.0, 0.0), plate_normal=N,
                      face_normals=(PLANE_Y, SIDE_Z)),  # borda da abertura na face
        EdgeCandidate(start=(0.0, 0.0, 0.0), end=(0.0, 2.0, 0.0), plate_normal=N,
                      face_normals=(SIDE_X, SIDE_Z), is_line=False),  # arco
    ]
    sel = select_corner_edges(cands)
    assert [c.index for c in sel.corners] == [0]
    assert sel.skipped == {"nao_atravessa_espessura": 1, "nao_reta": 1}
    assert sel.corners[0].mid == (0.0, 1.0, 0.0)
    assert sel.corners[0].length_mm == 2.0


def test_tangente_e_ignorada_para_ser_idempotente():
    # borda de um filete já feito: as duas faces vizinhas têm a mesma normal
    ja_filetado = canto(5.0, 5.0, faces=(SIDE_X, (1.0, 0.0, 0.001)))
    costura_furo = canto(9.0, 9.0, faces=(SIDE_Z, (0.0, 0.0, -1.0)))  # sinal oposto = mesma superfície
    sel = select_corner_edges([ja_filetado, costura_furo, canto(1.0, 1.0)])
    assert len(sel.corners) == 1
    assert sel.skipped == {"tangente": 2}


def test_canto_com_uma_face_so_nao_e_descartado_como_tangente():
    sel = select_corner_edges([canto(0.0, 0.0, faces=(SIDE_X,))])
    assert len(sel.corners) == 1


def test_mesma_aresta_vinda_dos_dois_vertices_conta_uma_vez():
    ida = canto(3.0, 4.0)
    volta = EdgeCandidate(start=ida.end, end=ida.start, plate_normal=N, face_normals=ida.face_normals)
    sel = select_corner_edges([ida, volta])
    assert len(sel.corners) == 1
    assert sel.skipped == {"repetida": 1}


def test_regiao_limita_pelo_ponto_medio_e_aceita_caixa_invertida():
    cands = [canto(10.0, 10.0), canto(100.0, 100.0)]
    sel = select_corner_edges(cands, region_mm=[50.0, 5.0, 50.0, 0.0, -5.0, 0.0])
    assert [c.mid for c in sel.corners] == [(10.0, 1.0, 10.0)]
    assert sel.skipped == {"fora_da_regiao": 1}


def test_regiao_malformada_e_erro():
    with pytest.raises(ValueError):
        select_corner_edges([canto(0.0, 0.0)], region_mm=[0.0, 0.0, 0.0])


def test_resultado_ordenado_por_posicao_e_sem_degeneradas():
    zero = EdgeCandidate(start=(0.0, 0.0, 0.0), end=(0.0, 0.0, 0.0), plate_normal=N)
    sel = select_corner_edges([canto(9.0, 0.0), canto(1.0, 0.0), zero])
    assert [c.mid[0] for c in sel.corners] == [1.0, 9.0]
    assert sel.skipped == {"degenerada": 1}
