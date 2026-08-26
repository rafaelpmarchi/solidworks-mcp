"""Modelagem 3D: sketches e features (escrita). Executa no thread STA.

Convenções:
- Entradas em mm/graus; conversão aqui (RNF-03).
- Toda operação retorna o que criou (nome da feature/sketch) ou levanta
  ComCallError com contexto — nunca sucesso silencioso (RNF-01).
- Nada aqui salva arquivo: salvar é decisão explícita (RNF-05).
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst

log = logging.getLogger(__name__)


def _model(doc: Any) -> Any:
    return cast_to(doc, "IModelDoc2")


def _active_doc(app: Any) -> Any:
    doc = com_get(app, "ActiveDoc")
    if doc is None:
        raise ComCallError("ActiveDoc", (), None, "nenhum documento ativo no SolidWorks")
    return doc


# ------------------------------------------------------------------ seleção

def select_entity(
    app: Any,
    name: str,
    entity_type: str,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
    z_mm: float = 0.0,
    append: bool = False,
    mark: int = 0,
) -> bool:
    """SelectByID2. Para FACE/EDGE/VERTEX sem nome, use as coordenadas (mm).

    entity_type: PLANE, FACE, EDGE, VERTEX, SKETCH, BODYFEATURE, AXIS,
    SKETCHSEGMENT, COMPONENT, DATUMPLANE etc. (nomes da API).
    """
    model = _model(_active_doc(app))
    ext = com_get(model, "Extension")
    ok = com_call(
        ext, "SelectByID2",
        name, entity_type,
        units.from_mm(x_mm), units.from_mm(y_mm), units.from_mm(z_mm),
        append, mark, None, swconst().swSelectOptionDefault,
    )
    if not ok:
        raise ComCallError(
            "SelectByID2", (name, entity_type, x_mm, y_mm, z_mm), None,
            "nada selecionado — confira nome/tipo/coordenadas (coordenadas em mm)",
        )
    return True


def clear_selection(app: Any) -> None:
    com_call(_model(_active_doc(app)), "ClearSelection2", True)


# ------------------------------------------------------------------ sketch

def insert_sketch(app: Any, plane_name: str | None = None) -> str:
    """Abre um sketch no plano/face indicado (ou na seleção atual)."""
    model = _model(_active_doc(app))
    if plane_name:
        try:
            select_entity(app, plane_name, "PLANE")
        except ComCallError:
            select_entity(app, plane_name, "FACE")
    skm = com_get(model, "SketchManager")
    com_call(skm, "InsertSketch", True)
    if com_get(skm, "ActiveSketch") is None:
        raise ComCallError("InsertSketch", (plane_name,), None, "sketch não foi aberto")
    # nome via última feature da árvore (cast ISketch→IFeature resolve dispid errado)
    feat = cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature")
    return com_call(feat, "Name")


def exit_sketch(app: Any) -> None:
    """Fecha o sketch ativo (confirma)."""
    skm = com_get(_model(_active_doc(app)), "SketchManager")
    com_call(skm, "InsertSketch", True)


def _skm(app: Any) -> Any:
    model = _model(_active_doc(app))
    skm = com_get(model, "SketchManager")
    if com_get(skm, "ActiveSketch") is None:
        raise ComCallError("SketchManager", (), None, "não há sketch ativo — use create_sketch antes")
    return skm


def sketch_line(app: Any, x1: float, y1: float, x2: float, y2: float, centerline: bool = False) -> None:
    skm = _skm(app)
    method = "CreateCenterLine" if centerline else "CreateLine"
    seg = com_call(skm, method,
                   units.from_mm(x1), units.from_mm(y1), 0.0,
                   units.from_mm(x2), units.from_mm(y2), 0.0)
    if seg is None:
        raise ComCallError(method, (x1, y1, x2, y2), None, "segmento não criado")


def sketch_circle(app: Any, xc: float, yc: float, diameter: float) -> None:
    seg = com_call(_skm(app), "CreateCircleByRadius",
                   units.from_mm(xc), units.from_mm(yc), 0.0,
                   units.from_mm(diameter / 2.0))
    if seg is None:
        raise ComCallError("CreateCircleByRadius", (xc, yc, diameter), None, "círculo não criado")


def sketch_rectangle(app: Any, x1: float, y1: float, x2: float, y2: float, center: bool = False) -> None:
    skm = _skm(app)
    if center:
        segs = com_call(skm, "CreateCenterRectangle",
                        units.from_mm(x1), units.from_mm(y1), 0.0,
                        units.from_mm(x2), units.from_mm(y2), 0.0)
    else:
        segs = com_call(skm, "CreateCornerRectangle",
                        units.from_mm(x1), units.from_mm(y1), 0.0,
                        units.from_mm(x2), units.from_mm(y2), 0.0)
    if not segs:
        raise ComCallError("CreateRectangle", (x1, y1, x2, y2), None, "retângulo não criado")


def sketch_arc_center(app: Any, xc: float, yc: float, x1: float, y1: float, x2: float, y2: float,
                      direction: int = 1) -> None:
    """Arco por centro + início + fim. direction: 1 anti-horário, -1 horário."""
    seg = com_call(_skm(app), "CreateArc",
                   units.from_mm(xc), units.from_mm(yc), 0.0,
                   units.from_mm(x1), units.from_mm(y1), 0.0,
                   units.from_mm(x2), units.from_mm(y2), 0.0, direction)
    if seg is None:
        raise ComCallError("CreateArc", (xc, yc), None, "arco não criado")


def sketch_polygon(app: Any, xc: float, yc: float, sides: int, diameter: float, inscribed: bool = True) -> None:
    segs = com_call(_skm(app), "CreatePolygon",
                    units.from_mm(xc), units.from_mm(yc), 0.0,
                    units.from_mm(xc + diameter / 2.0), units.from_mm(yc), 0.0,
                    sides, inscribed)
    if not segs:
        raise ComCallError("CreatePolygon", (xc, yc, sides), None, "polígono não criado")


# ------------------------------------------------------------------ features

def _feature_name(feat: Any, op: str) -> str:
    if feat is None:
        raise ComCallError(op, (), None, "feature não criada — o SolidWorks rejeitou a operação "
                                         "(sketch aberto/perfil inválido/seleção faltando?)")
    return com_call(cast_to(feat, "IFeature"), "Name")


def extrude(app: Any, depth_mm: float, cut: bool = False, flip: bool = False,
            through_all: bool = False, both_directions: bool = False) -> str:
    """Extrusão (boss ou corte) do sketch ativo/selecionado."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    c = swconst()
    end = c.swEndCondThroughAll if through_all else c.swEndCondBlind
    d = units.from_mm(abs(depth_mm))
    if cut:
        feat = com_call(
            fm, "FeatureCut4",
            True, flip, False, end, end, d, d, False, False, False, False,
            0.0, 0.0, False, False, False, False, False, True, True,
            True, True, False, c.swStartSketchPlane, 0.0, False, False,
        )
    else:
        feat = com_call(
            fm, "FeatureExtrusion3",
            True, flip, False, end, end, d, d, False, False, False, False,
            0.0, 0.0, False, False, False, False, True, True, True,
            c.swStartSketchPlane, 0.0, False,
        )
    name = _feature_name(feat, "FeatureCut4" if cut else "FeatureExtrusion3")
    log.info("extrusão %s criada: %s (%.2fmm)", "corte" if cut else "boss", name, depth_mm)
    return name


