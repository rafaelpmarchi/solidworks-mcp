"""Novo documento, salvar e exportar (RF-08, escrita). Thread STA."""

from __future__ import annotations

import logging
import os
from typing import Any

from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.modeling import _active_doc, _model

log = logging.getLogger(__name__)

EXPORT_EXTENSIONS = {".pdf", ".dxf", ".dwg", ".step", ".stp", ".igs", ".iges",
                     ".stl", ".png", ".jpg", ".x_t", ".sat", ".3mf", ".edrw", ".eprt"}


def _default_template(app: Any, doc_kind: str) -> str:
    c = swconst()
    pref = {
        "part": c.swDefaultTemplatePart,
        "assembly": c.swDefaultTemplateAssembly,
        "drawing": c.swDefaultTemplateDrawing,
    }[doc_kind]
    template = com_call(app, "GetUserPreferenceStringValue", pref)
    if not template or not os.path.exists(template):
        raise ComCallError("GetUserPreferenceStringValue", (doc_kind,), None,
                           f"template padrão de {doc_kind} não configurado no SolidWorks")
    return template


def new_document(app: Any, doc_kind: str = "part", template: str | None = None) -> dict[str, Any]:
    """Cria documento novo (part/assembly/drawing) a partir do template."""
    template = template or _default_template(app, doc_kind)
    doc = com_call(app, "NewDocument", template, 0, 0.0, 0.0)
    if doc is None:
        raise ComCallError("NewDocument", (template,), None, "documento não criado")
    model = _model(doc)
    return {"title": com_call(model, "GetTitle"), "template": template, "kind": doc_kind}


def save_active(app: Any) -> dict[str, Any]:
    """Salva o documento ativo no caminho atual (precisa já ter sido salvo antes)."""
    model = _model(_active_doc(app))
    path = com_call(model, "GetPathName")
    if not path:
        raise ComCallError("Save3", (), None, "documento nunca foi salvo — use save_as com um caminho")
    c = swconst()
    ok, errors, warnings = com_call(model, "Save3", c.swSaveAsOptions_Silent, 0, 0)
    if not ok:
        raise ComCallError("Save3", (path,), None, f"falha ao salvar (errors={errors})")
    return {"saved": path, "warnings": warnings}


def save_as(app: Any, path: str, overwrite: bool = False) -> dict[str, Any]:
    """Salva/exporta o documento ativo para o caminho (a extensão define o formato).

    Formatos: .sldprt/.sldasm/.slddrw (nativo) ou exportação (.pdf, .step,
    .dxf, .dwg, .stl, .png, .igs...). Recusa sobrescrever sem overwrite=True.
    """
    path = os.path.abspath(path)
    if os.path.exists(path) and not overwrite:
        raise ComCallError("SaveAs", (path,), None, "arquivo já existe — passe overwrite=True para substituir")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    model = _model(_active_doc(app))
    ext = com_get(model, "Extension")
    c = swconst()
    ok, errors, warnings = com_call(
        ext, "SaveAs3", path, c.swSaveAsCurrentVersion, c.swSaveAsOptions_Silent,
        None, None, 0, 0,
    )
    if not ok or not os.path.exists(path):
        raise ComCallError("SaveAs3", (path,), None, f"falha ao salvar/exportar (errors={errors})")
    log.info("salvo/exportado: %s", path)
    return {"path": path, "warnings": warnings, "size_bytes": os.path.getsize(path)}


def screenshot(app: Any, path: str) -> dict[str, Any]:
    """Salva uma imagem PNG da vista atual do documento ativo (zoom to fit)."""
    if not path.lower().endswith(".png"):
        path += ".png"
    model = _model(_active_doc(app))
    com_call(model, "ViewZoomtofit2")
    return save_as(app, path, overwrite=True)


# swStandardViews_e: de que lado a câmera olha (normal PARA FORA da face → vista)
_VIEW_BY_NORMAL = {(0, 0, 1): 1, (0, 0, -1): 2, (-1, 0, 0): 3, (1, 0, 0): 4,
                   (0, 1, 0): 5, (0, -1, 0): 6}


def view_face(app: Any, normal: list[float], path: str, box_mm: list[float] | None = None,
              hide_planes: bool = True) -> dict[str, Any]:
    """Screenshot olhando de frente para a face de normal (para fora) dada.

    normal: eixo da peça, ex. [0,-1,0] = face -Y. box_mm [x1,y1,z1,x2,y2,z2]
    dá zoom na região (sem ela, zoom to fit). hide_planes esconde os planos
    de referência visíveis — que no iso poluem a imagem.
    """
    chave = tuple(int(round(c)) for c in normal)
    if chave not in _VIEW_BY_NORMAL or sum(abs(c) for c in chave) != 1:
        raise ComCallError("view_face", tuple(normal), None,
                           "normal precisa ser um eixo da peça: [±1,0,0], [0,±1,0] ou [0,0,±1]")
    model = _model(_active_doc(app))
    escondidos = []
    if hide_planes:
        raw = com_call(model, "FirstFeature")
        vistos = 0
        while raw is not None:
            feat = cast_to(raw, "IFeature")
            if com_call(feat, "GetTypeName2") == "RefPlane":
                vistos += 1
                if vistos > 3 and com_get(feat, "Visible") == 1:  # swVisibilityStateShown
                    com_call(model, "ClearSelection2", True)
                    com_call(feat, "Select2", False, 0)
                    com_call(model, "BlankRefGeom")
                    escondidos.append(com_call(feat, "Name"))
            raw = com_call(feat, "GetNextFeature")
        com_call(model, "ClearSelection2", True)
    com_call(model, "ShowNamedView2", "", _VIEW_BY_NORMAL[chave])
    if box_mm:
        b = [float(v) / 1000.0 for v in box_mm]
        com_call(model, "ViewZoomTo2", *b)
    else:
        com_call(model, "ViewZoomtofit2")
    if not path.lower().endswith(".png"):
        path += ".png"
    r = save_as(app, path, overwrite=True)
    r["hidden_planes"] = escondidos
    return r
