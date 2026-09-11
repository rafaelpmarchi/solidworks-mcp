"""Tools de opções do sistema do SolidWorks (File Locations)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import settings as st


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def get_file_locations() -> dict[str, list[str]]:
        """System Options → File Locations do SolidWorks: templates de documento,
        formatos de folha, perfis de weldment, arquivo de propriedades de
        weldment, templates de lista de corte, BOM, materiais, Design Library e
        macros. Somente leitura."""
        return session.run(st.get_file_locations)

    @mcp.tool()
    def set_file_location(location: str, folders: list[str], append: bool = True) -> dict[str, Any]:
        """Grava pastas num File Location do SolidWorks (configuração PERSISTENTE
        do usuário — só com pedido explícito). location: document_templates,
        sheet_formats, weldment_profiles, weldment_property_file,
        weldment_cut_list_templates, bom_templates, material_databases,
        design_library ou macros. append=True mantém as pastas atuais;
        append=False substitui. As pastas precisam existir."""
        return session.run(lambda app: st.set_file_location(app, location, folders, append))

    @mcp.tool()
    def apply_kongz_library(root: str, append: bool = True) -> dict[str, Any]:
        """Configura o SolidWorks para a biblioteca KONGZ (Gromar) a partir da
        raiz da pasta KONGZ: templates de documento em
        CAD/KONGZ_SolidWorks_Library/KONGZ_templates, formatos de folha em
        .../sheetformat e perfis de weldment em .../data/weldment profiles.
        Configuração persistente — só com pedido explícito."""
        return session.run(lambda app: st.apply_kongz_library(app, root, append))
