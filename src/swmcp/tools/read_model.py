"""Tool de leitura de modelo 3D (RF-04)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.services import drawing_reader


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def get_model_properties(path: str) -> dict[str, Any]:
        """Propriedades de uma peça/montagem: material, massa, caixa envolvente,
        propriedades customizadas (documento e configuração), configurações e
        lista de features. Unidades: mm e kg. Somente-leitura.
        """
        return drawing_reader.get_model_properties(session, path).model_dump()
