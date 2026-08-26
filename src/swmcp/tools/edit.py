"""Tools de edição do documento ativo (escrita pontual, RF-07)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import edit as e


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def set_custom_property(name: str, value: str, configuration: str = "") -> dict[str, Any]:
        """Cria/atualiza uma propriedade customizada do documento ativo
        (configuration vazio = nível do documento). Não salva o arquivo."""
        return session.run(lambda app: e.set_custom_property(app, name, value, configuration))

    @mcp.tool()
    def delete_custom_property(name: str, configuration: str = "") -> dict[str, bool]:
        """Remove uma propriedade customizada do documento ativo."""
        session.run(lambda app: e.delete_custom_property(app, name, configuration))
        return {"deleted": True}

    @mcp.tool()
    def set_material(material_name: str, configuration: str = "") -> dict[str, str]:
        """Aplica um material do banco 'SOLIDWORKS Materials' à peça ativa.
        Exemplos de nome: 'AISI 304', 'AISI 1020', '6061 Alloy', 'ABS'."""
        return session.run(lambda app: e.set_material(app, material_name, configuration))

    @mcp.tool()
    def set_dimension(full_name: str, value: float, unit: str = "mm") -> dict[str, Any]:
        """Altera uma cota do modelo ativo e reconstrói. full_name no formato
        'D1@Esboço1' ou 'D1@Ressalto-Extrusão1'; unit: mm ou deg."""
        return session.run(lambda app: e.set_dimension(app, full_name, value, unit))

    @mcp.tool()
    def list_features(limit: int = 100) -> list[dict[str, Any]]:
        """Árvore de features do documento ativo: nome, tipo e se está suprimida.
        Use os nomes daqui em set_dimension/suppress/delete."""
        return session.run(lambda app: e.list_features(app, limit))

    @mcp.tool()
    def suppress_feature(feature_name: str, suppress: bool = True) -> dict[str, bool]:
        """Suprime (ou reativa, com suppress=False) uma feature pelo nome."""
        session.run(lambda app: e.suppress_feature(app, feature_name, suppress))
        return {"ok": True}

    @mcp.tool()
    def delete_feature(feature_name: str) -> dict[str, bool]:
        """APAGA uma feature (e filhos) do documento ativo. Destrutivo —
        confirme com o usuário antes de chamar."""
        session.run(lambda app: e.delete_feature(app, feature_name))
        return {"deleted": True}

    @mcp.tool()
    def list_equations() -> list[dict[str, Any]]:
        """Equações e variáveis globais do documento ativo."""
        return session.run(e.list_equations)

    @mcp.tool()
    def set_equation(index: int, equation: str) -> dict[str, Any]:
        """Substitui a equação no índice (veja list_equations). Formato:
        '\"D1@Esboço1\" = \"espessura\" * 2'. Reconstrói em seguida."""
        return session.run(lambda app: e.set_equation(app, index, equation))

    @mcp.tool()
    def add_equation(equation: str) -> dict[str, Any]:
        """Adiciona equação/variável global (ex.: '\"espessura\" = 5mm')."""
        return session.run(lambda app: e.add_equation(app, equation))

    @mcp.tool()
    def activate_configuration(name: str) -> dict[str, bool]:
        """Ativa uma configuração do documento ativo pelo nome."""
        session.run(lambda app: e.activate_configuration(app, name))
        return {"ok": True}
