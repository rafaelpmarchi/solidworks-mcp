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
