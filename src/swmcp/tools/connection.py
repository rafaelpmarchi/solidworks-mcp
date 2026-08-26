"""Tools de conexão e documentos (RF-01, RF-02)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import document as doc_w


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def sw_status() -> dict[str, Any]:
        """Status do SolidWorks: versão, documentos abertos e documento ativo.

        Conecta à instância aberta (ou inicia uma nova, visível). Nunca altera nada.
        """
        return session.status()

    @mcp.tool()
    def sw_open_document(path: str, read_only: bool = True) -> dict[str, Any]:
        """Abre um documento (.SLDDRW/.SLDPRT/.SLDASM) no SolidWorks.

        Por padrão abre somente-leitura. Retorna título, tipo e avisos de carga.
        """
        return session.run(lambda app: doc_w.open_document(app, path, read_only))

    @mcp.tool()
    def sw_close_document(title: str) -> dict[str, Any]:
        """Fecha o documento com esse título SEM salvar.

        Salvar nunca é efeito colateral: alterações não salvas são descartadas
        — confirme com o usuário antes se o documento estiver modificado.
        """
        session.run(lambda app: doc_w.close_document(app, title))
        return {"closed": title, "saved": False}
