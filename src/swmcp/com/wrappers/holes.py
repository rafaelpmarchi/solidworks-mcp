"""Furos do assistente de furação, roscas cosméticas e seleção de arestas
circulares por geometria (escrita). Executa no thread STA.

O assistente de furação nesta instalação NÃO tem a base de tamanhos do Toolbox:
HoleWizard5 com norma real (ISO/DIN/ANSI Metric + "M20x2.5") nomeia a feature
certo e gera a geometria de um furo em polegada, sem erro nenhum, e nem
ModifyDefinition corrige — IWizardHoleFeatureData2 devolve 0 em todo diâmetro.
Por isso aqui se usa o modo LEGADO do próprio assistente, que ignora a base e
obedece aos parâmetros passados. A rosca entra como representação cosmética,
que é o usual em desenho de fabricação.
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.constants import ADV_WIZARD_HOLE_TYPES
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst

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
    """Sub-sketch de POSICIONAMENTO do furo (o que tem um único ponto)."""
    achado = None
    raw = com_get(feature, "GetFirstSubFeature")
    while raw:
        sub = cast_to(raw, "IFeature")
        if com_get(sub, "GetTypeName2") == "ProfileFeature":
            sketch = cast_to(com_call(sub, "GetSpecificFeature2"), "ISketch")
            if len(com_call(sketch, "GetSketchPoints2") or []) == 1:
                achado = sub
        raw = com_get(sub, "GetNextSubFeature")
    return achado


def hole_wizard(
    app: Any,
    face_x_mm: float,
    face_y_mm: float,
    face_z_mm: float,
    diameter_mm: float,
    depth_mm: float,
    hole_type: str = "simple",
    thread_depth_mm: float = 0.0,
    through_all: bool = False,
    position_mm: list[float] | None = None,
) -> dict[str, Any]:
    """Furo do assistente de furação na face apontada pelas coordenadas (mm).

    hole_type: simple, tap, counterbore, countersink, taper_tap.
    position_mm é o centro do furo NAS COORDENADAS DO SKETCH da face; o padrão
    [0, 0] é a origem do sketch (no eixo, para uma face de extremidade).
    Usa o modo legado do assistente: o tamanho vem de diameter_mm/depth_mm, não
    de uma norma — sem Toolbox instalado a base de tamanhos não responde.
    """
    tipo = ADV_WIZARD_HOLE_TYPES.get(hole_type)
    if tipo is None:
        raise ComCallError("hole_wizard", (hole_type,), None,
                           f"hole_type deve ser um de {sorted(ADV_WIZARD_HOLE_TYPES)}")
    model = _model(_active_doc(app))
    ext = com_get(model, "Extension")
    fm = cast_to(com_get(model, "FeatureManager"), "IFeatureManager")
    c = swconst()

    select_face_at(app, face_x_mm, face_y_mm, face_z_mm)

    fim = c.swEndCondThroughAll if through_all else c.swEndCondBlind
    feat = com_call(
        fm, "HoleWizard5",
        c.swWzdLegacy, getattr(c, tipo), 0, "", fim,
        units.from_mm(diameter_mm), units.from_mm(depth_mm), units.from_mm(thread_depth_mm),
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        "", False, True, True, False, False, False,
    )
    if feat is None:
        raise ComCallError("HoleWizard5", (hole_type, diameter_mm, depth_mm), None,
                           "furo não criado — o SolidWorks rejeitou a operação")
    feature = cast_to(feat, "IFeature")
    nome = com_get(feature, "Name")

    # O assistente põe o furo onde a face foi clicada; reposiciona pelo sketch.
    alvo = position_mm or [0.0, 0.0]
    sketch_pos = _position_sketch(feature)
    if sketch_pos is None:
        raise ComCallError("hole_wizard", (nome,), None,
                           "furo criado mas sem sketch de posicionamento para centralizar")
    nome_sketch = com_get(sketch_pos, "Name")
    skm = cast_to(com_get(model, "SketchManager"), "ISketchManager")
    com_call(model, "ClearSelection2", True)
    com_call(ext, "SelectByID2", nome_sketch, "SKETCH", 0.0, 0.0, 0.0, False, 0, None,
             c.swSelectOptionDefault)
    com_call(skm, "InsertSketch", True)
    sketch = cast_to(com_get(skm, "ActiveSketch"), "ISketch")
    ponto = cast_to(com_call(sketch, "GetSketchPoints2")[0], "ISketchPoint")
    com_call(ponto, "SetCoords", units.from_mm(alvo[0]), units.from_mm(alvo[1]), 0.0)
    com_call(skm, "InsertSketch", True)
    com_call(model, "ForceRebuild3", False)
    log.info("furo %s criado: %s Ø%.2f×%.2f", hole_type, nome, diameter_mm, depth_mm)
    return {"feature": nome, "position_sketch": nome_sketch, "position_mm": alvo}


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
