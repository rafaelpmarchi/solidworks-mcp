"""Tools de estrutura soldada (weldment): perfis, membros, lista de corte."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.com.wrappers import weldment as w


def register(mcp: MCPServer, session: SwSession) -> None:
    @mcp.tool()
    def list_weldment_profiles(standard: str | None = None, type: str | None = None) -> dict[str, Any]:
        """Perfis de weldment disponíveis (biblioteca do SolidWorks + pastas do
        usuário): norma (iso, ansi, DIN…), tipo (square tube, pipe, c channel…)
        e caminho. Com filtro por norma ou tipo devolve também os tamanhos
        ("20 x 20 x 2"), que são o que insert_structural_member espera em size.
        Somente leitura."""
        return session.run(lambda app: w.list_profiles(app, standard, type))

    @mcp.tool()
    def insert_weldment_feature() -> dict[str, Any]:
        """Marca a peça ativa como weldment (feature 'Soldagem'): corpos viram
        itens de lista de corte e não se fundem. insert_structural_member já faz
        isso sozinho; use esta tool quando quiser só a marcação."""
        return session.run(w.insert_weldment_feature)

    @mcp.tool()
    def insert_structural_member(
        standard: str,
        type: str,
        size: str | None,
        sketch: str,
        segments: list[str] | None = None,
        corner: str | None = "miter",
        connected: str = "simple",
        angle_deg: float = 0.0,
        mirror: str | None = None,
        gap_mm: float = 0.0,
    ) -> dict[str, Any]:
        """Insere um membro estrutural (Structural Member) na peça ativa ao longo
        dos segmentos de um sketch (feche o sketch antes; list_features dá o nome).

        standard/type/size vêm de list_weldment_profiles (ex.: "iso",
        "square tube", "20 x 20 x 2"). segments=None usa todos os segmentos do
        sketch como um único grupo — eles precisam formar caminho contínuo e
        coplanar (linhas conectadas); senão liste só os nomes ("Linha1",…).
        corner: miter | butt1 | butt2 | None (sem tratamento de canto).
        connected: simple | coped (corte nas junções). angle_deg gira o perfil;
        mirror: horizontal | vertical espelha; gap_mm é a folga entre segmentos.
        A peça vira weldment automaticamente. Nada é salvo em disco."""
        return session.run(lambda app: w.insert_structural_member(
            app, standard, type, size, sketch, segments, corner, connected, angle_deg, mirror, gap_mm,
        ))

    @mcp.tool()
    def get_cut_list(update: bool = True) -> dict[str, Any]:
        """Lista de corte da peça weldment ativa: um item por pasta da lista
        (perfil × comprimento), com quantidade, comprimento, ângulos de corte,
        material e as demais propriedades sob chave canônica em inglês (LENGTH,
        ANGLE1…), mesmo com a UI em português. update=True recalcula a lista
        antes de ler (não salva)."""
        return session.run(lambda app: w.get_cut_list(app, update))

    @mcp.tool()
    def insert_cut_list_table(
        view: str, x_mm: float, y_mm: float, template: str | None = None,
    ) -> dict[str, Any]:
        """Insere a tabela de lista de corte no desenho ativo, ancorada em
        (x,y) mm da folha e ligada à vista nomeada (create_drawing_from_model
        devolve os nomes). template: .sldwldtbt; sem informar usa o da
        instalação. Nada é salvo."""
        return session.run(lambda app: w.insert_cut_list_table(app, view, x_mm, y_mm, template))

    @mcp.tool()
    def normalize_tube_cut(
        body: str | None = None, check_against: str | None = None, margin_mm: float = 2.0,
    ) -> dict[str, Any]:
        """Refaz a boca de lobo de um tubo de weldment como corte NORMAL ao tubo,
        que é o que a máquina de corte a laser de tubo consegue produzir.

        Método: junção das arestas interna e externa da boca (em cada ângulo, a
        mais recuada, para nunca invadir o outro tubo) → superfície radial →
        Substituir face nas faces da boca → superfície auxiliar apagada. As
        features ficam na peça ativa, sobre o corpo do tubo (nome de
        list_features/Corpos sólidos; opcional se a peça tem um corpo só).
        check_against: nome de outro corpo para medir a interferência que
        sobrou (mm³). Só boca completa (dá a volta no tubo). Nada é salvo."""
        return session.run(lambda app: w.normalize_tube_cut(app, body, check_against, margin_mm=margin_mm))

    @mcp.tool()
    def check_body_interference(body_a: str, body_b: str) -> dict[str, Any]:
        """Volume de interseção (mm³) entre dois corpos sólidos da peça ativa
        (nomes da pasta Corpos sólidos). Somente leitura."""
        return session.run(lambda app: w.body_interference(app, body_a, body_b))

    @mcp.tool()
    def create_weldment_profile(
        shape: str,
        standard: str,
        type: str,
        size: str | None = None,
        od_mm: float = 0.0,
        wall_mm: float = 0.0,
        width_mm: float = 0.0,
        height_mm: float = 0.0,
        corner_radius_mm: float | None = None,
        description: str | None = None,
        folder: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Cria um perfil de weldment novo (.SLDLFP) na biblioteca, no layout
        <pasta>/<norma>/<tipo>/<tamanho>.SLDLFP — o mesmo da biblioteca KONGZ
        (ex.: usiminas / tubo redondo / "2in x 2.0mm").

        shape: round_tube (od_mm, wall_mm) | rect_tube (width_mm, height_mm,
        wall_mm, corner_radius_mm opcional, padrão 2×parede) | square_tube
        (width_mm, wall_mm) | round_bar (od_mm) | flat_bar (width_mm,
        height_mm). size: nome do arquivo/tamanho; sem informar vira
        "50.8 x 2mm", "30 x 40 x 1.2mm" etc. folder: pasta raiz dos perfis; sem
        informar usa a primeira pasta de perfis do usuário (KONGZ). Grava em
        disco (só com pedido explícito); recusa sobrescrever sem overwrite.
        O perfil fica disponível na hora para insert_structural_member."""
        return session.run(lambda app: w.create_weldment_profile(
            app, shape, standard, type, size, od_mm, wall_mm, width_mm, height_mm,
            corner_radius_mm, description, folder, overwrite,
        ))
