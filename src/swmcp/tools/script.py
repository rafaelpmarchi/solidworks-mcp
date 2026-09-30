"""Válvula de escape: qualquer chamada da API COM que não tenha tool própria."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import script as sc


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def run_sw_script(code: str, scratch: bool = False) -> dict[str, Any]:
        """Executa código Python (pywin32) direto contra a API COM do SolidWorks,
        para operações sem tool dedicada. Escopo disponível:
          app       -> ISldWorks (documento ativo em com_get(app,'ActiveDoc'))
          cast_to(obj, 'IInterface') -> OBRIGATÓRIO em quase todo objeto retornado
          com_call(obj,'Metodo',...) / com_get(obj,'Prop') -> invocação fail-fast
          swconst() -> enums oficiais (ex.: swconst().swDocPART)
          units     -> from_mm/to_mm/from_deg/to_deg (API interna usa metros/rad)
          result    -> atribua o retorno desejado (JSON-serializável)
          doc, feature(nome), tree_order(), select_face(x,y,z),
          ray_select(p_mm, dir), to_sketch(sketch, p_mm), to_model(sketch, p_mm),
          darr([..]) -> VARIANT de doubles (CreatePoint com lista corrompe)
        scratch=True roda numa PEÇA NOVA descartável, fechada sem salvar no fim
        (o documento anterior volta a ser o ativo) — use para TESTAR chamada de
        API sem criar/apagar feature na peça que o usuário está vendo.
        prints aparecem no retorno. Métodos com parâmetro byref retornam tupla.
        Use com moderação e prefira as tools dedicadas; nunca salve/feche
        documento por aqui sem pedido explícito do usuário."""
        return session.run(lambda app: sc.run_script(app, code, scratch))
