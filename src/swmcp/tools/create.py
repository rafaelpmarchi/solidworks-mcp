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
    def fillet_opening_corners(feature_name: str, radius_mm: float,
                               region_mm: list[float] | None = None,
                               include_outer: bool = False,
                               preview: bool = False) -> dict[str, Any]:
        """Arredonda TODOS os cantos das aberturas (furos, fendas, grelhas com
        aletas) de uma chapa numa só feature de filete, sem selecionar aresta
        por aresta. feature_name é a extrusão/corte que tem as faces da chapa
        (use list_features). Acha as arestas retas que atravessam a espessura
        nos contornos internos das faces planas; ignora costura de furo redondo
        e cantos já filetados (idempotente). region_mm=[xmin,ymin,zmin,xmax,
        ymax,zmax] limita a uma grelha; include_outer=True inclui os cantos do
        contorno externo; preview=True só lista os cantos, sem criar nada.
        Devolve o nome do filete, nº de cantos e aviso se o SolidWorks
        descartou arestas (raio maior que o canto permite, ou aleta que é corpo
        separado só encostando na chapa)."""
        return session.run(lambda app: m.fillet_opening_corners(
            app, feature_name, radius_mm, region_mm, include_outer, preview))

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

    @mcp.tool()
    def sketch_point(x: float, y: float) -> dict[str, bool]:
        """Ponto no sketch ativo (mm)."""
        session.run(lambda app: m.sketch_point(app, x, y))
        return {"ok": True}

    @mcp.tool()
    def sketch_ellipse(xc: float, yc: float, major_radius: float, minor_radius: float) -> dict[str, bool]:
        """Elipse no sketch ativo (centro e semieixos em mm; maior no eixo X)."""
        session.run(lambda app: m.sketch_ellipse(app, xc, yc, major_radius, minor_radius))
        return {"ok": True}

    @mcp.tool()
    def sketch_slot(x1: float, y1: float, x2: float, y2: float, width: float) -> dict[str, bool]:
        """Rasgo (slot) reto entre dois centros com a largura dada (mm)."""
        session.run(lambda app: m.sketch_slot(app, x1, y1, x2, y2, width))
        return {"ok": True}

    @mcp.tool()
    def sketch_spline(points_mm: list[list[float]]) -> dict[str, bool]:
        """Spline pelos pontos [[x,y], ...] em mm (mínimo 3 pontos)."""
        session.run(lambda app: m.sketch_spline(app, points_mm))
        return {"ok": True}

    @mcp.tool()
    def sketch_text(x: float, y: float, text: str, height_mm: float = 5.0) -> dict[str, bool]:
        """Texto de sketch em (x,y) — pode ser extrudado para gravação em relevo."""
        session.run(lambda app: m.sketch_text(app, x, y, text, height_mm))
        return {"ok": True}

    @mcp.tool()
    def sketch_fillet(radius_mm: float) -> dict[str, bool]:
        """Arredonda o canto entre as DUAS entidades de sketch selecionadas
        (select_entity type='SKETCHSEGMENT' com append)."""
        session.run(lambda app: m.sketch_fillet(app, radius_mm))
        return {"ok": True}

    @mcp.tool()
    def sketch_offset(distance_mm: float, reverse: bool = False) -> dict[str, bool]:
        """Offset das entidades de sketch selecionadas."""
        session.run(lambda app: m.sketch_offset(app, distance_mm, reverse))
        return {"ok": True}

    @mcp.tool()
    def convert_entities() -> dict[str, bool]:
        """Projeta arestas/faces selecionadas no sketch ativo (Converter entidades)."""
        session.run(m.convert_entities)
        return {"ok": True}

    @mcp.tool()
    def edit_sketch(sketch_name: str) -> dict[str, str]:
        """Reabre um sketch existente para edição (use list_features para o nome;
        feche com close_sketch ou uma feature)."""
        return {"sketch": session.run(lambda app: m.edit_sketch(app, sketch_name))}

    @mcp.tool()
    def add_sketch_dimension(x_mm: float, y_mm: float, value_mm: float = 0) -> dict[str, str]:
        """Cota a entidade de sketch SELECIONADA (texto da cota em x,y).
        value_mm > 0 ajusta a geometria para esse valor."""
        return {"dimension": session.run(
            lambda app: m.add_sketch_dimension(app, x_mm, y_mm, value_mm or None))}

    @mcp.tool()
    def linear_pattern(count1: int, spacing1_mm: float, count2: int = 1,
                       spacing2_mm: float = 0, flip1: bool = False, flip2: bool = False) -> dict[str, str]:
        """Padrão linear. Antes: selecione a(s) feature(s) com select_entity
        (type='BODYFEATURE', mark=4) e a aresta/eixo da direção 1 com mark=1
        (direção 2 opcional, mark=2)."""
        return {"feature": session.run(
            lambda app: m.linear_pattern(app, count1, spacing1_mm, count2, spacing2_mm, flip1, flip2))}

    @mcp.tool()
    def circular_pattern(count: int, angle_deg: float = 360, equal_spacing: bool = True,
                         flip: bool = False) -> dict[str, str]:
        """Padrão circular. Antes: feature(s) com mark=4 e eixo/aresta circular
        com mark=1 (uma aresta cilíndrica serve de eixo)."""
        return {"feature": session.run(
            lambda app: m.circular_pattern(app, count, angle_deg, equal_spacing, flip))}

    @mcp.tool()
    def mirror_feature() -> dict[str, str]:
        """Espelha features. Antes: feature(s) com mark=1 e plano de espelho
        com mark=2 (select_entity type='PLANE')."""
        return {"feature": session.run(m.mirror_feature)}

    @mcp.tool()
    def loft(cut: bool = False) -> dict[str, str]:
        """Loft entre perfis. Antes: selecione os sketches-perfil na ordem,
        todos com type='SKETCH' e mark=1 (append=True)."""
        return {"feature": session.run(lambda app: m.loft(app, cut))}

    @mcp.tool()
    def rename_feature(old_name: str, new_name: str) -> dict[str, bool]:
        """Renomeia uma feature da árvore."""
        session.run(lambda app: m.rename_feature(app, old_name, new_name))
        return {"ok": True}

    @mcp.tool()
    def undo() -> dict[str, bool]:
        """Desfaz a última ação no documento ativo (Ctrl+Z)."""
        return {"undone": session.run(m.undo)}
