"""Reparos de referência perdida e arrumação da árvore.

Editar o perfil de uma revolução (dividir/recriar uma linha) troca a
identidade das faces que aquela linha gerava; o que apontava para essas
faces — eixo de padrão circular, plano do esboço de posição de um furo —
fica "dangling" e o SolidWorks avisa em "O que está errado?". A API deixa
religar o eixo do padrão (ICircularPatternFeatureData.Axis); o plano de um
esboço existente não tem chamada pública — nesse caso o furo se refaz com
hole_wizard na face certa.
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to
from swmcp.com.wrappers import holes
from swmcp.com.wrappers.modeling import _active_doc, _feature_by_name, _model, rename_feature

log = logging.getLogger(__name__)


def set_circular_pattern_axis(app: Any, feature_name: str, face_at_mm: list[float]) -> dict[str, Any]:
    """Religa o eixo de um padrão circular à face (cilíndrica/cônica) que passa
    pelo ponto face_at_mm — a face do furo principal, por exemplo. Reconstrói
    e confere que a feature ficou sem erro."""
    model = _model(_active_doc(app))
    feat = _feature_by_name(model, feature_name)
    if com_call(feat, "GetTypeName2") != "CirPattern":
        raise ComCallError("set_circular_pattern_axis", (feature_name,), None,
                           "a feature não é um padrão circular")
    holes.select_face_at(app, face_at_mm[0], face_at_mm[1], face_at_mm[2])
    selmgr = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    face = com_call(selmgr, "GetSelectedObject6", 1, -1)
    if face is None:
        raise ComCallError("set_circular_pattern_axis", tuple(face_at_mm), None, "face não selecionada")
    data = cast_to(com_call(feat, "GetDefinition"), "ICircularPatternFeatureData")
    if not com_call(data, "AccessSelections", model, None):
        raise ComCallError("AccessSelections", (feature_name,), None, "não abriu a definição do padrão")
    try:
        data.Axis = face
        if not com_call(feat, "ModifyDefinition", data, model, None):
            raise ComCallError("ModifyDefinition", (feature_name,), None,
                               "o SolidWorks recusou a nova definição do padrão")
    except ComCallError:
        com_call(data, "ReleaseSelectionAccess")
        raise
    com_call(model, "EditRebuild3")
    codigo = com_call(feat, "GetErrorCode2", True)
    codigo = codigo[0] if isinstance(codigo, tuple) else codigo
    return {"feature": feature_name, "axis_face_at_mm": list(face_at_mm),
            "error_code": int(codigo), "ok": int(codigo) == 0}


def rename_features(app: Any, names: dict[str, str]) -> dict[str, Any]:
    """Renomeia várias features de uma vez: {nome atual: nome novo}. Para na
    primeira que não existir, sem desfazer as anteriores — o retorno diz
    quais já foram."""
    feitas: list[list[str]] = []
    for antigo, novo in names.items():
        try:
            rename_feature(app, antigo, novo)
        except ComCallError as exc:
            raise ComCallError("rename_features", (antigo, novo), exc.hresult,
                               f"{exc.detail}; já renomeadas: {feitas}") from exc
        feitas.append([antigo, novo])
    return {"renamed": feitas, "count": len(feitas)}
