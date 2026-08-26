"""Válvula de escape: qualquer chamada da API COM que não tenha tool própria."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import script as sc


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def run_sw_script(code: str) -> dict[str, Any]:
        """Executa código Python (pywin32) direto contra a API COM do SolidWorks,
        para operações sem tool dedicada. Escopo disponível:
          app       -> ISldWorks (documento ativo em com_get(app,'ActiveDoc'))
          cast_to(obj, 'IInterface') -> OBRIGATÓRIO em quase todo objeto retornado
          com_call(obj,'Metodo',...) / com_get(obj,'Prop') -> invocação fail-fast
          swconst() -> enums oficiais (ex.: swconst().swDocPART)
          units     -> from_mm/to_mm/from_deg/to_deg (API interna usa metros/rad)
          result    -> atribua o retorno desejado (JSON-serializável)
        prints aparecem no retorno. Métodos com parâmetro byref retornam tupla.
        Use com moderação e prefira as tools dedicadas; nunca salve/feche
        documento por aqui sem pedido explícito do usuário."""
        return session.run(lambda app: sc.run_script(app, code))
