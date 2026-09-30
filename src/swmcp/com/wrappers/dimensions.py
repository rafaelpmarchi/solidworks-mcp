"""Cotas do modelo: listar e tolerar (ajuste ISO, bilateral, simétrica...).

O que a UI mostra numa cota (valor, tolerância, exibir como diâmetro) vive em
dois objetos: IDimension (valor, nome D1@Esboço1) e IDisplayDimension (como a
cota aparece — diametral, tolerância). ``Parameter(nome)`` só devolve o
IDimension, então tudo aqui percorre a árvore e olha as display dimensions de
cada feature (e das sub-features: os esboços de um furo do assistente ficam
dentro dele).

Armadilhas medidas no SW2023:
- o nome curto (D1) se repete entre esboços; a chave certa é o nome completo
  D1@Esboço10 — tolerância aplicada pelo nome curto cai na cota errada;
- cota radial de perfil de revolução (linha × linha de centro) precisa de
  Diametric=True antes do ajuste ISO: H7 sobre "90" calcula o desvio de um
  Ø90, e a peça é Ø180;
- SetFitValues(furo, eixo): letra maiúscula (H7) vai no primeiro argumento,
  minúscula (f7) no segundo; trocar deixa a tolerância 0/0 sem erro.
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.modeling import _active_doc, _model

log = logging.getLogger(__name__)

# swTolType_e. "fit" é swTolFITWITHTOL (8): é o "Ajuste" da UI, com a classe
# e os desvios calculados. swTolFIT (7, mesmo valor de swTolMETRIC) só grava a
# classe e deixa min/max em 0 — medido no SW2023.
TOLERANCE_TYPES = {
    "none": "swTolNONE",
    "basic": "swTolBASIC",
    "bilateral": "swTolBILAT",
    "limit": "swTolLIMIT",
    "symmetric": "swTolSYMMETRIC",
    "min": "swTolMIN",
    "max": "swTolMAX",
    "fit": "swTolFITWITHTOL",
    "fit_class_only": "swTolFIT",
    "fit_tolerance_only": "swTolFITTOLONLY",
}
_TYPE_NAME_BY_CODE: dict[int, str] = {}

# swDimensionParamType_e
_ANGULAR = 2


def _type_names() -> dict[int, str]:
    if not _TYPE_NAME_BY_CODE:
        c = swconst()
        for nome, enum in TOLERANCE_TYPES.items():
            _TYPE_NAME_BY_CODE[getattr(c, enum)] = nome
    return _TYPE_NAME_BY_CODE


def _short_name(full_name: str) -> str:
    """'D1@Esboço2@peça.Part' → 'D1@Esboço2'."""
    partes = full_name.split("@")
    return "@".join(partes[:2])


def _walk_features(model: Any, subfeatures: bool = True):
    """Gera (feature, nome do pai ou None) na ordem da árvore."""
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        yield feat, None
        if subfeatures:
            pai = com_get(feat, "Name")
            sub = com_call(feat, "GetFirstSubFeature")
            while sub is not None:
                subf = cast_to(sub, "IFeature")
                yield subf, pai
                sub = com_call(subf, "GetNextSubFeature")
        raw = com_call(feat, "GetNextFeature")


def _display_dimensions(feature: Any):
    raw = com_call(feature, "GetFirstDisplayDimension")
    while raw is not None:
        disp = cast_to(raw, "IDisplayDimension")
        yield disp
        raw = com_call(feature, "GetNextDisplayDimension", disp)


def _tolerance_info(dim: Any) -> dict[str, Any]:
    tol = cast_to(com_get(dim, "Tolerance"), "IDimensionTolerance")
    codigo = com_get(tol, "Type")
    nome = _type_names().get(codigo, str(codigo))
    if nome == "none":
        return {"type": "none"}
    minimo = com_call(tol, "GetMinValue2")
    maximo = com_call(tol, "GetMaxValue2")
    info: dict[str, Any] = {"type": nome,
                            "lower_mm": round(units.to_mm(minimo[1]), 4) if isinstance(minimo, tuple) else None,
                            "upper_mm": round(units.to_mm(maximo[1]), 4) if isinstance(maximo, tuple) else None}
    if nome == "symmetric" and info["upper_mm"] is not None:
        info["lower_mm"] = -info["upper_mm"]   # a API guarda só o máximo na simétrica
    if nome.startswith("fit"):
        furo = com_call(tol, "GetHoleFitValue") or ""
        eixo = com_call(tol, "GetShaftFitValue") or ""
        info["fit"] = f"{furo}{eixo}"
    return info


def _dimension_entry(disp: Any, feature_name: str) -> dict[str, Any]:
    dim = cast_to(com_call(disp, "GetDimension2", 0), "IDimension")
    angular = com_call(dim, "GetType") == _ANGULAR
    valor = com_get(dim, "SystemValue")
    return {
        "name": _short_name(com_get(dim, "FullName")),
        "feature": feature_name,
        "value": round(units.to_deg(valor) if angular else units.to_mm(valor), 4),
        "unit": "deg" if angular else "mm",
        "diametric": bool(com_get(disp, "Diametric")),
        "driven": com_get(dim, "DrivenState") == 1,  # swDimensionDrivenState_e: 1 = driven, 2 = driving
        "tolerance": _tolerance_info(dim),
    }


def list_dimensions(app: Any, feature_name: str = "") -> list[dict[str, Any]]:
    """Cotas de uma feature (com as dos esboços dela) ou de toda a árvore.

    Cada cota vem com nome completo (D1@Esboço10 — é ele que se passa a
    set_dimension/set_dimension_tolerance), valor, se é exibida como diâmetro
    e a tolerância atual. Sem feature_name percorre a árvore inteira; cotas
    repetidas (o esboço aparece na feature pai e como sub-feature) saem uma vez.
    """
    return list_dimensions_of(_model(_active_doc(app)), feature_name)


def list_dimensions_of(model: Any, feature_name: str = "") -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    vistos: set[str] = set()
    achou = not feature_name
    # O esboço absorvido por uma feature (Revolução1 ← Esboço1) é sub-feature
    # e as cotas dele aparecem na feature pai: pedir qualquer um dos dois nomes
    # tem de devolver as mesmas cotas.
    for feat, pai in _walk_features(model):
        nome = com_get(feat, "Name")
        if feature_name and feature_name not in (nome, pai):
            continue
        achou = True
        for disp in _display_dimensions(feat):
            item = _dimension_entry(disp, pai or nome)
            if item["name"] in vistos:
                continue
            vistos.add(item["name"])
            saida.append(item)
    if not achou:
        raise ComCallError("list_dimensions", (feature_name,), None,
                           "feature não encontrada na árvore — confira o nome em list_features")
    return saida


def _find_display_dimension(model: Any, full_name: str) -> tuple[Any, Any]:
    alvo = _short_name(full_name)
    for feat, _ in _walk_features(model):
        for disp in _display_dimensions(feat):
            dim = cast_to(com_call(disp, "GetDimension2", 0), "IDimension")
            if _short_name(com_get(dim, "FullName")) == alvo:
                return disp, dim
    raise ComCallError("set_dimension_tolerance", (full_name,), None,
                       "cota não encontrada — use o nome completo D1@Esboço1 (list_dimensions)")


def set_dimension_tolerance(app: Any, full_name: str, tolerance_type: str = "fit",
                            fit: str = "", upper_mm: float = 0.0, lower_mm: float = 0.0,
                            show_as_diameter: bool | None = None) -> dict[str, Any]:
    """Aplica tolerância a uma cota, como na caixa de cota da UI.

    tolerance_type: fit (ajuste ISO — fit='H7' furo, 'f7' eixo), bilateral
    (upper_mm/lower_mm, ex.: +0,05 / 0), symmetric (±upper_mm), limit
    (valores absolutos em upper_mm/lower_mm), min, max, basic, none.
    show_as_diameter força a cota radial a exibir como diâmetro (o ajuste é
    calculado sobre o valor exibido; sem isso H7 num raio sai errado).
    Devolve os desvios que o SolidWorks calculou, para conferir.
    """
    enum = TOLERANCE_TYPES.get(tolerance_type)
    if enum is None:
        raise ComCallError("set_dimension_tolerance", (tolerance_type,), None,
                           f"tolerance_type deve ser um de {sorted(TOLERANCE_TYPES)}")
    if tolerance_type.startswith("fit") and not fit:
        raise ComCallError("set_dimension_tolerance", (full_name,), None,
                           "ajuste ISO precisa de fit (ex.: 'H7' furo, 'g6' eixo)")
    model = _model(_active_doc(app))
    disp, dim = _find_display_dimension(model, full_name)
    if show_as_diameter is not None:
        disp.Diametric = bool(show_as_diameter)
    c = swconst()
    tol = cast_to(com_get(dim, "Tolerance"), "IDimensionTolerance")
    tol.Type = getattr(c, enum)
    if tolerance_type.startswith("fit"):
        furo = fit if fit[:1].isupper() else ""
        eixo = fit if fit[:1].islower() else ""
        if not com_call(tol, "SetFitValues", furo, eixo):
            raise ComCallError("SetFitValues", (full_name, fit), None,
                               "ajuste recusado — é uma letra ISO válida (H7, g6, f7...)?")
    elif tolerance_type in ("bilateral", "limit", "min", "max"):
        com_call(tol, "SetValues", units.from_mm(lower_mm), units.from_mm(upper_mm))
    elif tolerance_type == "symmetric":
        com_call(tol, "SetValues", units.from_mm(-abs(upper_mm)), units.from_mm(abs(upper_mm)))
    com_call(model, "EditRebuild3")
    item = _dimension_entry(disp, "")
    del item["feature"]
    if tolerance_type == "fit":
        t = item["tolerance"]
        if not t.get("upper_mm") and not t.get("lower_mm"):
            raise ComCallError("SetFitValues", (full_name, fit), None,
                               "o ajuste ficou 0/0 — o SolidWorks não reconheceu a classe; "
                               "confira a letra (maiúscula = furo, minúscula = eixo) e o valor da cota")
    return item
