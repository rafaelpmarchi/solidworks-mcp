"""Tools de modelagem 3D (escrita): documento novo, sketch, features."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import modeling as m
from swmcp.com.wrappers import output as o


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def new_document(kind: str = "part") -> dict[str, Any]:
        """Cria um documento novo no SolidWorks (kind: part, assembly ou drawing)
        a partir do template padrão. O documento fica ativo e NÃO salvo."""
        return session.run(lambda app: o.new_document(app, kind))

    @mcp.tool()
    def list_planes() -> list[str]:
        """Nomes dos planos de referência do documento ativo (a UI pode estar em
        português: 'Plano frontal', 'Plano superior', 'Plano direito')."""
        return session.run(m.list_planes)

    @mcp.tool()
    def create_sketch(plane: str) -> dict[str, str]:
        """Abre um sketch novo no plano/face nomeado do documento ativo.
        Use list_planes para descobrir os nomes. Depois desenhe com as tools
        sketch_* e feche com uma feature (extrude/revolve) ou close_sketch."""
        return {"sketch": session.run(lambda app: m.insert_sketch(app, plane))}

    @mcp.tool()
    def close_sketch() -> dict[str, bool]:
        """Fecha o sketch ativo sem criar feature."""
        session.run(m.exit_sketch)
        return {"closed": True}

    @mcp.tool()
    def sketch_line(x1: float, y1: float, x2: float, y2: float, centerline: bool = False) -> dict[str, bool]:
        """Desenha uma linha no sketch ativo (coordenadas em mm; centerline=True
        para linha de centro, necessária em revoluções)."""
        session.run(lambda app: m.sketch_line(app, x1, y1, x2, y2, centerline))
        return {"ok": True}

    @mcp.tool()
    def sketch_circle(xc: float, yc: float, diameter: float) -> dict[str, bool]:
        """Desenha um círculo no sketch ativo (centro e diâmetro em mm)."""
        session.run(lambda app: m.sketch_circle(app, xc, yc, diameter))
        return {"ok": True}

    @mcp.tool()
    def sketch_rectangle(x1: float, y1: float, x2: float, y2: float, center: bool = False) -> dict[str, bool]:
        """Retângulo no sketch ativo (mm). center=False: cantos opostos;
        center=True: (x1,y1) é o centro e (x2,y2) um canto."""
        session.run(lambda app: m.sketch_rectangle(app, x1, y1, x2, y2, center))
        return {"ok": True}

    @mcp.tool()
    def sketch_arc(xc: float, yc: float, x1: float, y1: float, x2: float, y2: float,
                   clockwise: bool = False) -> dict[str, bool]:
        """Arco por centro (xc,yc), ponto inicial e final (mm)."""
        session.run(lambda app: m.sketch_arc_center(app, xc, yc, x1, y1, x2, y2,
                                                    -1 if clockwise else 1))
        return {"ok": True}

    @mcp.tool()
    def sketch_polygon(xc: float, yc: float, sides: int, diameter: float) -> dict[str, bool]:
        """Polígono regular inscrito no sketch ativo (centro, nº de lados,
        diâmetro do círculo inscrito, em mm)."""
        session.run(lambda app: m.sketch_polygon(app, xc, yc, sides, diameter))
        return {"ok": True}

    @mcp.tool()
    def extrude(depth_mm: float, cut: bool = False, flip: bool = False,
                through_all: bool = False) -> dict[str, str]:
        """Extruda o sketch ativo: boss (cut=False) ou corte (cut=True).
        through_all corta tudo; flip inverte a direção. Fecha o sketch."""
        return {"feature": session.run(lambda app: m.extrude(app, depth_mm, cut, flip, through_all))}

    @mcp.tool()
    def revolve(angle_deg: float = 360.0, cut: bool = False) -> dict[str, str]:
        """Revoluciona o sketch ativo em torno da linha de centro dele
        (desenhe uma sketch_line com centerline=True antes)."""
        return {"feature": session.run(lambda app: m.revolve(app, angle_deg, cut))}

    @mcp.tool()
    def fillet_selected(radius_mm: float) -> dict[str, str]:
        """Filete de raio constante nas arestas selecionadas — selecione antes
        com select_entity(type='EDGE', coordenadas em mm sobre a aresta)."""
        return {"feature": session.run(lambda app: m.fillet(app, radius_mm))}

    @mcp.tool()
    def chamfer_selected(distance_mm: float, angle_deg: float = 45.0) -> dict[str, str]:
        """Chanfro distância×ângulo nas arestas selecionadas."""
        return {"feature": session.run(lambda app: m.chamfer(app, distance_mm, angle_deg))}

    @mcp.tool()
    def shell_selected(thickness_mm: float) -> dict[str, str]:
        """Casca no corpo ativo removendo as faces selecionadas
        (select_entity type='FACE' com coordenadas)."""
        return {"feature": session.run(lambda app: m.shell(app, thickness_mm))}

    @mcp.tool()
    def create_reference_plane(base_plane: str, offset_mm: float, flip: bool = False) -> dict[str, str]:
        """Plano de referência paralelo a um plano existente com offset em mm."""
        return {"feature": session.run(lambda app: m.reference_plane_offset(app, base_plane, offset_mm, flip))}

    @mcp.tool()
    def select_entity(name: str, entity_type: str, x_mm: float = 0, y_mm: float = 0,
                      z_mm: float = 0, append: bool = False, mark: int = 0) -> dict[str, bool]:
        """Seleciona uma entidade no documento ativo (SelectByID2).
        Tipos: PLANE, FACE, EDGE, VERTEX, SKETCH, BODYFEATURE, AXIS, COMPONENT.
        Para FACE/EDGE sem nome, deixe name='' e aponte as coordenadas em mm
        (use get_model_properties/bounding box ou um screenshot para se orientar).
        append=True acumula seleção (necessário para mates e filetes múltiplos)."""
        return {"selected": session.run(
            lambda app: m.select_entity(app, name, entity_type, x_mm, y_mm, z_mm, append, mark))}

    @mcp.tool()
    def clear_selection() -> dict[str, bool]:
        """Limpa a seleção atual."""
        session.run(m.clear_selection)
        return {"ok": True}

    @mcp.tool()
    def rebuild() -> dict[str, bool]:
        """Reconstrói o documento ativo (Ctrl+B). Retorna se reconstruiu sem erro."""
        return {"rebuilt": session.run(m.rebuild)}
