"""Desenho em PDF (de cliente, sem o SolidWorks): recortar vistas e comparar.

O PDF de desenho que chega de fora (Siemens, Creo/Pro-E) em geral não serve
para extração vetorial — as linhas vêm picadas e o texto nem sempre existe
como texto. O que funciona é RENDERIZAR a região da vista em 200-300 dpi e
ler, e medir o que não está cotado pela escala da vista:

    mm do modelo por pixel = (25,4 / dpi) / escala_da_vista

(escala "7:20" → 0,35). Os recortes da tabela comparativa são vetoriais
(show_pdf_page com clip), então dá zoom sem perder nitidez.

Retângulos: [x0, y0, x1, y1] em FRAÇÃO da página (0..1, origem no canto
superior esquerdo) — ou em pontos PDF se algum valor passar de 1.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

MM_PER_PT = 25.4 / 72.0


def _pymupdf() -> Any:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover — dependência opcional
        raise RuntimeError("PyMuPDF não instalado: pip install pymupdf (extra 'pdf')") from exc
    return pymupdf


def parse_scale(scale: str | float | None) -> float | None:
    """'7:20' → 0,35; '1:1' → 1; número passa direto."""
    if scale in (None, ""):
        return None
    if isinstance(scale, (int, float)):
        return float(scale)
    a, _, b = str(scale).replace(",", ".").partition(":")
    return float(a) / float(b) if b else float(a)


def resolve_rect(page_rect: Any, rect: Sequence[float] | None) -> Any:
    pymupdf = _pymupdf()
    if not rect:
        return page_rect
    if len(rect) != 4:
        raise ValueError("rect é [x0, y0, x1, y1]")
    if max(rect) <= 1.0:
        w, h = page_rect.width, page_rect.height
        return pymupdf.Rect(rect[0] * w, rect[1] * h, rect[2] * w, rect[3] * h)
    return pymupdf.Rect(*rect)


def page_info(path: str) -> dict[str, Any]:
    pymupdf = _pymupdf()
    with pymupdf.open(path) as doc:
        pg = doc[0]
        return {"pages": len(doc), "width_pt": pg.rect.width, "height_pt": pg.rect.height,
                "width_mm": round(pg.rect.width * MM_PER_PT, 1),
                "height_mm": round(pg.rect.height * MM_PER_PT, 1),
                "has_text": bool(pg.get_text().strip())}


def crop(path: str, out_png: str, rect: Sequence[float] | None = None, page: int = 0,
         dpi: int = 200, view_scale: str | float | None = None) -> dict[str, Any]:
    """Renderiza a região do desenho em PNG e diz quantos mm cada pixel vale."""
    pymupdf = _pymupdf()
    with pymupdf.open(path) as doc:
        pg = doc[page]
        clip = resolve_rect(pg.rect, rect)
        pix = pg.get_pixmap(dpi=dpi, clip=clip)
        os.makedirs(os.path.dirname(os.path.abspath(out_png)) or ".", exist_ok=True)
        pix.save(out_png)
        papel = 25.4 / dpi
        escala = parse_scale(view_scale)
        return {"png": os.path.abspath(out_png), "width_px": pix.width, "height_px": pix.height,
                "clip_pt": [round(v, 2) for v in clip], "dpi": dpi,
                "paper_mm_per_px": round(papel, 5),
                "model_mm_per_px": round(papel / escala, 5) if escala else None}


def compare_table(pdf_a: str, pdf_b: str, rows: Sequence[dict[str, Any]], out_pdf: str,
                  title: str = "", label_a: str = "", label_b: str = "",
                  row_height_pt: float = 186.0) -> dict[str, Any]:
    """Tabela A3 paisagem: Item | valor A | recorte A | valor B | recorte B.

    rows: [{item, a_value, a_rect, b_value, b_rect}] — rect None deixa a célula
    "sem indicação no desenho". Recortes vetoriais (zoom sem perder nitidez).
    """
    pymupdf = _pymupdf()
    a, b = pymupdf.open(pdf_a), pymupdf.open(pdf_b)
    label_a = label_a or os.path.splitext(os.path.basename(pdf_a))[0]
    label_b = label_b or os.path.splitext(os.path.basename(pdf_b))[0]
    out = pymupdf.open()
    largura, altura, margem, cab = 1191.0, 842.0, 24.0, 22.0
    colunas = [("Item", 150), (label_a, 165), (f"Recorte {label_a}", 330),
               (label_b, 165), (f"Recorte {label_b}", 330)]
    azul, vermelho = (0.1, 0.3, 0.7), (0.7, 0.2, 0.1)
    pagina, y, n = None, 0.0, 0

    def nova() -> tuple[Any, float]:
        nonlocal n
        n += 1
        pg = out.new_page(width=largura, height=altura)
        pg.insert_text((margem, margem + 14), title or f"Comparativo {label_a} × {label_b}",
                       fontsize=14, fontname="hebo")
        pg.insert_text((largura - margem - 60, margem + 14), f"pág. {n}", fontsize=9, fontname="helv")
        x, yy = margem, margem + 26
        for nome, w in colunas:
            r = pymupdf.Rect(x, yy, x + w, yy + cab)
            pg.draw_rect(r, color=(0.4, 0.4, 0.4), fill=(0.88, 0.9, 0.95), width=0.5)
            pg.insert_textbox(r + (4, 5, -4, 0), nome, fontsize=9.5, fontname="hebo")
            x += w
        return pg, yy + cab

    for i, row in enumerate(rows):
        if pagina is None or y + row_height_pt > altura - margem:
            pagina, y = nova()
        x = margem
        fundo = (1, 1, 1) if i % 2 == 0 else (0.97, 0.97, 0.97)
        textos = [str(row.get("item", "")), str(row.get("a_value", "")), None,
                  str(row.get("b_value", "")), None]
        for k, (_, w) in enumerate(colunas):
            celula = pymupdf.Rect(x, y, x + w, y + row_height_pt)
            pagina.draw_rect(celula, color=(0.4, 0.4, 0.4), fill=fundo, width=0.5)
            if textos[k] is not None:
                cor = (0, 0, 0) if k == 0 else (azul if k == 1 else vermelho)
                pagina.insert_textbox(celula + (5, 6, -5, -4), textos[k], fontsize=9.5,
                                      fontname="hebo" if k == 0 else "helv", color=cor)
            else:
                fonte, chave = (a, "a_rect") if k == 2 else (b, "b_rect")
                interno = celula + (4, 4, -4, -4)
                if not row.get(chave):
                    pagina.insert_textbox(interno + (0, row_height_pt / 2 - 14, 0, 0),
                                          "(sem indicação no desenho)", fontsize=9, fontname="helv",
                                          color=(0.5, 0.5, 0.5), align=1)
                else:
                    clip = resolve_rect(fonte[0].rect, row[chave])
                    s = min(interno.width / clip.width, interno.height / clip.height)
                    w2, h2 = clip.width * s, clip.height * s
                    x0 = interno.x0 + (interno.width - w2) / 2
                    y0 = interno.y0 + (interno.height - h2) / 2
                    pagina.show_pdf_page(pymupdf.Rect(x0, y0, x0 + w2, y0 + h2), fonte, 0, clip=clip)
            x += w
        y += row_height_pt
    os.makedirs(os.path.dirname(os.path.abspath(out_pdf)) or ".", exist_ok=True)
    out.save(out_pdf, garbage=3, deflate=True)
    paginas = len(out)
    out.close()
    a.close()
    b.close()
    return {"pdf": os.path.abspath(out_pdf), "rows": len(rows), "pages": paginas}
