"""Validação do modelo e leitura da furação (somente-leitura). Thread STA.

validate_model junta numa chamada o que se confere depois de cada lote de
features: árvore reconstruindo limpa, nenhum esboço azul (regra Gromar),
número de corpos e massa contra a do carimbo do desenho. A massa só vale com a
árvore limpa — feature em erro não corta nada e a massa parece certa (foi o
que aconteceu no 3-50200-92000: 100,03 kg com um furo em erro, 99,99 kg depois).

dump_holes lê os furos do assistente de uma peça de referência — tipo, Ø,
profundidades e a posição de cada furo em coordenadas da PEÇA — para copiar o
padrão de modelagem de outra peça.
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to
from swmcp.com.wrappers import holes, inspect
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.domain.placement import direction_to_local, to_local

log = logging.getLogger(__name__)

FULLY_CONSTRAINED = 3


def _walk(model: Any):
    """Features e sub-features, na ordem da árvore."""
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        yield feat, None
        for sub in inspect._subfeatures(feat):
            yield cast_to(sub, "IFeature"), feat
        raw = com_call(feat, "GetNextFeature")


def sketches_not_fully_defined(app: Any) -> tuple[int, list[dict[str, Any]]]:
    total, ruins, _ = sketch_audit(app)
    return total, ruins


def sketch_audit(app: Any) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    """(nº de esboços, não definidos, com cotas demais para as entidades).

    Cota demais é sinal de cotagem acumulada de várias tentativas — o esboço
    fica sub/sobredefinido sem explicação; sketch_redefine resolve."""
    model = _model(_active_doc(app))
    total, ruins, vistos, inchados = 0, [], set(), []
    for feat, pai in _walk(model):
        if com_call(feat, "GetTypeName2") != "ProfileFeature":
            continue
        nome = com_call(feat, "Name")
        if nome in vistos:
            continue
        vistos.add(nome)
        total += 1
        sketch = cast_to(com_call(feat, "GetSpecificFeature2"), "ISketch")
        estado = com_call(sketch, "GetConstrainedStatus")
        n_seg = len(com_call(sketch, "GetSketchSegments") or [])
        n_cotas = 0
        raw = com_call(feat, "GetFirstDisplayDimension")
        while raw is not None:
            n_cotas += 1
            raw = com_call(feat, "GetNextDisplayDimension", raw)
        if n_cotas > 2 * n_seg + 4:
            inchados.append({"sketch": nome, "dimensions": n_cotas, "segments": n_seg})
        if estado != FULLY_CONSTRAINED:
            ruins.append({"sketch": nome, "parent": com_call(pai, "Name") if pai else None,
                          "status": inspect.SKETCH_STATUS.get(estado, estado)})
    return total, ruins, inchados


def validate_model(app: Any, expected_mass_kg: float | None = None, tolerance_pct: float = 2.0,
                   density_kg_m3: float = 7850.0, expected_bodies: int = 1) -> dict[str, Any]:
    """Reconstrução + esboços + corpos + massa numa chamada; ok=True só com tudo certo."""
    rebuild = inspect.check_rebuild_errors(app, rebuild=True)
    total, ruins, inchados = sketch_audit(app)
    corpos = holes.measure_bodies(app, density_kg_m3)
    massa = round(sum(c["mass_kg"] for c in corpos), 4)
    problemas: list[str] = []
    if not rebuild["clean"]:
        problemas.append(f"{len(rebuild['problems'])} feature(s) com erro/aviso de reconstrução")
    if ruins:
        problemas.append(f"{len(ruins)} esboço(s) não totalmente definido(s)")
    if len(corpos) != expected_bodies:
        problemas.append(f"{len(corpos)} corpo(s) sólido(s), esperado {expected_bodies}")
    desvio = None
    if expected_mass_kg:
        desvio = round((massa - expected_mass_kg) / expected_mass_kg * 100.0, 3)
        if abs(desvio) > tolerance_pct:
            problemas.append(f"massa {massa} kg difere {desvio}% da esperada {expected_mass_kg} kg")
        if not rebuild["clean"]:
            problemas.append("massa não é confiável enquanto houver feature em erro")
    avisos = [f"esboço {i['sketch']} tem {i['dimensions']} cotas para {i['segments']} entidades — "
              "cotagem acumulada? rode sketch_redefine" for i in inchados]
    return {"ok": not problemas, "problems": problemas, "warnings": avisos,
            "rebuild_problems": rebuild["problems"],
            "sketches_checked": total, "sketches_not_fully_defined": ruins,
            "bodies": len(corpos), "mass_kg": massa, "density_kg_m3": density_kg_m3,
            "expected_mass_kg": expected_mass_kg, "mass_deviation_pct": desvio,
            "box_mm": corpos[0]["box_mm"] if len(corpos) == 1 else [c["box_mm"] for c in corpos]}


# ------------------------------------------------------------------ furos

_HOLE_FIELDS = ("Type", "Standard", "FastenerType", "FastenerSize", "EndCondition", "Depth",
                "Diameter", "CounterBoreDiameter", "CounterBoreDepth", "ThreadDepth",
                "TapDrillDiameter", "TapDrillDepth", "ThreadDiameter", "NearCounterSinkDiameter")


def dump_holes(app: Any, name_filter: str = "") -> list[dict[str, Any]]:
    """Furos do assistente: dados da feature e posição de cada furo NA PEÇA (mm).

    'drill_direction' é para onde o furo entra (contrária à normal do esboço
    de posição, que aponta para fora da face).
    """
    model = _model(_active_doc(app))
    saida = []
    for feat, pai in _walk(model):
        if pai is not None or com_call(feat, "GetTypeName2") != "HoleWzd":
            continue
        nome = com_call(feat, "Name")
        if name_filter and name_filter.lower() not in nome.lower():
            continue
        dados: dict[str, Any] = {}
        definicao = cast_to(com_call(feat, "GetDefinition"), "IWizardHoleFeatureData2")
        for campo in _HOLE_FIELDS:
            try:
                v = com_get(definicao, campo)
            except ComCallError:
                continue
            chave = campo[0].lower() + campo[1:]
            dados[chave + ("_mm" if isinstance(v, float) else "")] = (
                round(units.to_mm(v), 4) if isinstance(v, float) else v)
        posicoes, direcao = [], None
        esboco = holes._position_sketch(feat)
        if esboco is not None:
            sketch = cast_to(com_call(esboco, "GetSpecificFeature2"), "ISketch")
            xf = cast_to(com_call(sketch, "ModelToSketchTransform"), "IMathTransform")
            arr = list(com_get(xf, "ArrayData"))
            for raw in com_call(sketch, "GetSketchPoints2") or []:
                pt = cast_to(raw, "ISketchPoint")
                local = (units.to_mm(com_get(pt, "X")), units.to_mm(com_get(pt, "Y")), 0.0)
                posicoes.append([round(v, 4) for v in to_local(arr, local)])
            n = direction_to_local(arr, (0.0, 0.0, 1.0))
            direcao = [round(-c, 6) for c in n]
        saida.append({"feature": nome, **dados, "positions_mm": posicoes,
                      "drill_direction": direcao})
    return saida
