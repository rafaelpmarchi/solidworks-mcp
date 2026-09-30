"""Tools de conferência e ajuste de peça existente: cotas e tolerâncias,
erros de reconstrução, faces, estado do esboço, edição de canto no perfil
e reparo de referência perdida."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import dimensions as d
from swmcp.com.wrappers import inspect as i
from swmcp.com.wrappers import repair as r
from swmcp.com.wrappers import sketch_edit as se


def register(mcp: MCPServer, session: SwSession) -> None:
    # ------------------------------------------------------------ cotas
    @mcp.tool()
    def list_dimensions(feature_name: str = "") -> list[dict[str, Any]]:
        """Cotas do modelo ativo com NOME COMPLETO (D1@Esboço10 — o nome curto
        se repete entre esboços e é o que se passa a set_dimension e
        set_dimension_tolerance), valor (mm ou deg), se é exibida como diâmetro,
        se é dirigida e a tolerância atual (tipo, desvios, ajuste ISO).
        feature_name limita a uma feature (com os esboços dela, inclusive os de
        um furo do assistente); vazio percorre a árvore toda. Somente-leitura."""
        return session.run(lambda app: d.list_dimensions(app, feature_name))

    @mcp.tool()
    def set_dimension_tolerance(full_name: str, tolerance_type: str = "fit", fit: str = "",
                                upper_mm: float = 0.0, lower_mm: float = 0.0,
                                show_as_diameter: bool | None = None) -> dict[str, Any]:
        """Tolerância numa cota, como na caixa de cota da UI. tolerance_type:
        fit (ajuste ISO: fit='H7' furo, 'f7' eixo — maiúscula/minúscula decide),
        bilateral (upper_mm/lower_mm, ex.: +0,05/0 → upper_mm=0.05, lower_mm=0),
        symmetric (±upper_mm), limit, min, max, basic, none. Em cota RADIAL de
        perfil de revolução passe show_as_diameter=True: o ajuste é calculado
        sobre o valor exibido (H7 sobre "90" dá o desvio de Ø90, e a peça é
        Ø180). Devolve os desvios calculados pelo SolidWorks para conferir."""
        return session.run(lambda app: d.set_dimension_tolerance(
            app, full_name, tolerance_type, fit, upper_mm, lower_mm, show_as_diameter))

    # ------------------------------------------------------- inspeção
    @mcp.tool()
    def check_rebuild_errors(rebuild: bool = True) -> dict[str, Any]:
        """Reconstrói e lista só as features (e sub-features — o esboço de
        posição de um furo que perdeu a face avisa ali) com erro ou aviso,
        como o painel "O que está errado?". clean=True = árvore limpa. Use
        depois de mexer num perfil: editar linha troca a identidade das faces
        e o que apontava para elas (eixo de padrão, plano de esboço) fica
        perdido — set_circular_pattern_axis religa o eixo; furo se refaz com
        hole_wizard na face certa."""
        return session.run(lambda app: i.check_rebuild_errors(app, rebuild))

    @mcp.tool()
    def list_faces(kind: str = "", diameter_mm: float | None = None,
                   tolerance_mm: float = 0.05, limit: int = 300) -> list[dict[str, Any]]:
        """Faces dos corpos da peça ativa: tipo (plane, cylinder, cone, torus,
        sphere), parâmetros da superfície (normal/eixo, ponto, diâmetro), caixa
        e área, em mm. kind filtra o tipo; diameter_mm filtra cilindro/cone.
        Somente-leitura — serve para achar por geometria a face que vira eixo
        de um padrão ou plano de um furo, e um ponto dela para select_face_at."""
        return session.run(lambda app: i.list_faces(app, kind, diameter_mm, tolerance_mm, limit))

    @mcp.tool()
    def sketch_status(sketch_name: str = "") -> dict[str, Any]:
        """Estado de um esboço (fully_defined / under_defined / over_defined)
        e QUAIS segmentos e pontos estão soltos, com coordenadas e quantas
        relações têm — é o que diz o que falta amarrar. Sem sketch_name lê o
        esboço aberto. Somente-leitura."""
        return session.run(lambda app: i.sketch_status(app, sketch_name))

    # -------------------------------------------- edição de canto (esboço)
    @mcp.tool()
    def sketch_corner_chamfer(corner_mm: list[float], distance_mm: float,
                              distance2_mm: float | None = None) -> dict[str, Any]:
        """Chanfro DENTRO do esboço aberto, no canto de coordenada corner_mm
        [x, y] (mm do esboço; sketch_status/list_dimensions ajudam a achar).
        É o chanfro de esboço do SolidWorks: encurta as duas linhas sem
        recriá-las, então cotas e tolerâncias existentes ficam. Distância ×
        distância (distance2_mm para chanfro desigual). Para o chanfro de um
        ressalto torneado é o jeito de mantê-lo no perfil do torno em vez de
        uma feature Chanfro separada."""
        return session.run(lambda app: se.sketch_corner_chamfer(app, corner_mm, distance_mm, distance2_mm))

    @mcp.tool()
    def sketch_corner_fillet(corner_mm: list[float], radius_mm: float) -> dict[str, Any]:
        """Filete DENTRO do esboço aberto, no canto de coordenada corner_mm
        [x, y]. Filete de esboço do SolidWorks nas duas linhas do canto —
        cotas e relações existentes ficam. Devolve o centro do arco."""
        return session.run(lambda app: se.sketch_corner_fillet(app, corner_mm, radius_mm))

    @mcp.tool()
    def sketch_undercut_din509(corner_mm: list[float], radius_mm: float = 0.8,
                               depth_mm: float = 0.3, width_mm: float = 0.0,
                               ramp_angle_deg: float = 15.0) -> dict[str, Any]:
        """Alívio DIN 509 forma E (saída de retífica) no canto interno
        corner_mm [x, y] de um perfil de revolução ABERTO para edição — furo ou
        eixo, o lado do material é lido das linhas. O canto junta a linha
        paralela à linha de centro (cilindro) e a do ressalto; o alívio entra
        no cilindro: raio radius_mm tangente ao ressalto e ao fundo,
        profundidade depth_mm, largura width_mm (0 = a da norma para o par
        r×t: E0,8×0,3 → 2,5) e rampa de ramp_angle_deg. As linhas originais são
        ENCURTADAS, não recriadas, e o alívio sai cotado (R, t, f, ângulo) com
        relações de tangência. Confira 'lost_dimensions': cota que ficava no
        pedaço apagado (raro — só quando o canto é o início das duas linhas)
        vem listada com valor e tolerância para ser refeita, e 'fully_defined'.
        Reabra o esboço com edit_sketch e feche com close_sketch depois."""
        return session.run(lambda app: se.sketch_undercut_din509(
            app, corner_mm, radius_mm, depth_mm, width_mm, ramp_angle_deg))

    # ------------------------------------------------------------ reparo
    @mcp.tool()
    def set_circular_pattern_axis(feature_name: str, face_at_mm: list[float]) -> dict[str, Any]:
        """Religa o eixo de um padrão circular à face cilíndrica/cônica que
        passa por face_at_mm [x, y, z] (coordenadas da peça; list_faces dá
        um ponto). É o conserto para "Selecione uma aresta linear como um
        eixo" depois de editar o perfil. Reconstrói e devolve ok."""
        return session.run(lambda app: r.set_circular_pattern_axis(app, feature_name, face_at_mm))

    @mcp.tool()
    def rename_features(names: dict[str, str]) -> dict[str, Any]:
        """Renomeia várias features de uma vez: {nome atual: nome novo}.
        Para na primeira que não existir e diz quais já foram."""
        return session.run(lambda app: r.rename_features(app, names))
