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
    def list_components() -> list[dict[str, Any]]:
        """Componentes da montagem ativa: nome, arquivo, suprimido, fixo."""
        return session.run(a.list_components)

    @mcp.tool()
    def set_component_suppressed(name: str, suppressed: bool = True) -> dict[str, bool]:
        """Suprime/resolve um componente da montagem (nome de list_components)."""
        session.run(lambda app: a.set_component_suppressed(app, name, suppressed))
        return {"ok": True}

    @mcp.tool()
    def set_component_fixed(name: str, fixed: bool = True) -> dict[str, bool]:
        """Fixa (ou libera) um componente da montagem."""
        session.run(lambda app: a.set_component_fixed(app, name, fixed))
        return {"ok": True}

    @mcp.tool()
    def move_component(name: str, dx_mm: float, dy_mm: float, dz_mm: float) -> dict[str, bool]:
        """Translada um componente livre (mates podem limitar o movimento)."""
        session.run(lambda app: a.move_component(app, name, dx_mm, dy_mm, dz_mm))
        return {"ok": True}

    @mcp.tool()
    def check_interference() -> list[dict[str, Any]]:
        """Detecção de interferência entre componentes da montagem ativa.
        Retorna pares de componentes e o volume de interferência em mm³."""
        return session.run(a.check_interference)

    @mcp.tool()
    def add_mate(mate_type: str, distance_mm: float = 0.0, angle_deg: float = 0.0,
                 flip: bool = False) -> dict[str, str]:
        """Cria um mate entre as DUAS entidades já selecionadas (use
        select_entity duas vezes, a segunda com append=True).
        mate_type: coincident, concentric, distance, parallel, perpendicular,
        tangent, angle, lock."""
        return {"mate": session.run(lambda app: a.add_mate(app, mate_type, distance_mm, angle_deg, flip))}
