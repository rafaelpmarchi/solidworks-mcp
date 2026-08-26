"""Tool de leitura de desenho (RF-03)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.services import drawing_reader


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def get_drawing_dump(path: str) -> dict[str, Any]:
        """Dump completo e fiel de um desenho .SLDDRW em JSON.

        Folhas, vistas, cotas (valor em mm/graus, tolerância, inspeção),
        anotações (GD&T, solda, acabamento), notas de legenda e propriedades.
        Somente-leitura: abre o arquivo read-only se necessário e fecha ao
        final sem salvar. Itens não reconhecidos vêm em `unrecognized` —
        nunca são omitidos.
        """
        return drawing_reader.get_drawing_dump(session, path).model_dump()
