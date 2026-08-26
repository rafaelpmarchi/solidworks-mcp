"""Entrypoint do servidor MCP: registra tools e roda sobre stdio."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.log import setup_logging

INSTRUCTIONS = """\
Servidor MCP do SolidWorks (Gromar). Unidades: tudo que entra e sai das tools
é milímetro e grau. Tools get_/list_/sw_status são somente-leitura. As demais
ALTERAM o documento ativo — mas nada é salvo em disco sem save_document[_as],
e salvar/sobrescrever/apagar só com pedido explícito do usuário. Fluxo típico
de modelagem: new_document → create_sketch(plano) → sketch_* → extrude/revolve
→ take_screenshot para conferir o resultado visualmente. O SolidWorks precisa
estar instalado nesta máquina; se não houver instância aberta, uma nova é
iniciada visível ao usuário.
"""


def build_server() -> MCPServer:
    mcp = MCPServer("solidworks", instructions=INSTRUCTIONS)
    session = SwSession()

    from swmcp.tools import (
        assembly,
        connection,
        create,
        create_drawing,
        edit,
        output,
        read_drawing,
        read_model,
        review,
        script,
    )

    connection.register(mcp, session)
    read_drawing.register(mcp, session)
    read_model.register(mcp, session)
    review.register(mcp, session)
    create.register(mcp, session)
    edit.register(mcp, session)
    output.register(mcp, session)
    assembly.register(mcp, session)
    create_drawing.register(mcp, session)
    script.register(mcp, session)

    return mcp


def main() -> None:
    setup_logging()
    build_server().run()


if __name__ == "__main__":
    main()