def revolve(app: Any, angle_deg: float = 360.0, cut: bool = False) -> str:
    """Revolução do sketch ativo (precisa de linha de centro no sketch)."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    ang = units.from_deg(angle_deg)
    feat = com_call(
        fm, "FeatureRevolve2",
        True, True, False, cut, False, False, 0, 0, ang, 0.0,
        False, False, 0.0, 0.0, 0, 0.0, 0.0, True, True, True,
    )
    return _feature_name(feat, "FeatureRevolve2")


def fillet(app: Any, radius_mm: float) -> str:
    """Filete de raio constante nas arestas SELECIONADAS (select_entity EDGE)."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    # assinatura: (Options, R1, R2, Rho, Ftyp, OverflowType, ConicRhoType, + 7 arrays)
    # 195 = flags padrão dos exemplos oficiais; Ftyp 0 = raio constante
    feat = com_call(
        fm, "FeatureFillet3",
        195, units.from_mm(radius_mm), 0.0, 0.0, 0, 0, 0,
        None, None, None, None, None, None, None,
    )
    return _feature_name(feat, "FeatureFillet3")


def chamfer(app: Any, distance_mm: float, angle_deg: float = 45.0) -> str:
    """Chanfro distância-ângulo nas arestas SELECIONADAS."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    feat = com_call(
        fm, "InsertFeatureChamfer",
        4, 1, units.from_mm(distance_mm), units.from_deg(angle_deg), 0.0, 0.0, 0.0, 0.0,
    )
    return _feature_name(feat, "InsertFeatureChamfer")


def shell(app: Any, thickness_mm: float) -> str:
    """Casca com as faces SELECIONADAS removidas."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    feat = com_call(fm, "InsertFeatureShell", units.from_mm(thickness_mm), False)
    return _feature_name(feat, "InsertFeatureShell")


def reference_plane_offset(app: Any, base_plane: str, offset_mm: float, flip: bool = False) -> str:
    """Plano de referência paralelo a um plano/face com offset."""
    model = _model(_active_doc(app))
    select_entity(app, base_plane, "PLANE")
    fm = com_get(model, "FeatureManager")
    c = swconst()
    flag = c.swRefPlaneReferenceConstraint_Distance
    if flip:
        flag |= c.swRefPlaneReferenceConstraint_OptionFlip
    feat = com_call(fm, "InsertRefPlane", flag, units.from_mm(offset_mm), 0, 0.0, 0, 0.0)
    return _feature_name(feat, "InsertRefPlane")


def rebuild(app: Any) -> bool:
    """Reconstrói o documento ativo (EditRebuild3)."""
    return bool(com_call(_model(_active_doc(app)), "EditRebuild3"))


def zoom_to_fit(app: Any) -> None:
    com_call(_model(_active_doc(app)), "ViewZoomtofit2")


def list_planes(app: Any) -> list[str]:
    """Nomes dos planos de referência do documento ativo (na língua da UI)."""
    model = _model(_active_doc(app))
    planes = []
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        if com_call(feat, "GetTypeName2") == "RefPlane":
            planes.append(com_call(feat, "Name"))
        raw = com_call(feat, "GetNextFeature")
    return planes
