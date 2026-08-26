"""Tool de criação de desenho 2D a partir do modelo (RF-06)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import drawing_build as db


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def create_drawing_from_model(
        model_path: str,
        views: list[str] | None = None,
        template: str = "",
        import_annotations: bool = True,
    ) -> dict[str, Any]:
        """Cria um desenho 2D novo com vistas do modelo indicado.
        views: front, back, left, right, top, bottom, iso (default front+top+iso).
        Importa as cotas marcadas para desenho do modelo. O desenho fica aberto
        e NÃO salvo, para o projetista revisar; salve com save_document_as."""
        return session.run(
            lambda app: db.create_drawing_from_model(app, model_path, views, template or None, import_annotations)
        )

    @mcp.tool()
    def add_projected_view(source_view: str, x_mm: float, y_mm: float) -> dict[str, str]:
        """Vista projetada no desenho ativo a partir de uma vista existente
        (nome via get_drawing_dump); posição em mm define a direção."""
        return {"view": session.run(lambda app: db.add_projected_view(app, source_view, x_mm, y_mm))}

    @mcp.tool()
    def insert_drawing_note(text: str, x_mm: float, y_mm: float) -> dict[str, str]:
        """Nota de texto na folha ativa do desenho, na posição (x,y) mm."""
        return {"note": session.run(lambda app: db.insert_drawing_note(app, text, x_mm, y_mm))}

    @mcp.tool()
    def set_sheet_scale(numerator: float, denominator: float) -> dict[str, str]:
        """Muda a escala da folha ativa do desenho (ex.: 1 e 2 para 1:2)."""
        return session.run(lambda app: db.set_sheet_scale(app, numerator, denominator))
