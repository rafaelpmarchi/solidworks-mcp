"""Tool de leitura de modelo 3D (RF-04)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import holes as h
from swmcp.services import drawing_reader


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def measure_bodies(density_kg_m3: float = 7850.0) -> list[dict[str, Any]]:
        """Volume, área, massa e caixa de cada corpo sólido da peça ativa
        (mm, mm², kg). Somente-leitura. Serve para CONFERIR o modelo: o volume
        de cada feature é previsível no papel, então comparar o medido com o
        esperado pega cota errada que não salta aos olhos na tela. A densidade
        padrão é a do aço (7850 kg/m³) e não depende do material da peça."""
        return session.run(lambda app: h.measure_bodies(app, density_kg_m3))

    @mcp.tool()
    def list_circular_edges(min_diameter_mm: float = 0.0,
                            max_diameter_mm: float | None = None) -> list[dict[str, Any]]:
        """Arestas circulares da peça ativa: centro (mm), diâmetro e eixo.
        Somente-leitura. É como achar a aresta de um filete ou de uma rosca sem
        precisar acertar um ponto em cima dela — depois use select_circular_edge."""
        return session.run(lambda app: h.list_circular_edges(
            app, min_diameter_mm, max_diameter_mm))

    @mcp.tool()
    def get_model_properties(path: str) -> dict[str, Any]:
        """Propriedades de uma peça/montagem: material, massa, caixa envolvente,
        propriedades customizadas (documento e configuração), configurações e
        lista de features. Unidades: mm e kg. Somente-leitura.
        """
        return drawing_reader.get_model_properties(session, path).model_dump()
