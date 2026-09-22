"""Entrypoint do servidor MCP: registra tools e roda sobre stdio."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from swmcp.com.session import SwSession
from swmcp.log import setup_logging

INSTRUCTIONS = """\
Servidor MCP do SolidWorks (Gromar). Unidades: tudo que entra e sai das tools
é milímetro e grau. Tools get_/list_/sw_status são somente-leitura. As demais
ALTERAM o documento ativo — mas nada é salvo em disco sem save_document[_as],
e salvar/sobrescrever/apagar só com pedido explícito do usuário. Fluxo típico
de modelagem: new_document → create_sketch(plano) → sketch_* → extrude/revolve
→ take_screenshot para conferir o resultado visualmente. O SolidWorks precisa
estar instalado nesta máquina; se não houver instância aberta, uma nova é
iniciada visível ao usuário.

Geometria por API sai EXATA, mas não confie na tela para saber isso: os snaps
de esboço do SolidWorks valem também para a API e arredondam o que se pede sem
avisar. As tools sketch_* desligam esses snaps e conferem cada coordenada
gravada; sketch_polyline desenha um perfil inteiro assim de uma vez. Depois de
cada feature, measure_bodies dá o volume medido para comparar com a conta feita
à mão — é o que pega cota errada, corte que pegou material demais e furo com o
tamanho trocado. Em extrude, reverse_direction muda o lado para onde a extrusão
cresce e both_directions cresce para os dois; flip é diferente — inverte qual
lado do perfil vira material e num corte apaga quase tudo.

Furo: hole_wizard usa o assistente de furação (simple/tap/counterbore/
countersink/taper_tap) com tamanho de norma — size='M20x2.5' + standard, os
mesmos nomes do diálogo, que saem da biblioteca do SolidWorks (list_hole_sizes
mostra os tamanhos e o Ø de broca de cada um; tamanho que falte só entra pelo
assistente, na UI). A API do assistente valida o nome do tamanho mas às vezes
ignora as dimensões da norma e gera um furo em polegada, então a tool confere o
que saiu e refaz com os números da biblioteca — o campo 'mode' diz se veio
'standard' ou 'legacy', e a geometria conferida é a pedida nos dois casos. Com
hole_type='tap' a representação de rosca entra junto; para rosca externa (ou
avulsa) use cosmetic_thread sobre a aresta achada por list_circular_edges +
select_circular_edge, que casam a aresta pela geometria em vez de exigir um
clique certeiro.

Engenharia reversa (tools mesh_*): trabalham numa malha de scanner 3D
(STL/OBJ/PLY em mm) processada por um motor em subprocesso — nada disso toca
o SolidWorks até mesh_section_to_sketch/mesh_primitive_to_sw. Fluxo:
mesh_import → mesh_align (assentar a peça nos eixos) → mesh_segment →
mesh_fit_primitive nas regiões lisas → materializar no SW → modelar → exportar
STL do modelo → mesh_deviation_map para conferir o desvio scan × CAD.
Lacuna de scan aparece como 'sem dado' no mapa — não é interpolada.

Estrutura soldada (weldment): sketch com linhas conectadas → close_sketch →
insert_structural_member(norma, tipo, tamanho, sketch) — os nomes vêm de
list_weldment_profiles (com filtro por norma devolve os tamanhos). A peça
vira weldment sozinha; get_cut_list lê a lista de corte (quantidade,
comprimento, ângulos, material) e insert_cut_list_table põe a tabela num
desenho. normalize_tube_cut refaz a boca de lobo de um tubo como corte
normal ao tubo (geometria de laser de tubo), na própria peça; use
check_body_interference para conferir. File Locations (templates, formatos
de folha, perfis) leem-se com get_file_locations e gravam-se com
set_file_location/apply_kongz_library — configuração persistente, só com
pedido explícito. sw_status esconde os perfis .sldlfp que o SolidWorks abre em
segundo plano (só conta em library_documents_hidden).
"""


def build_server() -> MCPServer:
    mcp = MCPServer("solidworks", instructions=INSTRUCTIONS)
    session = SwSession()

    from swmcp.tools import (
        assembly,
        connection,
        create,
        create_drawing,
        edit,
        mesh,
        output,
        read_drawing,
        read_model,
        review,
        script,
        settings,
        weldment,
    )

    connection.register(mcp, session)
    read_drawing.register(mcp, session)
    read_model.register(mcp, session)
    review.register(mcp, session)
    create.register(mcp, session)
    edit.register(mcp, session)
    output.register(mcp, session)
    assembly.register(mcp, session)
    create_drawing.register(mcp, session)
    script.register(mcp, session)
    mesh.register(mcp, session)
    weldment.register(mcp, session)
    settings.register(mcp, session)

    return mcp


def main() -> None:
    setup_logging()
    build_server().run()


if __name__ == "__main__":
    main()
