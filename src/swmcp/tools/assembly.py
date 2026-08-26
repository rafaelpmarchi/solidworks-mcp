"""Tools de montagem: inserir componentes e mates."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import assembly as a


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def insert_component(path: str, x_mm: float = 0, y_mm: float = 0, z_mm: float = 0) -> dict[str, Any]:
        """Insere uma peça/submontagem na montagem ativa, na posição dada (mm)."""
        return session.run(lambda app: a.insert_component(app, path, x_mm, y_mm, z_mm))

    @mcp.tool()
    def add_mate(mate_type: str, distance_mm: float = 0.0, angle_deg: float = 0.0,
                 flip: bool = False) -> dict[str, str]:
        """Cria um mate entre as DUAS entidades já selecionadas (use
        select_entity duas vezes, a segunda com append=True).
        mate_type: coincident, concentric, distance, parallel, perpendicular,
        tangent, angle, lock."""
        return {"mate": session.run(lambda app: a.add_mate(app, mate_type, distance_mm, angle_deg, flip))}
