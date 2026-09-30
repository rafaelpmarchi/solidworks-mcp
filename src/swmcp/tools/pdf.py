"""Tools de desenho em PDF de cliente (não usam o SolidWorks)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.services import pdf_drawing as pd


def register(mcp: MCPServer, session: SwSession) -> None:  # noqa: ARG001 — padrão dos módulos
    @mcp.tool()
    def pdf_drawing_info(path: str) -> dict[str, Any]:
        """Tamanho da folha (pt e mm), nº de páginas e se o PDF tem texto
        extraível (desenho Creo/Pro-E exportado às vezes não tem)."""
        return pd.page_info(path)

    @mcp.tool()
    def pdf_drawing_crop(path: str, out_png: str, rect: list[float] | None = None,
                         page: int = 0, dpi: int = 200,
                         view_scale: str = "") -> dict[str, Any]:
        """Renderiza uma região do desenho PDF em PNG para LER a vista (leia o
        PNG depois). rect=[x0,y0,x1,y1] em fração da página (0..1, origem em
        cima à esquerda) ou em pontos PDF. Use 200-300 dpi por vista — a folha
        A0 inteira de uma vez sai ilegível. Com view_scale ('7:20', '2:1') o
        retorno traz model_mm_per_px, para medir o que não está cotado."""
        return pd.crop(path, out_png, rect, page, dpi, view_scale or None)

    @mcp.tool()
    def pdf_compare_table(pdf_a: str, pdf_b: str, rows: list[dict[str, Any]], out_pdf: str,
                          title: str = "", label_a: str = "", label_b: str = "") -> dict[str, Any]:
        """PDF A3 com a comparação de dois desenhos, uma linha por cota:
        Item | valor A | recorte A | valor B | recorte B. rows=[{"item",
        "a_value", "a_rect", "b_value", "b_rect"}] com rect como em
        pdf_drawing_crop (null = "sem indicação no desenho"). Os recortes são
        vetoriais. Ache os retângulos com pdf_drawing_crop antes."""
        return pd.compare_table(pdf_a, pdf_b, rows, out_pdf, title, label_a, label_b)
