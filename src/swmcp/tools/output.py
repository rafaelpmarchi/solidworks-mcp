"""Tools de salvar, exportar e visualizar (RF-08)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def save_document() -> dict[str, Any]:
        """Salva o documento ativo no caminho atual. Só use quando o usuário
        pedir para salvar — salvar nunca é efeito colateral."""
        return session.run(o.save_active)

    @mcp.tool()
    def save_document_as(path: str, overwrite: bool = False) -> dict[str, Any]:
        """Salva o documento ativo no caminho dado; a extensão define o formato:
        nativo (.sldprt/.sldasm/.slddrw) ou exportação (.pdf, .step, .dxf,
        .dwg, .stl, .igs, .png...). Recusa sobrescrever sem overwrite=True."""
        return session.run(lambda app: o.save_as(app, path, overwrite))

    @mcp.tool()
    def export_document(path: str, overwrite: bool = False) -> dict[str, Any]:
        """Exporta o documento ativo (PDF, STEP, DXF, DWG, STL, IGES, PNG...)
        sem mudar o arquivo nativo. Alias de save_document_as para exportação."""
        return session.run(lambda app: o.save_as(app, path, overwrite))

    @mcp.tool()
    def take_screenshot(path: str = "") -> dict[str, Any]:
        """Salva um PNG da vista atual do documento ativo (com zoom to fit) e
        retorna o caminho — leia o arquivo para VER o estado do modelo.
        path vazio usa %TEMP%/swmcp_screenshot.png."""
        import os
        import tempfile

        path = path or os.path.join(tempfile.gettempdir(), "swmcp_screenshot.png")
        return session.run(lambda app: o.screenshot(app, path))

    @mcp.tool()
    def zoom_to_fit() -> dict[str, bool]:
        """Enquadra o modelo na janela (zoom to fit)."""
        session.run(m.zoom_to_fit)
        return {"ok": True}
