"""Edição pontual do documento ativo (RF-07, escrita). Thread STA.

Nada aqui salva o arquivo — a mudança fica pendente até save explícito.
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.modeling import _active_doc, _model

log = logging.getLogger(__name__)

MATERIAL_DB = "SOLIDWORKS Materials"


def set_custom_property(app: Any, name: str, value: str, configuration: str = "") -> dict[str, Any]:
    """Cria/atualiza propriedade customizada (doc ou configuração)."""
    model = _model(_active_doc(app))
    ext = com_get(model, "Extension")
    cpm = com_call(ext, "CustomPropertyManager", configuration)
    c = swconst()
    result = com_call(
        cpm, "Add3", name, c.swCustomInfoText, value,
        c.swCustomPropertyReplaceValue,
    )
    if result not in (0, 1):  # swCustomInfoAddResult: 0=ok, 1=substituída
        raise ComCallError("Add3", (name, value), None, f"propriedade não gravada (código {result})")
    return {"name": name, "value": value, "configuration": configuration or "(documento)"}


def delete_custom_property(app: Any, name: str, configuration: str = "") -> None:
    model = _model(_active_doc(app))
    cpm = com_call(com_get(model, "Extension"), "CustomPropertyManager", configuration)
    result = com_call(cpm, "Delete2", name)
    if result != 0:
        raise ComCallError("Delete2", (name,), None, f"propriedade não removida (código {result})")


def set_material(app: Any, material_name: str, configuration: str = "") -> dict[str, str]:
    """Aplica material do banco padrão do SolidWorks à peça ativa."""
    doc = _active_doc(app)
    model = _model(doc)
    if com_call(model, "GetType") != swconst().swDocPART:
        raise ComCallError("SetMaterial", (material_name,), None, "documento ativo não é peça")
    part = cast_to(doc, "IPartDoc")
    com_call(part, "SetMaterialPropertyName2", configuration, MATERIAL_DB, material_name)
    raw = com_call(part, "GetMaterialPropertyName2", configuration, "")
    applied = raw[0] if isinstance(raw, tuple) else raw
    if not applied:
        raise ComCallError("SetMaterialPropertyName2", (material_name,), None,
                           "material não aplicado — nome existe no banco 'SOLIDWORKS Materials'?")
    return {"material": applied, "database": MATERIAL_DB}


def set_dimension(app: Any, full_name: str, value: float, unit: str = "mm") -> dict[str, Any]:
    """Altera uma cota do modelo (ex.: 'D1@Esboço1') e reconstrói.

    unit: "mm" ou "deg".
    """
    model = _model(_active_doc(app))
    raw = com_call(model, "Parameter", full_name)
    if raw is None:
        raise ComCallError("Parameter", (full_name,), None, "cota não encontrada — use o nome completo D1@Feature")
    dim = cast_to(raw, "IDimension")
    system_value = units.from_deg(value) if unit == "deg" else units.from_mm(value)
    errcode = com_call(dim, "SetSystemValue3", system_value,
                       swconst().swSetValue_InThisConfiguration, None)
    if errcode != 0:
        raise ComCallError("SetSystemValue3", (full_name, value), None,
                           f"cota não alterada (swSetValueReturnStatus={errcode})")
    rebuilt = bool(com_call(model, "EditRebuild3"))
    return {"dimension": full_name, "value": value, "unit": unit, "rebuilt": rebuilt}


def suppress_feature(app: Any, feature_name: str, suppress: bool = True) -> None:
    select_feature(app, feature_name)
    model = _model(_active_doc(app))
    method = "EditSuppress2" if suppress else "EditUnsuppress2"
    if not com_call(model, method):
        raise ComCallError(method, (feature_name,), None, "operação recusada pelo SolidWorks")


def delete_feature(app: Any, feature_name: str) -> None:
    """Apaga uma feature (com filhos). Irreversível na sessão — confirmar antes."""
    select_feature(app, feature_name)
    model = _model(_active_doc(app))
    ext = com_get(model, "Extension")
    ok = com_call(ext, "DeleteSelection2", swconst().swDelete_Children)
    if not ok:
        raise ComCallError("DeleteSelection2", (feature_name,), None, "feature não apagada")


def select_feature(app: Any, feature_name: str) -> None:
    model = _model(_active_doc(app))
    com_call(model, "ClearSelection2", True)
    ext = com_get(model, "Extension")
    ok = com_call(ext, "SelectByID2", feature_name, "BODYFEATURE", 0.0, 0.0, 0.0,
                  False, 0, None, swconst().swSelectOptionDefault)
    if not ok:
        # sketches e planos têm tipos próprios
        for etype in ("SKETCH", "PLANE", "REFERENCECURVES", "COMPONENT"):
            if com_call(ext, "SelectByID2", feature_name, etype, 0.0, 0.0, 0.0,
                        False, 0, None, swconst().swSelectOptionDefault):
                return
        raise ComCallError("SelectByID2", (feature_name,), None, "feature não encontrada pelo nome")


def activate_configuration(app: Any, name: str) -> None:
    model = _model(_active_doc(app))
    if not com_call(model, "ShowConfiguration2", name):
        raise ComCallError("ShowConfiguration2", (name,), None, "configuração não encontrada")


def list_equations(app: Any) -> list[dict[str, Any]]:
    """Equações do documento ativo (índice, expressão, valor)."""
    model = _model(_active_doc(app))
    eqmgr = com_get(model, "GetEquationMgr")
    if eqmgr is None:
        return []
    eqmgr = cast_to(eqmgr, "IEquationMgr")
    count = com_get(eqmgr, "GetCount")
    out = []
    for i in range(count):
        out.append({
            "index": i,
            "equation": com_call(eqmgr, "Equation", i),
            "value": com_call(eqmgr, "Value", i),
            "global_variable": bool(com_call(eqmgr, "GlobalVariable", i)),
        })
    return out


def set_equation(app: Any, index: int, equation: str) -> dict[str, Any]:
    """Substitui a equação no índice dado (formato: '\"D1@Esboço1\" = 25mm')."""
    model = _model(_active_doc(app))
    eqmgr = cast_to(com_get(model, "GetEquationMgr"), "IEquationMgr")
    com_call(eqmgr, "SetEquation", index, equation)
    com_call(model, "EditRebuild3")
    return {"index": index, "equation": equation}


def add_equation(app: Any, equation: str) -> dict[str, Any]:
    """Adiciona equação/variável global (ex.: '\"espessura\" = 5mm')."""
    model = _model(_active_doc(app))
    eqmgr = cast_to(com_get(model, "GetEquationMgr"), "IEquationMgr")
    idx = com_call(eqmgr, "Add2", -1, equation, True)
    if idx < 0:
        raise ComCallError("Add2", (equation,), None, "equação rejeitada — confira a sintaxe")
    com_call(model, "EditRebuild3")
    return {"index": idx, "equation": equation}


def list_features(app: Any, limit: int = 100) -> list[dict[str, Any]]:
    """Árvore de features do documento ativo (nome, tipo, suprimida)."""
    model = _model(_active_doc(app))
    out: list[dict[str, Any]] = []
    raw = com_call(model, "FirstFeature")
    while raw is not None and len(out) < limit:
        feat = cast_to(raw, "IFeature")
        supressed = com_call(feat, "IsSuppressed2", swconst().swThisConfiguration, None)
        if isinstance(supressed, tuple):
            supressed = supressed[0]
        out.append({
            "name": com_call(feat, "Name"),
            "type": com_call(feat, "GetTypeName2"),
            "suppressed": bool(supressed),
        })
        raw = com_call(feat, "GetNextFeature")
    return out
