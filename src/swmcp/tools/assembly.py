"""Tools de montagem: inserir componentes e mates."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import assembly as a
from swmcp.com.wrappers import assembly_refs as r


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def insert_component(path: str, x_mm: float = 0, y_mm: float = 0, z_mm: float = 0,
                         rotation_deg: list[float] | None = None,
                         fixed: bool = False) -> dict[str, Any]:
        """Insere uma peça/submontagem na montagem ativa. (x,y,z) em mm é onde
        a ORIGEM da peça cai; rotation_deg=[rx,ry,rz] gira em torno dos eixos
        da montagem na ordem X → Y → Z (ex.: [180,0,0] vira de cabeça para
        baixo; [0,180,0] espelha a posição de X e Z). fixed=True fixa o
        componente na posição pedida. Devolve a caixa do componente para
        conferir onde ele ficou."""
        return session.run(lambda app: a.insert_component(
            app, path, x_mm, y_mm, z_mm, rotation_deg, fixed))

    @mcp.tool()
    def set_component_transform(name: str, x_mm: float, y_mm: float, z_mm: float,
                                rotation_deg: list[float] | None = None,
                                fixed: bool | None = None) -> dict[str, Any]:
        """Posição e rotação ABSOLUTAS de um componente (mesma convenção de
        insert_component). Libera o componente fixo para mover e volta a fixar;
        fixed=True/False força o estado final. Confere o que foi gravado —
        falha se posicionamentos (mates) impedirem."""
        return session.run(lambda app: a.set_component_transform(
            app, name, x_mm, y_mm, z_mm, rotation_deg, fixed))

    @mcp.tool()
    def list_components() -> list[dict[str, Any]]:
        """Componentes da montagem ativa: nome, arquivo, suprimido, fixo."""
        return session.run(a.list_components)

    @mcp.tool()
    def set_component_suppressed(name: str, suppressed: bool = True) -> dict[str, bool]:
        """Suprime/resolve um componente da montagem (nome de list_components)."""
        session.run(lambda app: a.set_component_suppressed(app, name, suppressed))
        return {"ok": True}

    @mcp.tool()
    def set_component_fixed(name: str, fixed: bool = True) -> dict[str, bool]:
        """Fixa (ou libera) um componente da montagem."""
        session.run(lambda app: a.set_component_fixed(app, name, fixed))
        return {"ok": True}

    @mcp.tool()
    def move_component(name: str, dx_mm: float, dy_mm: float, dz_mm: float) -> dict[str, bool]:
        """Translada um componente livre (mates podem limitar o movimento)."""
        session.run(lambda app: a.move_component(app, name, dx_mm, dy_mm, dz_mm))
        return {"ok": True}

    @mcp.tool()
    def check_interference() -> list[dict[str, Any]]:
        """Detecção de interferência entre componentes da montagem ativa.
        Retorna pares de componentes e o volume de interferência em mm³."""
        return session.run(a.check_interference)

    @mcp.tool()
    def add_mate(mate_type: str, distance_mm: float = 0.0, angle_deg: float = 0.0,
                 flip: bool = False, alignment: str = "closest") -> dict[str, str]:
        """Cria um mate entre as DUAS entidades já selecionadas — de preferência
        com select_component_entity (pela geometria) duas vezes, a segunda com
        append=True. mate_type: coincident, concentric, distance, parallel,
        perpendicular, tangent, angle, lock. alignment: closest, aligned ou
        anti_aligned (list_mates mostra o de mates existentes)."""
        return {"mate": session.run(lambda app: a.add_mate(
            app, mate_type, distance_mm, angle_deg, flip, alignment))}

    @mcp.tool()
    def list_mates(component: str) -> list[dict[str, Any]]:
        """Mates (posicionamentos) de um componente: tipo, alinhamento, flip,
        valor (distância mm / ângulo graus) e as entidades de cada lado —
        componente, kind (face/edge/vertex/plane), ponto e direção em
        coordenadas da MONTAGEM (mm). O ponto é um ponto qualquer do
        plano/reta da entidade, não necessariamente em cima dela. Somente-leitura."""
        return session.run(lambda app: r.list_mates(app, component))

    @mcp.tool()
    def select_component_entity(component: str, kind: str, point_mm: list[float],
                                direction: list[float] | None = None,
                                radius_mm: float = 0.0, append: bool = False,
                                mark: int = 0) -> dict[str, Any]:
        """Seleciona uma entidade de um COMPONENTE pela geometria, em coordenadas
        da montagem (mm) — para mates, sem depender de acertar um clique.
        kind: face (plana; cilíndrica com radius_mm), edge (reta; circular com
        radius_mm), vertex, plane (plano de referência da peça). Com direction
        (normal da face / direção da aresta / eixo) casa o plano/reta/eixo
        inteiro; sem direction pega a entidade que passa pelo ponto."""
        return session.run(lambda app: r.select_component_entity(
            app, component, kind, point_mm, direction, radius_mm, append, mark))

    @mcp.tool()
    def replicate_component(source: str, offsets_mm: list[list[float]]) -> dict[str, Any]:
        """Copia um componente para outras posições SEGUINDO AS MESMAS
        REFERÊNCIAS: cada cópia entra com a rotação do original deslocada por
        um [dx,dy,dz] (mm) e cada mate do original é refeito nas entidades
        correspondentes — as da cópia e as do outro componente deslocadas pelo
        mesmo offset (o rasgo vizinho, o furo seguinte). Ex.: porta-etiqueta
        montado num rasgo → offsets dos outros rasgos. Relata mate a mate e
        confere que a cópia não saiu do lugar (moved_mm = 0); original fixo
        sem mates gera cópias fixas. Rode check_interference depois."""
        return session.run(lambda app: r.replicate_component(app, source, offsets_mm))

    @mcp.tool()
    def replace_component(component: str, new_path: str,
                          all_instances: bool = False) -> dict[str, Any]:
        """Substitui o arquivo de um componente (ou de todas as instâncias do
        mesmo arquivo) mantendo posição e mates. Confere que ele passou a
        apontar para o arquivo novo e devolve mate_errors — os mates cuja
        referência não existe na peça nova."""
        return session.run(lambda app: r.replace_component(app, component, new_path, all_instances))

    @mcp.tool()
    def mate_errors() -> list[dict[str, Any]]:
        """Mates da montagem ativa com erro/aviso (referência perdida,
        sobredefinição). Somente-leitura."""
        return session.run(r.mate_errors)

    @mcp.tool()
    def component_transform(component: str) -> dict[str, Any]:
        """Onde está a origem da peça na montagem e para onde apontam os eixos
        X/Y/Z dela. Somente-leitura."""
        return session.run(lambda app: r.component_transform(app, component))
