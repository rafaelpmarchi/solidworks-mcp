"""Furos do assistente de furação, roscas cosméticas e seleção de arestas
circulares por geometria (escrita). Executa no thread STA.

O furo sai pelo assistente de furação com tamanho de NORMA (como no diálogo:
Ansi Metric / Furo roscado / M20x2.5) — os números vêm da biblioteca do próprio
SolidWorks, lida em hole_library.

Só que a API não é confiável nesse caminho: medido no SW2023, HoleWizard5
valida o nome do tamanho contra a base (aceita "M20x2.5" em Ansi Metric e
recusa "M20", que só existe em ISO — prova de que está lendo a tabela certa) e
mesmo assim gera um furo padrão em polegada, Ø25,4 com rebaixo Ø50,8.
ModifyDefinition não corrige: IWizardHoleFeatureData2 devolve 0 em todo
diâmetro. Por isso hole_wizard CONFERE o diâmetro que saiu e, quando o
assistente ignorou a norma, refaz a feature no modo legado usando as dimensões
da biblioteca — a peça sai certa de qualquer jeito e o retorno diz por qual
caminho ("standard" ou "legacy"). A rosca entra como representação cosmética,
que é o usual em desenho de fabricação.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from swmcp.com import units
from swmcp.com.constants import ADV_WIZARD_HOLE_TYPES
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers import hole_library
from swmcp.domain.placement import apply_transform

log = logging.getLogger(__name__)

# Tolerância ao casar uma aresta circular pedida com as do corpo (mm).
EDGE_MATCH_TOLERANCE_MM = 0.01


def _model(doc: Any) -> Any:
    return cast_to(doc, "IModelDoc2")


def _active_doc(app: Any) -> Any:
    doc = com_get(app, "ActiveDoc")
    if doc is None:
        raise ComCallError("ActiveDoc", (), None, "nenhum documento ativo no SolidWorks")
    return doc


def _bodies(app: Any) -> list[Any]:
    part = cast_to(_active_doc(app), "IPartDoc")
    return list(com_call(part, "GetBodies2", 0, True) or [])


# ------------------------------------------------------- arestas circulares

def list_circular_edges(app: Any, min_diameter_mm: float = 0.0,
                        max_diameter_mm: float | None = None) -> list[dict[str, Any]]:
    """Arestas circulares do corpo, com centro (mm), diâmetro (mm) e eixo.

    É o caminho para achar a aresta de um filete/rosca sem depender de acertar
    um ponto em cima dela no SelectByID2 (que falha por tolerância).
    """
    saida: list[dict[str, Any]] = []
    for raw_body in _bodies(app):
        body = cast_to(raw_body, "IBody2")
        for raw_edge in com_call(body, "GetEdges") or []:
            edge = cast_to(raw_edge, "IEdge")
            curve = cast_to(com_call(edge, "GetCurve"), "ICurve")
            if not com_call(curve, "IsCircle"):
                continue
            p = com_call(curve, "CircleParams")  # [cx,cy,cz, ax,ay,az, raio]
            diametro = units.to_mm(p[6]) * 2.0
            if diametro < min_diameter_mm:
                continue
            if max_diameter_mm is not None and diametro > max_diameter_mm:
                continue
            saida.append({
                "center_mm": [round(units.to_mm(p[i]), 4) for i in range(3)],
                "axis": [round(p[i], 4) for i in range(3, 6)],
                "diameter_mm": round(diametro, 4),
            })
    saida.sort(key=lambda e: (e["center_mm"], e["diameter_mm"]))
    return saida


def _find_circular_edge(app: Any, center_mm: list[float], diameter_mm: float,
                        tolerance_mm: float) -> Any:
    for raw_body in _bodies(app):
        body = cast_to(raw_body, "IBody2")
        for raw_edge in com_call(body, "GetEdges") or []:
            edge = cast_to(raw_edge, "IEdge")
            curve = cast_to(com_call(edge, "GetCurve"), "ICurve")
            if not com_call(curve, "IsCircle"):
                continue
            p = com_call(curve, "CircleParams")
            if abs(units.to_mm(p[6]) * 2.0 - diameter_mm) > tolerance_mm:
                continue
            if all(abs(units.to_mm(p[i]) - center_mm[i]) <= tolerance_mm for i in range(3)):
                return raw_edge
    return None


def select_circular_edge(app: Any, center_mm: list[float], diameter_mm: float,
                         append: bool = False,
                         tolerance_mm: float = EDGE_MATCH_TOLERANCE_MM) -> dict[str, Any]:
    """Seleciona a aresta circular de centro e diâmetro dados (mm).

    Casa pela geometria e seleciona o próprio objeto (IEntity::Select4), então
    não depende da tolerância de clique do SelectByID2.
    """
    raw_edge = _find_circular_edge(app, center_mm, diameter_mm, tolerance_mm)
    if raw_edge is None:
        raise ComCallError(
            "select_circular_edge", (center_mm, diameter_mm), None,
            "nenhuma aresta circular com esse centro e diâmetro "
            "(use list_circular_edges para ver as que existem)",
        )
    model = _model(_active_doc(app))
    if not append:
        com_call(model, "ClearSelection2", True)
    if not com_call(cast_to(raw_edge, "IEntity"), "Select4", append, None):
        raise ComCallError("Select4", (center_mm, diameter_mm), None, "aresta não selecionada")
    n = com_call(cast_to(com_get(model, "SelectionManager"), "ISelectionMgr"),
                 "GetSelectedObjectCount2", -1)
    return {"selected": True, "selection_count": n}


# -------------------------------------------------------------------- faces

def select_face_at(app: Any, x_mm: float, y_mm: float, z_mm: float,
                   append: bool = False, tolerance_mm: float = 0.1) -> dict[str, Any]:
    """Seleciona a face do corpo que passa pelo ponto (mm).

    O SelectByID2 com coordenadas depende do estado da janela e devolve False
    mesmo com o ponto em cima da face; aqui a face é achada pela geometria
    (GetClosestPointOn em cada face) e selecionada pelo próprio objeto.
    """
    melhor, menor = None, None
    alvo = (units.from_mm(x_mm), units.from_mm(y_mm), units.from_mm(z_mm))
    for raw_body in _bodies(app):
        body = cast_to(raw_body, "IBody2")
        for raw_face in com_call(body, "GetFaces") or []:
            face = cast_to(raw_face, "IFace2")
            perto = com_call(face, "GetClosestPointOn", *alvo)  # [x, y, z, ...]
            if not perto:
                continue
            dist = sum((perto[i] - alvo[i]) ** 2 for i in range(3)) ** 0.5
            if menor is None or dist < menor:
                melhor, menor = raw_face, dist
    if melhor is None or units.to_mm(menor) > tolerance_mm:
        achado = "nenhuma face" if melhor is None else f"a face mais próxima está a {units.to_mm(menor):.3f}mm"
        raise ComCallError("select_face_at", (x_mm, y_mm, z_mm), None,
                           f"{achado} do ponto — confira as coordenadas (mm)")
    model = _model(_active_doc(app))
    if not append:
        com_call(model, "ClearSelection2", True)
    if not com_call(cast_to(melhor, "IEntity"), "Select4", append, None):
        raise ComCallError("Select4", (x_mm, y_mm, z_mm), None, "face não selecionada")
    n = com_call(cast_to(com_get(model, "SelectionManager"), "ISelectionMgr"),
                 "GetSelectedObjectCount2", -1)
    return {"selected": True, "distance_mm": round(units.to_mm(menor), 4), "selection_count": n}


# ------------------------------------------------------------------- furos

def _position_sketch(feature: Any) -> Any:
    """Sub-sketch de POSICIONAMENTO do furo.

    O furo tem dois sub-esboços: o do perfil (com segmentos) e o de posição
    (só pontos — um por furo). Contar "um ponto" só vale até o esboço de
    posição ganhar o segundo furo.
    """
    achado = None
    raw = com_get(feature, "GetFirstSubFeature")
    while raw:
        sub = cast_to(raw, "IFeature")
        if com_get(sub, "GetTypeName2") == "ProfileFeature":
            sketch = cast_to(com_call(sub, "GetSpecificFeature2"), "ISketch")
            if (com_call(sketch, "GetSketchPoints2") or []) and not (com_call(sketch, "GetSketchSegments") or []):
                achado = sub
        raw = com_get(sub, "GetNextSubFeature")
    return achado


def _delete_feature(app: Any, feature: Any) -> None:
    model = _model(_active_doc(app))
    com_call(model, "ClearSelection2", True)
    com_call(feature, "Select2", False, 0)
    com_call(model, "DeleteSelection", False)


def _count_cylinders(app: Any, diameter_mm: float, tolerance_mm: float = 0.05) -> int:
    """Quantas faces cilíndricas do corpo têm esse diâmetro."""
    total = 0
    for raw_body in _bodies(app):
        body = cast_to(raw_body, "IBody2")
        for raw_face in com_call(body, "GetFaces") or []:
            surf = cast_to(com_call(cast_to(raw_face, "IFace2"), "GetSurface"), "ISurface")
            if com_call(surf, "IsCylinder"):
                d = units.to_mm(com_call(surf, "CylinderParams")[6]) * 2.0
                if abs(d - diameter_mm) <= tolerance_mm:
                    total += 1
    return total


def _volume_mm3(app: Any) -> float:
    body = cast_to(_bodies(app)[0], "IBody2")
    return com_call(body, "GetMassProperties", 7850.0)[3] * 1e9


# quanto o volume removido pode fugir do cilindro teórico (ponta da broca, chanfro)
HOLE_VOLUME_TOLERANCE = 0.05


def _position_sketch_or_fail(feature: Any) -> Any:
    sketch_pos = _position_sketch(feature)
    if sketch_pos is None:
        raise ComCallError("hole_wizard", (com_get(feature, "Name"),), None,
                           "furo criado mas sem sketch de posicionamento para centralizar")
    return sketch_pos


def model_to_sketch_mm(feature: Any, pontos_modelo: list[list[float]]) -> list[list[float]]:
    """Converte pontos da peça (mm) para as coordenadas do esboço de posição.

    O esboço de uma face tem eixos próprios (na face Z=0 de uma cantoneira o X
    do esboço sai invertido em relação ao da peça); chutar essa orientação é o
    que põe o furo na aba errada. A transformada vem do próprio esboço.
    """
    sketch = cast_to(com_call(_position_sketch_or_fail(feature), "GetSpecificFeature2"), "ISketch")
    xf = cast_to(com_call(sketch, "ModelToSketchTransform"), "IMathTransform")
    arr = list(com_get(xf, "ArrayData"))
    saida = []
    for p in pontos_modelo:
        x, y, _ = apply_transform(arr, (p[0], p[1], p[2]))
        saida.append([round(x, 6), round(y, 6)])
    return saida


def _move_hole_to(app: Any, feature: Any, alvos: list[list[float]]) -> str:
    """Põe os pontos do furo nas posições pedidas (coordenadas do sketch da face).

    O assistente cria a feature com um ponto só; o primeiro é movido e os
    demais são criados no mesmo esboço — uma feature, vários furos, como no
    diálogo.
    """
    model = _model(_active_doc(app))
    ext = com_get(model, "Extension")
    nome_sketch = com_get(_position_sketch_or_fail(feature), "Name")
    skm = cast_to(com_get(model, "SketchManager"), "ISketchManager")
    com_call(model, "ClearSelection2", True)
    com_call(ext, "SelectByID2", nome_sketch, "SKETCH", 0.0, 0.0, 0.0, False, 0, None,
             swconst().swSelectOptionDefault)
    com_call(skm, "InsertSketch", True)
    sketch = cast_to(com_get(skm, "ActiveSketch"), "ISketch")
    pontos = [cast_to(p, "ISketchPoint") for p in com_call(sketch, "GetSketchPoints2") or []]
    for ponto, alvo in zip(pontos, alvos):
        com_call(ponto, "SetCoords", units.from_mm(alvo[0]), units.from_mm(alvo[1]), 0.0)
    if len(alvos) > len(pontos):
        antes = com_get(skm, "AddToDB")
        skm.AddToDB = True   # sem isso o ponto novo "gruda" em outra entidade por inferência
        try:
            for alvo in alvos[len(pontos):]:
                if com_call(skm, "CreatePoint", units.from_mm(alvo[0]), units.from_mm(alvo[1]), 0.0) is None:
                    raise ComCallError("CreatePoint", tuple(alvo), None, "ponto do furo não criado")
        finally:
            skm.AddToDB = antes
    com_call(skm, "InsertSketch", True)
    com_call(model, "ForceRebuild3", False)
    return nome_sketch


def hole_wizard(
    app: Any,
    face_x_mm: float,
    face_y_mm: float,
    face_z_mm: float,
    depth_mm: float,
    diameter_mm: float = 0.0,
    size: str = "",
    standard: str = "Ansi Metric",
    hole_type: str = "simple",
    thread_depth_mm: float = 0.0,
    through_all: bool = False,
    position_mm: list[float] | None = None,
    add_cosmetic_thread: bool = True,
    fit: str = "normal",
    positions_mm: list[list[float]] | None = None,
    model_positions_mm: list[list[float]] | None = None,
    fully_define: bool = True,
) -> dict[str, Any]:
    """Furo do assistente de furação na face apontada pelas coordenadas (mm).

    Dois jeitos de dizer o tamanho:
    - size="M20x2.5" (+ standard): vem da biblioteca do SolidWorks, como no
      diálogo do assistente — o Ø da broca é o da norma, não um chute.
    - diameter_mm: o furo é do tamanho pedido, sem norma.

    hole_type: simple, clearance (folga de parafuso, com fit close/normal/
    loose), tap (macho reto), counterbore, countersink, taper_tap.
    Posição, de um destes jeitos (vários pontos = vários furos numa feature):
    - model_positions_mm: [[x,y,z], ...] na peça — o jeito seguro, porque o
      esboço da face tem eixos próprios (X pode sair invertido);
    - positions_mm: [[x,y], ...] nas coordenadas do sketch da face;
    - position_mm: um ponto só no sketch; o padrão [0, 0] é a origem.
    fully_define cota o esboço de posição até ficar totalmente definido.

    Com size, tenta primeiro criar o furo pela norma e CONFERE o Ø que saiu:
    medido no SW2023, o HoleWizard5 valida o nome do tamanho contra a base e
    ainda assim gera um furo padrão em polegada (Ø25,4/Ø50,8). Quando isso
    acontece a feature é desfeita e refeita no modo legado do assistente com as
    dimensões da própria biblioteca — a peça sai certa de qualquer forma, e o
    retorno diz por qual caminho ("standard" ou "legacy") ela saiu.
    """
    tipo_legado = ADV_WIZARD_HOLE_TYPES.get(hole_type)
    if tipo_legado is None:
        raise ComCallError("hole_wizard", (hole_type,), None,
                           f"hole_type deve ser um de {sorted(ADV_WIZARD_HOLE_TYPES)}")
    model = _model(_active_doc(app))
    fm = cast_to(com_get(model, "FeatureManager"), "IFeatureManager")
    c = swconst()
    fim = c.swEndCondThroughAll if through_all else c.swEndCondBlind
    if sum(v is not None for v in (position_mm, positions_mm, model_positions_mm)) > 1:
        raise ComCallError("hole_wizard", (), None,
                           "use só um de position_mm, positions_mm ou model_positions_mm")
    if model_positions_mm is not None and any(len(p) != 3 for p in model_positions_mm):
        raise ComCallError("hole_wizard", (), None, "model_positions_mm leva pontos [x, y, z]")
    folga = hole_type == "clearance"

    def alvos_de(feature: Any) -> list[list[float]]:
        if model_positions_mm:
            return model_to_sketch_mm(feature, model_positions_mm)
        if positions_mm:
            return [[float(p[0]), float(p[1])] for p in positions_mm]
        return [list(position_mm or [0.0, 0.0])]

    n_furos = len(model_positions_mm or positions_mm or [None])

    biblioteca = None
    if folga and not size:
        raise ComCallError("hole_wizard", (hole_type,), None,
                           "furo de folga precisa de size (ex.: 'M6' com standard='ISO')")
    if size:
        tipo_biblioteca = ("tap" if hole_type in ("tap", "taper_tap")
                           else "clearance" if folga else "simple")
        biblioteca = hole_library.resolve_size(app, size, standard, tipo_biblioteca, fit)
        diameter_mm = biblioteca["drill_diameter_mm"]
    if not diameter_mm:
        raise ComCallError("hole_wizard", (size, diameter_mm), None,
                           "informe size (tamanho da biblioteca) ou diameter_mm")

    def cria_legado() -> Any:
        select_face_at(app, face_x_mm, face_y_mm, face_z_mm)
        return com_call(
            fm, "HoleWizard5",
            c.swWzdLegacy, getattr(c, tipo_legado), 0, "", fim,
            units.from_mm(diameter_mm), units.from_mm(depth_mm), units.from_mm(thread_depth_mm),
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            "", False, True, True, False, False, False,
        )

    cilindros_antes = _count_cylinders(app, diameter_mm)
    volume_antes = _volume_mm3(app)
    esperado_mm3 = math.pi * (diameter_mm / 2.0) ** 2 * depth_mm * n_furos

    def furo_confere() -> str | None:
        """None se o furo saiu como pedido; senão diz o que está errado."""
        novos = _count_cylinders(app, diameter_mm) - cilindros_antes
        if novos < n_furos:
            return f"apareceram {novos} faces Ø{diameter_mm:.2f} para {n_furos} furo(s)"
        if not through_all:
            removido = volume_antes - _volume_mm3(app)
            if abs(removido - esperado_mm3) > esperado_mm3 * HOLE_VOLUME_TOLERANCE:
                return (f"removeu {removido:.0f}mm³ onde Ø{diameter_mm:.2f}×{depth_mm:.2f} "
                        f"pede {esperado_mm3:.0f}mm³")
        return None

    modo = "legacy"
    feat = None
    if biblioteca:
        select_face_at(app, face_x_mm, face_y_mm, face_z_mm)
        feat = com_call(
            fm, "HoleWizard5",
            c.swWzdTap if hole_type in ("tap", "taper_tap") else c.swWzdHole,
            biblioteca["standard_index"],
            hole_library.fastener_type_index(standard, biblioteca["hole_type"]),
            biblioteca["size"], fim,
            # furo de folga: o Ø do ajuste vai no Diameter — é assim que o
            # assistente sai com o Fino/Largo em vez do Normal
            units.from_mm(diameter_mm) if folga else 0.0,
            units.from_mm(depth_mm), units.from_mm(thread_depth_mm),
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            "", False, True, True, False, False, False,
        )
        if feat is not None:
            feature = cast_to(feat, "IFeature")
            _move_hole_to(app, feature, alvos_de(feature))
            problema = furo_confere()
            if problema is None:
                modo = "standard"
            else:
                log.warning("o assistente ignorou o tamanho %s da norma %s (%s); "
                            "refazendo no modo legado com as dimensões da biblioteca",
                            biblioteca["size"], standard, problema)
                _delete_feature(app, feature)
                feat = None
    if feat is None:
        feat = cria_legado()
        modo = "legacy"
    if feat is None:
        raise ComCallError("HoleWizard5", (hole_type, diameter_mm, depth_mm), None,
                           "furo não criado — o SolidWorks rejeitou a operação")

    feature = cast_to(feat, "IFeature")
    nome = com_get(feature, "Name")
    alvos = alvos_de(feature)
    nome_sketch = _move_hole_to(app, feature, alvos)
    problema = furo_confere()
    if problema is not None:
        _delete_feature(app, feature)
        raise ComCallError("hole_wizard", (size or diameter_mm, depth_mm), None,
                           f"o furo saiu diferente do pedido ({problema}) — nada foi deixado na peça")

    rosca = None
    if add_cosmetic_thread and hole_type in ("tap", "taper_tap") and biblioteca:
        centro = _hole_mouth_center(app, diameter_mm, (face_x_mm, face_y_mm, face_z_mm))
        if centro is not None:
            comprimento = thread_depth_mm or depth_mm
            rosca = cosmetic_thread(app, centro, diameter_mm,
                                    biblioteca["nominal_diameter_mm"] or diameter_mm,
                                    comprimento, biblioteca["size"], through_all)
    definicao = None
    if fully_define:
        from swmcp.com.wrappers import sketch_define
        definicao = sketch_define.fully_define_sketch(app, nome_sketch)
    log.info("furo %s criado: %s %d× Ø%.2f×%.2f (%s)", hole_type, nome, n_furos,
             diameter_mm, depth_mm, modo)
    return {"feature": nome, "position_sketch": nome_sketch,
            "position_mm": alvos[0], "positions_mm": alvos,
            "holes": n_furos, "drill_diameter_mm": round(diameter_mm, 4), "mode": modo,
            "library": biblioteca, "cosmetic_thread": rosca,
            "sketch_definition": definicao}


def _hole_mouth_center(app: Any, diameter_mm: float,
                       perto_de: tuple[float, float, float]) -> list[float] | None:
    """Centro da aresta circular do furo mais próxima do ponto onde ele foi feito."""
    melhor, menor = None, None
    for aresta in list_circular_edges(app, diameter_mm - 0.05, diameter_mm + 0.05):
        centro = aresta["center_mm"]
        dist = sum((centro[i] - perto_de[i]) ** 2 for i in range(3)) ** 0.5
        if menor is None or dist < menor:
            melhor, menor = centro, dist
    return melhor


def cosmetic_thread(app: Any, center_mm: list[float], edge_diameter_mm: float,
                    thread_diameter_mm: float, length_mm: float,
                    callout: str = "", through_all: bool = False) -> dict[str, Any]:
    """Representação de rosca a partir de uma aresta circular (mm).

    center_mm/edge_diameter_mm identificam a ARESTA onde a rosca começa (a boca
    do furo, ou o fim do chanfro numa ponta roscada); thread_diameter_mm é o
    diâmetro nominal da rosca e callout o texto da chamada (ex.: 'M20x2,5').
    """
    select_circular_edge(app, center_mm, edge_diameter_mm)
    model = _model(_active_doc(app))
    fm = cast_to(com_get(model, "FeatureManager"), "IFeatureManager")
    c = swconst()
    fim = c.swEndCondThroughAll if through_all else c.swEndCondBlind
    feat = com_call(fm, "InsertCosmeticThread3", 0, "", "",
                    units.from_mm(thread_diameter_mm), fim, units.from_mm(length_mm), callout)
    if feat is None:
        raise ComCallError("InsertCosmeticThread3", (center_mm, thread_diameter_mm), None,
                           "rosca não criada — confira se a aresta é circular e de uma face cilíndrica")
    return {"feature": com_get(cast_to(feat, "IFeature"), "Name"), "callout": callout}


# -------------------------------------------------------------- conferência

def measure_bodies(app: Any, density_kg_m3: float = 7850.0) -> list[dict[str, Any]]:
    """Volume, área, massa e caixa de cada corpo sólido (mm, mm², kg).

    Serve para conferir o modelo contra o cálculo feito à mão: como cada feature
    de corte tem volume previsível, comparar o volume medido com o esperado pega
    erro de cota que passa despercebido na tela (um snap que arredondou uma cota,
    um corte que pegou material demais).
    """
    saida: list[dict[str, Any]] = []
    for i, raw_body in enumerate(_bodies(app)):
        body = cast_to(raw_body, "IBody2")
        props = com_call(body, "GetMassProperties", density_kg_m3)
        # [cx, cy, cz, volume_m3, area_m2, massa_kg, ...]
        volume_m3 = props[3]
        box = com_call(body, "GetBodyBox")
        saida.append({
            "index": i,
            "name": com_get(body, "Name"),
            "volume_mm3": round(volume_m3 * 1e9, 3),
            "surface_area_mm2": round(props[4] * 1e6, 3),
            "mass_kg": round(volume_m3 * density_kg_m3, 4),
            "density_kg_m3": density_kg_m3,
            "face_count": com_call(body, "GetFaceCount"),
            "box_mm": [round(units.to_mm(v), 3) for v in box] if box else None,
        })
    return saida
