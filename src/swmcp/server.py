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
gravada; sketch_polyline desenha um perfil inteiro assim de uma vez e une o
vértice que fecha o contorno (sem isso o esboço parece fechado e a feature é
recusada sem explicação).

REGRA DA GROMAR — ESBOÇO SEMPRE TOTALMENTE DEFINIDO (preto, nunca azul).
Esboço feito por API nasce sub-definido; por isso extrude, revolve,
sheet_metal_base_flange e hole_wizard já amarram o esboço sozinhos (relações
+ cotas presas à origem) e devolvem sketch_definition.fully_defined — confira
esse campo, e se vier False resolva antes de seguir. Esboço mexido fora
dessas tools (ou de peça antiga) se amarra com fully_define_sketch(nome),
que serve para perfil, círculo e pontos de posição de furo;
fully_dimension_profile é a versão para perfil de revolução (cota diametral).

Chapa metálica: sheet_metal_base_flange faz a flange-base (espessura, raio,
fator K) de um perfil aberto — L de cantoneira, U de bandeja — ou fechado
(chapa plana), com Sheet-Metal e planificação. Desenhe pela face EXTERNA e
confira a caixa devolvida: se a espessura cresceu para fora, refaça com
thicken_reverse invertido.

Montagem: insert_component/set_component_transform põem a ORIGEM da peça em
(x,y,z) com rotation_deg [rx,ry,rz] (eixos da montagem, ordem X→Y→Z) e
fixed; conferem a posição gravada e devolvem a caixa do componente.
Prefira REFERÊNCIAS a posição fixa: select_component_entity escolhe face/
aresta/vértice/plano de um componente pela geometria (coordenadas da
montagem; cilindro e círculo pedem radius_mm) e add_mate (com alignment)
cria o mate. list_mates lê os mates de um componente;
replicate_component copia um componente para outros lugares refazendo os
mesmos mates nas entidades correspondentes (porta-etiqueta de um rasgo para
os outros rasgos) e confere que a cópia não saiu do lugar;
replace_component troca o arquivo mantendo posição e mates; mate_errors
mostra mate com referência perdida. Depois, check_interference.

Peça torneada: groove_relief faz o canal de alívio/saída de rosca com rampas em
ângulo e raio no fundo, e flats_across faz o rebaixo plano entre-faces varrendo
sozinho todo o trecho com diâmetro maior que a medida — cortar só a largura do
colar deixa um dente no cone vizinho. Depois de
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
'standard' ou 'legacy', e a geometria conferida é a pedida nos dois casos.
Furo de FOLGA de parafuso: hole_type='clearance', size='M6', standard='ISO',
fit='close'|'normal'|'loose' (Fino/Normal/Largo; M6 fino = Ø6,4). Vários
furos numa feature: model_positions_mm=[[x,y,z],...] em coordenadas da peça
(o esboço da face tem eixos próprios — X pode sair invertido). Com
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
Peça de REVOLUÇÃO (disco, flange, cubo, polia): mesh_align(mode='axis') acha o
eixo real pela geometria (o PCA erra o centro quando há furos/orelhas ou scan
de um lado só) e o põe em Z; mesh_revolve_profile tira o perfil (r, z) com os
cantos vivos e o raio de concordância de cada canto e, com draw=True, desenha
perfil + linha de centro num esboço que contém o eixo, pronto para revolve
(thickness_mm fecha um scan de um lado só — estimativa); mesh_detect_holes
acha os furos ao longo do eixo com Ø pelas paredes e o padrão angular (12
posições a cada 30°, quais faltam), e com draw=True desenha os círculos no
esboço ativo. mesh_apply_to_sw leva o corpo de malha do SolidWorks para o
mesmo sistema alinhado do motor (Mover/Copiar corpo), para modelar em cima
dele. Malha de milhões de triângulos visível deixa a API lenta: oculte com
set_body_visibility enquanto modela. mesh_deviation_map(reference_stl=
'active_doc') mede o documento aberto sem realinhar (STL nas coordenadas da
peça; bodies= escolhe os corpos). surface_from_faces vira as faces de um
sólido auxiliar em corpo de superfície (o lado que o scanner viu).

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

