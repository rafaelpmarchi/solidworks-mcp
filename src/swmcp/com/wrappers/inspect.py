"""Inspeção do modelo: erros de reconstrução, faces do corpo e estado do esboço.

O painel "O que está errado?" do SolidWorks só existe na tela; por API o que
há é IFeature::GetErrorCode2 em cada feature (e sub-feature — o esboço de
posição de um furo que perdeu a face avisa na sub-feature, não no furo).
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.modeling import _active_doc, _model

log = logging.getLogger(__name__)

# swConstrainedStatus_e (ISketch::GetConstrainedStatus)
SKETCH_STATUS = {0: "unknown", 1: "no_solution", 2: "under_defined",
                 3: "fully_defined", 4: "over_defined", 5: "invalid"}
# swSketchSegments_e (ISketchSegment::GetType)
SEGMENT_TYPES = {0: "line", 1: "arc", 2: "ellipse", 3: "spline", 4: "text", 5: "parabola"}
# ISketchSegment::Status (mesmo enum por entidade): 1 = sub-definida
_UNDER_DEFINED_ENTITY = 1


def _feature_error(feat: Any) -> tuple[int, bool]:
    raw = com_call(feat, "GetErrorCode2", True)
    if isinstance(raw, tuple):
        return int(raw[0]), bool(raw[1])
    return int(raw), False


def check_rebuild_errors(app: Any, rebuild: bool = True) -> dict[str, Any]:
    """Reconstrói e lista só o que ficou com erro ou aviso, com sub-features.

    O texto do erro é o mesmo do painel "O que está errado?" (IFeature::
    GetErrorCode2 → swFeatureError_e → GetErrorText). Lista vazia = árvore
    limpa. rebuild=False só lê o estado atual.
    """
    model = _model(_active_doc(app))
    rebuilt = None
    if rebuild:
        rebuilt = bool(com_call(model, "EditRebuild3"))
    problemas: list[dict[str, Any]] = []
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        pai = com_get(feat, "Name")
        for f, sub in ((feat, None),) + tuple((cast_to(s, "IFeature"), True) for s in _subfeatures(feat)):
            codigo, aviso = _feature_error(f)
            if codigo != 0:
                problemas.append({
                    "feature": pai if sub is None else f"{pai} / {com_get(f, 'Name')}",
                    "type": com_call(f, "GetTypeName2"),
                    "level": "warning" if aviso else "error",
                    "code": codigo,
                    "text": _error_text(codigo),
                })
        raw = com_call(feat, "GetNextFeature")
    return {"rebuilt": rebuilt, "problems": problemas, "clean": not problemas}


def _subfeatures(feat: Any) -> list[Any]:
    saida = []
    raw = com_call(feat, "GetFirstSubFeature")
    while raw is not None:
        saida.append(raw)
        raw = com_call(cast_to(raw, "IFeature"), "GetNextSubFeature")
    return saida


_ERROR_TEXTS: dict[int, str] = {}


def _error_text(codigo: int) -> str:
    """Texto do swFeatureError_e, pela própria API quando ela dá."""
    if codigo in _ERROR_TEXTS:
        return _ERROR_TEXTS[codigo]
    # A API não expõe o texto do painel; o nome do enum já localiza o problema.
    c = swconst()
    texto = next((nome for nome in dir(c)
                  if nome.startswith("swFeatureError") and getattr(c, nome) == codigo), "")
    _ERROR_TEXTS[codigo] = texto or f"swFeatureError_e {codigo}"
    return _ERROR_TEXTS[codigo]


# ------------------------------------------------------------------- faces

def _surface_info(surf: Any) -> dict[str, Any]:
    if com_call(surf, "IsPlane"):
        p = com_call(surf, "PlaneParams")
        return {"kind": "plane", "normal": [round(v, 6) for v in p[0:3]],
                "point_mm": [round(units.to_mm(v), 4) for v in p[3:6]]}
    if com_call(surf, "IsCylinder"):
        p = com_call(surf, "CylinderParams")
        return {"kind": "cylinder", "point_mm": [round(units.to_mm(v), 4) for v in p[0:3]],
                "axis": [round(v, 6) for v in p[3:6]],
                "diameter_mm": round(units.to_mm(p[6]) * 2.0, 4)}
    if com_call(surf, "IsCone"):
        p = com_call(surf, "ConeParams")
        return {"kind": "cone", "point_mm": [round(units.to_mm(v), 4) for v in p[0:3]],
                "axis": [round(v, 6) for v in p[3:6]],
                "base_diameter_mm": round(units.to_mm(p[6]) * 2.0, 4),
                "half_angle_deg": round(units.to_deg(p[7]), 4)}
    if com_call(surf, "IsTorus"):
        p = com_call(surf, "TorusParams")
        return {"kind": "torus", "center_mm": [round(units.to_mm(v), 4) for v in p[0:3]],
                "axis": [round(v, 6) for v in p[3:6]],
                "major_radius_mm": round(units.to_mm(p[6]), 4),
                "minor_radius_mm": round(units.to_mm(p[7]), 4)}
    if com_call(surf, "IsSphere"):
        p = com_call(surf, "SphereParams")
        return {"kind": "sphere", "center_mm": [round(units.to_mm(v), 4) for v in p[0:3]],
                "radius_mm": round(units.to_mm(p[3]), 4)}
    return {"kind": "other"}


def list_faces(app: Any, kind: str = "", diameter_mm: float | None = None,
               tolerance_mm: float = 0.05, limit: int = 300) -> list[dict[str, Any]]:
    """Faces dos corpos da peça: tipo (plane/cylinder/cone/torus/sphere),
    parâmetros da superfície, caixa e área. Filtros: kind e, para cilindro/
    cone, diameter_mm. Serve para achar a face certa por geometria — a que
    vira eixo de um padrão circular ou plano de um furo — sem clicar."""
    doc = _active_doc(app)
    model = _model(doc)
    if com_call(model, "GetType") != swconst().swDocPART:
        raise ComCallError("list_faces", (), None, "documento ativo não é peça")
    part = cast_to(doc, "IPartDoc")
    saida: list[dict[str, Any]] = []
    for ib, raw_body in enumerate(com_call(part, "GetBodies2", 0, True) or []):
        body = cast_to(raw_body, "IBody2")
        for raw_face in com_call(body, "GetFaces") or []:
            face = cast_to(raw_face, "IFace2")
            info = _surface_info(cast_to(com_call(face, "GetSurface"), "ISurface"))
            if kind and info["kind"] != kind:
                continue
            if diameter_mm is not None:
                d = info.get("diameter_mm", info.get("base_diameter_mm"))
                if d is None or abs(d - diameter_mm) > tolerance_mm:
                    continue
            box = com_call(face, "GetBox")
            info.update({
                "body": ib,
                "box_mm": [round(units.to_mm(v), 3) for v in box],
                "area_mm2": round(com_call(face, "GetArea") * 1e6, 3),
            })
            saida.append(info)
            if len(saida) >= limit:
                return saida
    return saida


# ------------------------------------------------------------------ esboço

def _sketch_by_name(model: Any, name: str) -> Any:
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        candidatos = [feat] + [cast_to(s, "IFeature") for s in _subfeatures(feat)]
        for f in candidatos:
            if com_get(f, "Name") == name and com_call(f, "GetTypeName2") == "ProfileFeature":
                return cast_to(com_call(f, "GetSpecificFeature2"), "ISketch")
        raw = com_call(feat, "GetNextFeature")
    raise ComCallError("sketch_status", (name,), None, "esboço não encontrado na árvore")


def _segment_summary(seg: Any) -> dict[str, Any]:
    tipo = SEGMENT_TYPES.get(com_call(seg, "GetType"), "other")
    item: dict[str, Any] = {"type": tipo, "construction": bool(com_get(seg, "ConstructionGeometry")),
                            "relations": com_call(seg, "GetRelationsCount")}
    if tipo in ("line", "arc"):
        obj = cast_to(seg, "ISketchLine" if tipo == "line" else "ISketchArc")
        for chave, prop in (("start_mm", "GetStartPoint2"), ("end_mm", "GetEndPoint2")):
            p = cast_to(com_call(obj, prop), "ISketchPoint")
            item[chave] = [round(units.to_mm(com_get(p, "X")), 4), round(units.to_mm(com_get(p, "Y")), 4)]
        if tipo == "arc":
            c = cast_to(com_call(obj, "GetCenterPoint2"), "ISketchPoint")
            item["center_mm"] = [round(units.to_mm(com_get(c, "X")), 4), round(units.to_mm(com_get(c, "Y")), 4)]
            item["radius_mm"] = round(units.to_mm(com_call(obj, "GetRadius")), 4)
    return item


def sketch_status(app: Any, sketch_name: str = "") -> dict[str, Any]:
    """Estado do esboço (totalmente/sub/sobre-definido) e QUAIS entidades
    estão soltas, com coordenadas — é o que falta para saber o que amarrar.
    Sem sketch_name usa o esboço aberto."""
    model = _model(_active_doc(app))
    skm = com_get(model, "SketchManager")
    if sketch_name:
        sketch = _sketch_by_name(model, sketch_name)
    else:
        ativo = com_get(skm, "ActiveSketch")
        if ativo is None:
            raise ComCallError("sketch_status", (), None, "não há esboço aberto — informe sketch_name")
        sketch = cast_to(ativo, "ISketch")
    estado = com_call(sketch, "GetConstrainedStatus")
    soltos = []
    total = 0
    for raw in com_call(sketch, "GetSketchSegments") or []:
        seg = cast_to(raw, "ISketchSegment")
        total += 1
        if com_get(seg, "Status") == _UNDER_DEFINED_ENTITY:
            soltos.append(_segment_summary(seg))
    pontos_soltos = []
    for raw in com_call(sketch, "GetSketchPoints2") or []:
        p = cast_to(raw, "ISketchPoint")
        if com_get(p, "Status") == _UNDER_DEFINED_ENTITY and com_get(p, "Type") == 0:
            pontos_soltos.append([round(units.to_mm(com_get(p, "X")), 4), round(units.to_mm(com_get(p, "Y")), 4)])
    return {"sketch": sketch_name or "(ativo)", "status": SKETCH_STATUS.get(estado, str(estado)),
            "fully_defined": estado == 3, "segments": total,
            "under_defined_segments": soltos, "under_defined_points": pontos_soltos}
