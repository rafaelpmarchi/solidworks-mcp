"""Entrypoint do servidor MCP: registra tools e roda sobre stdio."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.log import setup_logging

INSTRUCTIONS = """\
Servidor MCP do SolidWorks (Gromar). Unidades: tudo que entra e sai das tools
é milímetro e grau. Tools get_/list_/sw_status são somente-leitura e nunca
alteram arquivos. O SolidWorks precisa estar instalado nesta máquina; se não
houver instância aberta, uma nova é iniciada visível ao usuário.
"""


def build_server() -> MCPServer:
    mcp = MCPServer("solidworks", instructions=INSTRUCTIONS)
    session = SwSession()

    from swmcp.tools import connection, read_drawing, read_model, review

    connection.register(mcp, session)
    read_drawing.register(mcp, session)
    read_model.register(mcp, session)
    review.register(mcp, session)

    return mcp


def main() -> None:
    setup_logging()
    build_server().run()


if __name__ == "__main__":
    main()