Conferir e ajustar peça existente: list_dimensions dá as cotas com NOME
COMPLETO (D1@Esboço10 — o nome curto se repete entre esboços) e a tolerância
de cada uma; set_dimension_tolerance aplica ajuste ISO (H7 furo / f7 eixo),
bilateral, simétrica etc. — em cota radial de perfil de revolução passe
show_as_diameter=True, senão o ajuste sai calculado sobre o raio.
check_rebuild_errors é o painel "O que está errado?" por API (com
sub-features); list_faces acha faces por geometria; sketch_status diz quais
entidades de um esboço estão soltas. Para pôr chanfro, filete ou alívio
DIN 509 DENTRO do perfil torneado (em vez de feature separada) abra o esboço
com edit_sketch e use sketch_corner_chamfer / sketch_corner_fillet /
sketch_undercut_din509 pela coordenada do canto: as linhas são encurtadas,
não recriadas, e as cotas ficam. Editar o perfil troca a identidade das faces
geradas por aquela linha: o que apontava para elas fica perdido —
check_rebuild_errors mostra, set_circular_pattern_axis religa o eixo de um
padrão; furo do assistente que perdeu a face se refaz com hole_wizard.

Bloco hidráulico (aprendido no 3-50200-92000): port_hole faz o pórtico G
inteiro numa feature (rebaixo d2×a + broca da rosca + canal), começando FORA
da face — o rebaixo que invade um ressalto de interface corta o ressalto; o
assistente não serve para isso porque o rebaixo customizado sai em polegada.
angled_channel fura inclinado (canal Ø7 de NG6 a 10°/12,5°) apontando o
destino com target_mm; canal que termina EXATAMENTE na parede de outro furo dá
erro de reconstrução (swFeatureError 51) — passe 1-2 mm. sketch_on_face e
batch_holes trabalham em coordenadas da PEÇA; o lote desliga o redesenho.
Depois de cada lote rode validate_model (reconstrução + esboços + massa do
carimbo) — nunca siga com feature em erro, e massa só vale com a árvore limpa.
dump_holes lê a furação de uma peça de referência para copiar o padrão;
organize_tree monta as pastas por face conferindo a ordem real da árvore;
copy_properties_from traz material/propriedades da referência; view_face tira
a foto normal a uma face (o iso deita peça com Z de eixo). Para testar uma
chamada de API duvidosa use run_sw_script(scratch=True) — nunca crie e apague
feature de teste na peça que o usuário está vendo.

Editar perfil torneado (aprendido no U1 do 3-50200-92000): sketch_relief_groove
faz o canal de alívio U1 (raio no pé, fundo, entrada em arco) no canto parede ×
ressalto; remove_sketch_chamfer/move_sketch_chamfer tiram ou mudam chanfro de
canto com as pontas exatas; sketch_arc sai sempre com o arco CURTO (o
CreateArc às vezes dá o maior). Antes e depois de mexer no perfil chame
profile_volume: a variação do corpo tem que bater com a do perfil. Esboço que
acumulou cotas de várias tentativas (validate_model avisa) se conserta com
sketch_redefine — apaga tudo e cota uma vez; não empilhe cotas por cima.
fillet_circular_edges, set_hole_depth e replace_hole_with_channel ajustam a
furação sem script.

Desenho de cliente em PDF: pdf_drawing_crop renderiza cada vista em 200-300
dpi (a folha inteira sai ilegível; extração vetorial de PDF Creo não serve) e
com view_scale dá mm por pixel para medir o que não está cotado. Desenho
Siemens é 1º diedro (ISO E): a vista posta à DIREITA é a vista pela esquerda.
Notação de rosca M16-30/38 = rosca 30 / broca 38. pdf_compare_table monta a
tabela comparativa de dois desenhos com recorte por cota.
"""


def build_server() -> MCPServer:
    mcp = MCPServer("solidworks", instructions=INSTRUCTIONS)
    session = SwSession()

    from swmcp.tools import (
        assembly,
        bodies,
        connection,
        create,
        create_drawing,
        edit,
        inspect_edit,
        machining,
        mesh,
        output,
        pdf,
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
    inspect_edit.register(mcp, session)
    machining.register(mcp, session)
    pdf.register(mcp, session)
    output.register(mcp, session)
    bodies.register(mcp, session)
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
