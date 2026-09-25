"""Chapa metálica: flange-base a partir de um esboço (escrita). Thread STA.

A flange-base cria o corpo de chapa, a feature "Sheet-Metal" com espessura,
raio e fator K, e a planificação — é o que faz a peça sair com lista de corte
e planificado corretos, coisa que uma extrusão fina não dá.

Medido no SW2023 (API em PT-BR):
- IFeatureManager::InsertSheetMetalBaseFlange2 (19 args) devolve None sempre,
  com qualquer combinação de alívio/escopo; InsertSheetMetalBaseFlange
  (16 args, com ICustomBendAllowance) funciona e é o que se usa aqui;
- perfil ABERTO (L, U, Z) vira perfil dobrado extrudado em depth_mm; perfil
  FECHADO vira chapa plana (depth ignorado, a espessura é a extrusão);
- thicken_reverse escolhe o lado do perfil para onde a espessura cresce. Para
  o perfil ser a face EXTERNA (cotas externas, 40×40 de cantoneira), a
  espessura tem de ir para dentro — qual dos dois valores faz isso depende do
  sentido em que o perfil foi desenhado, então a tool devolve a caixa do corpo
  para conferir.
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers import modeling, sketch_define

log = logging.getLogger(__name__)


def _model(app: Any) -> Any:
    doc = com_get(app, "ActiveDoc")
    if doc is None:
        raise ComCallError("ActiveDoc", (), None, "nenhum documento ativo no SolidWorks")
    return cast_to(doc, "IModelDoc2")


def _bodies_summary(app: Any) -> list[dict[str, Any]]:
    part = cast_to(com_get(app, "ActiveDoc"), "IPartDoc")
    saida = []
    for raw in com_call(part, "GetBodies2", 0, True) or []:
        body = cast_to(raw, "IBody2")
        props = com_call(body, "GetMassProperties", 7850.0)
        caixa = com_call(body, "GetBodyBox")
        saida.append({"name": com_get(body, "Name"),
                      "volume_mm3": round(props[3] * 1e9, 3),
                      "box_mm": [round(units.to_mm(v), 3) for v in caixa]})
    return saida


def sheet_metal_base_flange(
    app: Any,
    thickness_mm: float,
    depth_mm: float = 0.0,
    bend_radius_mm: float = 0.0,
    k_factor: float = 0.5,
    thicken_reverse: bool = False,
    reverse_direction: bool = False,
    sketch_name: str = "",
    fully_define: bool = True,
) -> dict[str, Any]:
    """Flange-base do esboço aberto (ou do esboço nomeado).

    bend_radius_mm=0 usa raio interno igual à espessura. Antes de criar a
    feature o esboço é deixado totalmente definido (fully_define).
    """
    if thickness_mm <= 0:
        raise ComCallError("sheet_metal_base_flange", (thickness_mm,), None, "espessura deve ser > 0")
    if not 0.0 < k_factor < 1.0:
        raise ComCallError("sheet_metal_base_flange", (k_factor,), None, "fator K deve estar entre 0 e 1")
    raio = bend_radius_mm or thickness_mm
    model = _model(app)
    skm = com_get(model, "SketchManager")

    definicao = None
    if com_get(skm, "ActiveSketch") is not None:
        nome = com_call(cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature"), "Name")
        if sketch_name and sketch_name != nome:
            raise ComCallError("sheet_metal_base_flange", (sketch_name,), None,
                               f"o esboço aberto é {nome}, não {sketch_name}")
        if fully_define:
            definicao = sketch_define.fully_define_sketch(app)
        modeling.exit_sketch(app)
    elif sketch_name:
        nome = sketch_name
        if fully_define:
            definicao = sketch_define.fully_define_sketch(app, sketch_name)
    else:
        raise ComCallError("sheet_metal_base_flange", (), None,
                           "abra/desenhe o esboço do perfil antes (ou informe sketch_name)")

    com_call(model, "ClearSelection2", True)
    if not com_call(com_get(model, "Extension"), "SelectByID2", nome, "SKETCH",
                    0.0, 0.0, 0.0, False, 0, None, swconst().swSelectOptionDefault):
        raise ComCallError("SelectByID2", (nome,), None, "esboço do perfil não selecionado")

    c = swconst()
    fm = cast_to(com_get(model, "FeatureManager"), "IFeatureManager")
    cba = cast_to(com_call(fm, "CreateCustomBendAllowance"), "ICustomBendAllowance")
    cba.Type = c.swBendAllowanceKFactor
    cba.KFactor = float(k_factor)
    feat = com_call(
        fm, "InsertSheetMetalBaseFlange",
        units.from_mm(thickness_mm), thicken_reverse, units.from_mm(raio),
        units.from_mm(depth_mm), 0.0, reverse_direction,
        c.swEndCondBlind, c.swEndCondBlind, 0,
        cba, False, 1, units.from_mm(0.5), units.from_mm(0.5), 0.5, True,
    )
    if feat is None:
        raise ComCallError("InsertSheetMetalBaseFlange", (nome, thickness_mm, depth_mm), None,
                           "flange-base não criada — o perfil tem um único contorno (aberto "
                           "precisa de depth_mm > 0)? a peça já tem corpo de chapa?")
    nome_feat = com_call(cast_to(feat, "IFeature"), "Name")
    log.info("flange-base %s: esp %.2f, raio %.2f, K %.2f, prof %.1f",
             nome_feat, thickness_mm, raio, k_factor, depth_mm)
    return {"feature": nome_feat, "sketch": nome, "thickness_mm": thickness_mm,
            "bend_radius_mm": raio, "k_factor": k_factor, "depth_mm": depth_mm,
            "sketch_definition": definicao, "bodies": _bodies_summary(app)}
