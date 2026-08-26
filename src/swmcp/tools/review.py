"""Tool de revisão de desenho (RF-05)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.review import engine
from swmcp.services import drawing_reader


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def review_drawing(path: str, ruleset: str = "gromar") -> dict[str, Any]:
        """Revisa um desenho .SLDDRW com as regras da Gromar.

        Lê o desenho (somente-leitura) e roda as regras de verificação:
        legenda completa, material declarado, escala coerente, cota de
        inspeção com tolerância, GD&T com datum, solda com descrição.
        Retorna o relatório com achados por severidade. Itens que a leitura
        não reconheceu viram achados INFO — a revisão não os avaliou.
        """
        dump = drawing_reader.get_drawing_dump(session, path)
        report = engine.review(dump, ruleset)
        out = report.model_dump()
        out["summary"] = {"errors": report.errors, "warnings": report.warnings, "total": len(report.findings)}
        return out
