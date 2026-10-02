"""Tools de corpos: listar, mostrar/ocultar, superfície a partir de faces, STL."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import bodies as b
from swmcp.com.wrappers import output as o


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def list_bodies() -> list[dict[str, Any]]:
        """Corpos da peça ativa (sólidos e de superfície — inclusive a malha de
        scan importada): nome, tipo, visível, nº de faces e caixa em mm.
        Somente-leitura."""
        return session.run(b.list_bodies)

    @mcp.tool()
    def set_body_visibility(visible: bool, names: list[str] | None = None,
                            pattern: str = "", body_type: str = "") -> dict[str, Any]:
        """Mostra/oculta corpos por nome, padrão glob ('*Importado*') ou tipo
        ('solid'|'surface'). Ocultar a malha de scan (milhões de triângulos)
        enquanto modela deixa cada chamada da API muito mais rápida. Não
        altera geometria (só exibição)."""
        return session.run(lambda app: b.set_body_visibility(app, names, visible,
                                                             pattern, body_type))

    @mcp.tool()
    def set_reference_visibility(visible: bool, names: list[str] | None = None,
                                 kinds: list[str] | None = None) -> dict[str, Any]:
        """Mostra/oculta geometria de referência: por nome ou por tipo
        (kinds: 'plane', 'axis', 'csys'). Os 3 planos padrão só entram se
        nomeados. Útil antes de screenshot (o eixo de 1 m polui a vista)."""
        return session.run(lambda app: b.set_reference_visibility(app, names, visible, kinds))

    @mcp.tool()
    def surface_from_faces(body_name: str = "", direction: list[float] | None = None,
                           min_dot: float = -0.3, distance_mm: float = 0.0,
                           feature_name: str = "",
                           hide_source: bool = False) -> dict[str, Any]:
        """Corpo de SUPERFÍCIE com as faces de um sólido que apontam para
        `direction` (normal média · direção > min_dot), por Superfície
        equidistante de distance_mm (0 = cópia exata). Padrão: direção +Z e
        min_dot -0,3 = faces de cima + paredes, sem as de baixo — o lado que o
        scanner viu numa peça escaneada por cima. body_name vazio = o maior
        sólido; hide_source oculta o sólido de origem."""
        return session.run(lambda app: b.surface_from_faces(
            app, body_name, direction, min_dot, distance_mm, feature_name, hide_source))

    @mcp.tool()
    def export_stl(path: str, bodies: list[str] | None = None,
                   overwrite: bool = False) -> dict[str, Any]:
        """STL do documento ativo NAS COORDENADAS DA PEÇA (sem a translação
        para o octante positivo que o SolidWorks faz por padrão), em mm e
        qualidade fina — pronto para mesh_deviation_map. bodies limita aos
        corpos com esses nomes (os outros ficam ocultos só durante a
        exportação). Recusa sobrescrever sem overwrite=True."""
        return session.run(lambda app: o.export_stl(app, path, bodies, overwrite))
