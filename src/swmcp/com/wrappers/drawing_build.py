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
