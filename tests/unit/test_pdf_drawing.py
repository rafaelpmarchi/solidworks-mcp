"""Recorte e tabela comparativa de desenho em PDF (sem SolidWorks)."""

import pytest

pymupdf = pytest.importorskip("pymupdf")

from swmcp.services import pdf_drawing as pd  # noqa: E402


@pytest.fixture
def desenho(tmp_path):
    caminho = tmp_path / "d.pdf"
    doc = pymupdf.open()
    pg = doc.new_page(width=1000, height=500)
    pg.draw_rect(pymupdf.Rect(100, 100, 300, 200), color=(0, 0, 0), width=1)
    pg.insert_text((120, 150), "Ø200 H9", fontsize=12)
    doc.save(caminho)
    return str(caminho)


def test_escala_da_vista():
    assert pd.parse_scale("7:20") == pytest.approx(0.35)
    assert pd.parse_scale("1:1") == 1.0 and pd.parse_scale(None) is None
    assert pd.parse_scale(0.4) == 0.4


def test_retangulo_em_fracao_ou_pontos():
    r = pymupdf.Rect(0, 0, 1000, 500)
    assert tuple(pd.resolve_rect(r, [0.1, 0.2, 0.3, 0.4])) == (100, 100, 300, 200)
    assert tuple(pd.resolve_rect(r, [100, 100, 300, 200])) == (100, 100, 300, 200)
    with pytest.raises(ValueError):
        pd.resolve_rect(r, [1, 2, 3])


def test_recorte_diz_mm_por_pixel(desenho, tmp_path):
    info = pd.crop(desenho, str(tmp_path / "v.png"), [0.1, 0.2, 0.3, 0.4], dpi=254, view_scale="1:2")
    assert info["width_px"] == pytest.approx(200 / 72 * 254, abs=2)  # pixmap arredonda a borda
    assert info["paper_mm_per_px"] == pytest.approx(0.1)
    assert info["model_mm_per_px"] == pytest.approx(0.2)
    assert pd.page_info(desenho)["has_text"] is True


def test_tabela_comparativa_pagina_nova_a_cada_4_linhas(desenho, tmp_path):
    linhas = [{"item": f"cota {i}", "a_value": "Ø200 H9", "a_rect": [0.1, 0.2, 0.3, 0.4],
               "b_value": "Ø200 H8", "b_rect": None} for i in range(5)]
    r = pd.compare_table(desenho, desenho, linhas, str(tmp_path / "c.pdf"), label_a="A", label_b="B")
    assert r["rows"] == 5 and r["pages"] == 2
    with pymupdf.open(r["pdf"]) as out:
        texto = out[0].get_text()
    assert "sem indicação no desenho" in texto and "Ø200 H8" in texto
