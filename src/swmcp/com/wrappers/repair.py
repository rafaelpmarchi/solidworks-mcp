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


# ------------------------------------------------------- pastas por face

FOLDER_CONTAINING = 2   # swFeatureTreeFolder_Containing
MOVE_AFTER = 3          # swMoveLocation_e: depois da feature de referência


def _tree_order(model: Any) -> list[str]:
    nomes = []
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        nomes.append(com_call(feat, "Name"))
        raw = com_call(feat, "GetNextFeature")
    return nomes


def organize_tree(app: Any, groups: list[dict[str, Any]], renames: dict[str, str] | None = None,
                  after: str = "") -> dict[str, Any]:
    """Renomeia, reordena e agrupa em pastas: [{name, features:[...]}, ...].

    As features vão para a sequência dos grupos a partir de 'after' (padrão:
    logo antes da primeira feature dos grupos na árvore atual) e cada grupo
    vira uma pasta. ReorderFeature devolve False mesmo movendo, por isso a
    ordem é conferida lendo a árvore; se não bater, nenhuma pasta é criada e o
    retorno diz onde divergiu. Pasta só junta feature contígua — é por isso
    que a reordenação vem antes.
    """
    from swmcp.domain.tree import desired_sequence, order_mismatches

    model = _model(_active_doc(app))
    renomeadas = rename_features(app, renames)["renamed"] if renames else []
    ordem = _tree_order(model)
    pedidas = {f for g in groups for f in g["features"]}
    # port_hole/angled_channel criam "Plano <feature>" logo antes da feature: o
    # plano vai junto para a pasta, senão ela deixa de ser contígua
    grupos = [(g["name"], [x for f in g["features"]
                           for x in ([f"Plano {f}"] if f"Plano {f}" in ordem
                                     and f"Plano {f}" not in pedidas else []) + [f]])
              for g in groups]
    sequencia = desired_sequence(grupos)
    faltando = [f for f in sequencia if f not in ordem]
    if faltando:
        raise ComCallError("organize_tree", tuple(faltando[:5]), None,
                           f"features não existem na árvore: {faltando[:10]}")
    anterior = after
    if not anterior:
        primeira = min(ordem.index(f) for f in sequencia)
        anterior = ordem[primeira - 1] if primeira > 0 else ""
    ext = com_get(model, "Extension")
    for nome in sequencia:
        if anterior:
            com_call(ext, "ReorderFeature", nome, anterior, MOVE_AFTER)
        anterior = nome
    com_call(model, "ForceRebuild3", False)
    divergencias = order_mismatches(_tree_order(model), sequencia)
    if divergencias:
        return {"renamed": renomeadas, "folders": [], "ok": False,
                "mismatches": divergencias[:10],
                "note": "a reordenação não ficou como pedido (dependência entre features?) — "
                        "nenhuma pasta foi criada"}
    fm = com_get(model, "FeatureManager")
    pastas = []
    for nome_grupo, features in grupos:
        com_call(model, "ClearSelection2", True)
        for i, f in enumerate(features):
            com_call(_feature_by_name(model, f), "Select2", i > 0, 0)
        pasta = com_call(fm, "InsertFeatureTreeFolder2", FOLDER_CONTAINING)
        if pasta is None:
            pastas.append({"name": nome_grupo, "ok": False})
            continue
        cast_to(pasta, "IFeature").Name = nome_grupo
        pastas.append({"name": nome_grupo, "ok": True, "features": len(features)})
    com_call(model, "ClearSelection2", True)
    return {"renamed": renomeadas, "folders": pastas, "ok": all(p["ok"] for p in pastas),
            "mismatches": []}
