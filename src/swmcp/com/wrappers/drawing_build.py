"""Criação de desenho 2D a partir do modelo (RF-06, Fase 3). Thread STA."""

from __future__ import annotations

import logging
import os
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.com.wrappers.output import _default_template

log = logging.getLogger(__name__)

# candidatos por vista — instalação pode estar em inglês ou português
STANDARD_VIEWS = {
    "front": ["*Front", "*Frontal"],
    "back": ["*Back", "*Traseira"],
    "left": ["*Left", "*Esquerda"],
    "right": ["*Right", "*Direita"],
    "top": ["*Top", "*Superior"],
    "bottom": ["*Bottom", "*Inferior"],
    "iso": ["*Isometric", "*Isométrica"],
}


def create_drawing_from_model(
    app: Any,
    model_path: str,
    views: list[str] | None = None,
    template: str | None = None,
    import_annotations: bool = True,
) -> dict[str, Any]:
    """Cria um desenho novo com vistas padrão do modelo indicado.

    views: nomes em inglês: front, top, right, iso... (default: front+top+iso).
    Cotas marcadas para desenho são importadas do modelo se import_annotations.
    O desenho fica aberto e NÃO salvo — revisão humana antes de salvar.
    """
    model_path = os.path.abspath(model_path)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"modelo não existe: {model_path}")
    views = views or ["front", "top", "iso"]
    invalid = [v for v in views if v not in STANDARD_VIEWS]
    if invalid:
        raise ValueError(f"vistas inválidas {invalid}; use {sorted(STANDARD_VIEWS)}")

    template = template or _default_template(app, "drawing")
    doc = com_call(app, "NewDocument", template, 0, 0.0, 0.0)
    if doc is None:
        raise ComCallError("NewDocument", (template,), None, "desenho não criado")
    dwg = cast_to(doc, "IDrawingDoc")

    created = []
    positions = [(0.09, 0.20), (0.09, 0.08), (0.22, 0.20), (0.22, 0.08)]
    for view_name, (x, y) in zip(views, positions):
        view = None
        for candidate in STANDARD_VIEWS[view_name]:
            view = com_call(dwg, "CreateDrawViewFromModelView3",
                            model_path, candidate, x, y, 0.0)
            if view is not None:
                break
        if view is None:
            raise ComCallError("CreateDrawViewFromModelView3", (view_name,), None,
                               f"vista {view_name!r} não criada (tentado {STANDARD_VIEWS[view_name]})")
        created.append({"view": view_name, "name": com_call(cast_to(view, "IView"), "GetName2")})

    imported = 0
    if import_annotations:
        c = swconst()
        anns = com_call(dwg, "InsertModelAnnotations3",
                        c.swImportModelItemsFromEntireModel,
                        c.swInsertDimensionsMarkedForDrawing, True, True, False, False)
        imported = len(anns) if anns else 0

    model = _model(doc)
    return {
        "title": com_call(model, "GetTitle"),
        "model": model_path,
        "views": created,
        "annotations_imported": imported,
        "saved": False,
    }


def _active_drawing(app: Any) -> Any:
    doc = _active_doc(app)
    if com_call(_model(doc), "GetType") != swconst().swDocDRAWING:
        raise ComCallError("DrawingDoc", (), None, "documento ativo não é desenho")
    return cast_to(doc, "IDrawingDoc")


def add_projected_view(app: Any, source_view: str, x_mm: float, y_mm: float) -> str:
    """Vista projetada a partir de uma vista existente, posicionada em (x,y) mm
    da folha — a direção da projeção segue a posição relativa à vista base."""
    dwg = _active_drawing(app)
    model = _model(_active_doc(app))
    com_call(model, "ClearSelection2", True)
    ext = com_get(model, "Extension")
    if not com_call(ext, "SelectByID2", source_view, "DRAWINGVIEW", 0.0, 0.0, 0.0,
                    False, 0, None, swconst().swSelectOptionDefault):
        raise ComCallError("SelectByID2", (source_view,), None, "vista base não encontrada")
    view = com_call(dwg, "CreateUnfoldedViewAt3",
                    units.from_mm(x_mm), units.from_mm(y_mm), 0.0, False)
    if view is None:
        raise ComCallError("CreateUnfoldedViewAt3", (source_view,), None, "projeção não criada")
    return com_call(cast_to(view, "IView"), "GetName2")


def insert_drawing_note(app: Any, text: str, x_mm: float, y_mm: float) -> str:
    """Nota de texto solta na folha ativa do desenho, em (x,y) mm."""
    dwg = _active_drawing(app)
    raw = com_call(dwg, "CreateText2", text,
                   units.from_mm(x_mm), units.from_mm(y_mm), 0.0, 0.005, 0.0)
    if raw is None:
        raise ComCallError("CreateText2", (text,), None, "nota não criada")
    note = cast_to(raw, "INote")
    return com_call(note, "GetName")


def set_sheet_scale(app: Any, numerator: float, denominator: float) -> dict[str, Any]:
    """Muda a escala da folha ativa (ex.: 1:2 → numerator=1, denominator=2)."""
    dwg = _active_drawing(app)
    sheet = cast_to(com_call(dwg, "GetCurrentSheet"), "ISheet")
    ok = com_call(sheet, "SetScale", float(numerator), float(denominator), True, True)
    if not ok:
        raise ComCallError("SetScale", (numerator, denominator), None, "escala recusada")
    com_call(_model(_active_doc(app)), "EditRebuild3")
    return {"scale": f"{numerator:g}:{denominator:g}"}
