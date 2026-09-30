"""Tools de bloco hidráulico e furação por coordenadas da peça: pórtico G,
canal inclinado, esboço em face, furação em lote, validação, leitura de furos,
pastas por face e cópia de propriedades."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import channels as ch
from swmcp.com.wrappers import edit as e
from swmcp.com.wrappers import output as o
from swmcp.com.wrappers import repair as r
from swmcp.com.wrappers import validate as v
from swmcp.domain.ports import PIPE_PORTS


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def port_hole(face_x_mm: float, face_y_mm: float, face_z_mm: float, size: str,
                  name: str = "", spot_depth_mm: float = 1.0,
                  thread_drill_depth_mm: float | None = None,
                  channel_diameter_mm: float = 0.0, channel_length_mm: float = 0.0,
                  spot_diameter_mm: float | None = None) -> dict[str, Any]:
        """Pórtico hidráulico G numa feature: rebaixo de vedação d2×a, broca da
        rosca até t e, opcional, o canal de ligação (Ø e comprimento medido da
        face) com ponta de 118°. O ponto (mm, coordenadas da PEÇA) é o centro
        do pórtico em cima da face plana; o furo entra normal a ela.
        size: G1/8, G1/4, G3/8, G1/2, G3/4 (d2/b/t da DIN EN ISO 1179-1, tabela
        Siemens; broca ISO 228). spot_depth_mm é o "a" do desenho (1 ou 5,5).
        Feito como corte por revolução porque o rebaixo customizado do
        assistente sai em polegada no SW2023. O perfil começa 5 mm FORA da
        face: rebaixo que invade um ressalto corta o ressalto também.
        Volume removido e erro de reconstrução são conferidos; se falhar, nada
        fica na peça."""
        return session.run(lambda app: ch.port_hole(
            app, [face_x_mm, face_y_mm, face_z_mm], size, name, spot_depth_mm,
            thread_drill_depth_mm, channel_diameter_mm, channel_length_mm, spot_diameter_mm))

    @mcp.tool()
    def list_pipe_ports() -> list[dict[str, Any]]:
        """Tabela de pórticos G usada por port_hole (d2, b, t, broca, Ø menor, mm)."""
        return [vars(p) for p in PIPE_PORTS.values()]

    @mcp.tool()
    def angled_channel(start_x_mm: float, start_y_mm: float, start_z_mm: float,
                       diameter_mm: float, name: str,
                       target_mm: list[float] | None = None,
                       direction: list[float] | None = None, length_mm: float = 0.0,
                       overshoot_mm: float = 2.0, extend_past_target_mm: float = 1.5) -> dict[str, Any]:
        """Canal furado reto em qualquer direção DENTRO de um plano de vista
        (em planta, elevação ou perfil) — ex.: os Ø7 inclinados 10°/12,5° de
        interface NG6. start = boca do canal na face (mm, peça). Diga o destino
        com target_mm=[x,y,z] (o canal passa extend_past_target_mm além, para
        não terminar tangente ao outro furo — isso dá erro de reconstrução) ou
        com direction=[dx,dy,dz] + length_mm. Corte por revolução num plano
        auxiliar paralelo a um plano base (fica escondido, nomeado pelo canal)."""
        return session.run(lambda app: ch.angled_channel(
            app, [start_x_mm, start_y_mm, start_z_mm], diameter_mm, name, length_mm,
            direction, target_mm, overshoot_mm, extend_past_target_mm))

    @mcp.tool()
    def sketch_on_face(face_x_mm: float, face_y_mm: float, face_z_mm: float,
                       polylines_mm: list[list[list[float]]] | None = None,
                       circles_mm: list[list[float]] | None = None,
                       rectangles_mm: list[list[list[float]]] | None = None) -> dict[str, Any]:
        """Abre esboço na face do ponto e desenha em COORDENADAS DA PEÇA (mm):
        polylines_mm = contornos fechados [[x,y,z],...]; circles_mm = [[x,y,z,Ø]];
        rectangles_mm = [[[canto1],[canto2]]]. Recusa ponto fora do plano da
        face. O esboço fica ABERTO: siga com extrude (ressalto 0,5 mm de
        interface de válvula, rebaixo, corte)."""
        return session.run(lambda app: ch.sketch_on_face(
            app, [face_x_mm, face_y_mm, face_z_mm], polylines_mm or [], circles_mm or [],
            rectangles_mm or []))

    @mcp.tool()
    def batch_holes(items: list[dict[str, Any]], stop_on_error: bool = False) -> dict[str, Any]:
        """Vários furos numa chamada, com o redesenho desligado (rápido).
        Cada item: {"kind": "wizard"|"port"|"channel", ...parâmetros}:
          wizard  → os de hole_wizard (face_x_mm, face_y_mm, face_z_mm, depth_mm,
                    size/diameter_mm, hole_type, thread_depth_mm,
                    model_positions_mm...) + "name" para renomear;
          port    → face_point_mm=[x,y,z] (centro do pórtico na face),
                    size, name, spot_depth_mm, thread_drill_depth_mm,
                    channel_diameter_mm, channel_length_mm;
          channel → start_mm=[x,y,z], diameter_mm, name, target_mm ou
                    direction + length_mm.
        Devolve ok/erro por item. Rode validate_model depois do lote."""
        return session.run(lambda app: ch.batch_holes(app, items, stop_on_error))

    @mcp.tool()
    def validate_model(expected_mass_kg: float | None = None, tolerance_pct: float = 2.0,
                       density_kg_m3: float = 7850.0, expected_bodies: int = 1) -> dict[str, Any]:
        """Confere a peça ativa numa chamada: reconstrução sem erro/aviso, todo
        esboço totalmente definido (regra Gromar), nº de corpos e massa contra
        a do carimbo (expected_mass_kg, ±tolerance_pct). Rode DEPOIS DE CADA
        LOTE de features, antes de seguir. Massa só vale com a árvore limpa:
        feature em erro não corta e a massa parece certa."""
        return session.run(lambda app: v.validate_model(
            app, expected_mass_kg, tolerance_pct, density_kg_m3, expected_bodies))

    @mcp.tool()
    def dump_holes(name_filter: str = "") -> list[dict[str, Any]]:
        """Furos do assistente da peça ativa: tipo, norma, tamanho, Ø, profundidades,
        rebaixo e a POSIÇÃO de cada furo em coordenadas da peça, com a direção
        em que entra. Serve para copiar o padrão de modelagem de uma peça de
        referência (abra-a com sw_open_document antes). Somente-leitura."""
        return session.run(lambda app: v.dump_holes(app, name_filter))

    @mcp.tool()
    def organize_tree(groups: list[dict[str, Any]], renames: dict[str, str] | None = None,
                      after: str = "") -> dict[str, Any]:
        """Organiza a árvore em pastas: groups=[{"name": "Face +Y (KZ)",
        "features": [...]}, ...] na ordem desejada; renames={atual: novo}
        aplicado antes. As features são reordenadas em sequência a partir de
        'after' (padrão: antes da 1ª delas) e cada grupo vira pasta. A ordem é
        CONFERIDA lendo a árvore (ReorderFeature devolve False mesmo movendo);
        se divergir, nenhuma pasta é criada. O plano auxiliar "Plano <nome>"
        de port_hole/angled_channel entra junto na pasta sozinho. Rode
        validate_model depois: reordenar pode mudar qual face um furo pega."""
        return session.run(lambda app: r.organize_tree(app, groups, renames, after))

    @mcp.tool()
    def copy_properties_from(source_path: str, include_material: bool = True,
                             overwrite: bool = False) -> dict[str, Any]:
        """Copia material e propriedades customizadas (documento e configuração
        ativa) de uma peça de referência para o documento ativo. A referência
        abre somente-leitura e fecha no fim. overwrite=False mantém o que o
        documento ativo já tiver. Não salva nada."""
        return session.run(lambda app: e.copy_properties_from(
            app, source_path, include_material, overwrite))

    @mcp.tool()
    def view_face(normal: list[float], path: str = "", box_mm: list[float] | None = None,
                  hide_planes: bool = True) -> dict[str, Any]:
        """Screenshot olhando de frente para uma face: normal = eixo PARA FORA
        da face ([0,-1,0] = face -Y). box_mm=[x1,y1,z1,x2,y2,z2] dá zoom na
        região. Esconde os planos auxiliares visíveis. Retorna o PNG — leia
        para ver. O iso padrão do SolidWorks deita peça com Z de eixo."""
        import os
        import tempfile

        caminho = path or os.path.join(tempfile.gettempdir(), "swmcp_view_face.png")
        return session.run(lambda app: o.view_face(app, normal, caminho, box_mm, hide_planes))

    @mcp.tool()
    def fillet_circular_edges(edges_mm: list[list[float]], radius_mm: float,
                              name: str = "") -> dict[str, Any]:
        """Filete em várias arestas circulares de uma vez, achadas pela
        geometria: edges_mm=[[cx, cy, cz, Ø], ...] (list_circular_edges dá os
        valores). Ex.: R0,6 no fundo dos rebaixos Ø32 × 2,7. Feature com erro é
        desfeita. name renomeia."""
        return session.run(lambda app: ch.fillet_circular_edges(app, edges_mm, radius_mm, name))

    @mcp.tool()
    def set_hole_depth(feature_name: str, depth_mm: float) -> dict[str, Any]:
        """Muda a profundidade de um furo do assistente e confere: se não pegar
        ou o furo ficar com erro (ex.: terminando tangente a outro furo,
        swFeatureError 51), volta a profundidade anterior."""
        return session.run(lambda app: ch.set_hole_depth(app, feature_name, depth_mm))

    @mcp.tool()
    def replace_hole_with_channel(hole_feature: str, start_mm: list[float], diameter_mm: float,
                                  name: str, length_mm: float = 0.0,
                                  direction: list[float] | None = None,
                                  target_mm: list[float] | None = None) -> dict[str, Any]:
        """Troca um furo reto por canal inclinado (como angled_channel) no MESMO
        lugar da árvore e da pasta — ex.: o Ø7 da NG6 que o desenho pede a 10°.
        O furo é suprimido enquanto o canal é feito; se o canal falhar, ele
        volta."""
        return session.run(lambda app: ch.replace_hole_with_channel(
            app, hole_feature, start_mm, diameter_mm, name, length_mm, direction, target_mm))
