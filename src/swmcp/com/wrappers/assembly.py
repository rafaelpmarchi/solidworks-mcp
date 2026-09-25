"""Montagens: inserir componentes e mates básicos (escrita). Thread STA."""

from __future__ import annotations

import logging
import os
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.domain.placement import transform_array

log = logging.getLogger(__name__)

MATE_TYPES = {
    "coincident": "swMateCOINCIDENT",
    "concentric": "swMateCONCENTRIC",
    "distance": "swMateDISTANCE",
    "parallel": "swMatePARALLEL",
    "perpendicular": "swMatePERPENDICULAR",
    "tangent": "swMateTANGENT",
    "angle": "swMateANGLE",
    "lock": "swMateLOCK",
}


def _assembly(app: Any) -> Any:
    doc = _active_doc(app)
    if com_call(_model(doc), "GetType") != swconst().swDocASSEMBLY:
        raise ComCallError("AssemblyDoc", (), None, "documento ativo não é montagem")
    return cast_to(doc, "IAssemblyDoc")


def insert_component(app: Any, path: str, x_mm: float = 0, y_mm: float = 0, z_mm: float = 0,
                     rotation_deg: list[float] | None = None,
                     fixed: bool = False) -> dict[str, Any]:
    """Insere um componente na montagem ativa (o arquivo é aberto se preciso).

    (x, y, z) é onde a ORIGEM da peça cai na montagem. rotation_deg=[rx,ry,rz]
    gira a peça em torno dos eixos da montagem, na ordem X → Y → Z. fixed
    deixa o componente fixo (sem posicionamento, a posição é a pedida).
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"arquivo não existe: {path}")
    asm = _assembly(app)
    # o componente precisa estar carregado na sessão para AddComponent5
    from swmcp.com.wrappers import document as doc_w

    if doc_w.find_open_document(app, path) is None:
        doc_w.open_document(app, path, read_only=False)
        com_call(_model(_active_doc(app)), "Visible")  # noop; garante retorno ao ativo
    comp = com_call(
        asm, "AddComponent5", path,
        swconst().swAddComponentConfigOptions_CurrentSelectedConfig, "",
        False, "",
        units.from_mm(x_mm), units.from_mm(y_mm), units.from_mm(z_mm),
    )
    if comp is None:
        raise ComCallError("AddComponent5", (path,), None, "componente não inserido")
    comp = cast_to(comp, "IComponent2")
    nome = com_call(comp, "Name2")
    # AddComponent5 põe o CENTRO DA CAIXA do componente em (x,y,z), não a
    # origem da peça (medido no SW2023: pino 0..30 em y=14 caiu em -1..29).
    # A posição é sempre refeita pela origem, que é o que a tool promete.
    # fixed=False não solta nada: o 1º componente da montagem o SolidWorks
    # já fixa sozinho, e isso fica como está (None = manter o estado)
    posicao = set_component_transform(app, nome, x_mm, y_mm, z_mm,
                                      rotation_deg or [0.0, 0.0, 0.0], True if fixed else None)
    return {"component": nome, "path": path, "placement": posicao}


def list_components(app: Any) -> list[dict[str, Any]]:
    """Componentes de topo da montagem ativa (nome, arquivo, suprimido, fixo)."""
    asm = _assembly(app)
    c = swconst()
    out = []
    for raw in com_call(asm, "GetComponents", True) or ():
        comp = cast_to(raw, "IComponent2")
        out.append({
            "name": com_call(comp, "Name2"),
            "path": com_call(comp, "GetPathName"),
            "suppressed": com_call(comp, "GetSuppression2") == c.swComponentSuppressed,
            "fixed": bool(com_call(comp, "IsFixed")),
        })
    return out


def _find_component(app: Any, name: str) -> Any:
    asm = _assembly(app)
    for raw in com_call(asm, "GetComponents", True) or ():
        comp = cast_to(raw, "IComponent2")
        if com_call(comp, "Name2") == name:
            return comp
    raise ComCallError("GetComponents", (name,), None,
                       "componente não encontrado — use list_components para os nomes")


def set_component_suppressed(app: Any, name: str, suppressed: bool) -> None:
    comp = _find_component(app, name)
    c = swconst()
    state = c.swComponentSuppressed if suppressed else c.swComponentFullyResolved
    result = com_call(comp, "SetSuppression2", state)
    log.info("SetSuppression2(%s, %s) -> %s", name, suppressed, result)


def set_component_fixed(app: Any, name: str, fixed: bool) -> None:
    asm = _assembly(app)
    comp = _find_component(app, name)
    com_call(comp, "Select4", False, None, False)
    com_call(asm, "FixComponent" if fixed else "UnfixComponent")


def _create_transform(app: Any, array: list[float]) -> Any:
    """IMathTransform a partir dos 16 números.

    O array TEM de ir como VARIANT(VT_ARRAY|VT_R8): uma lista Python comum é
    aceita sem erro e vira transformada identidade — o componente "não se
    mexe" e nada avisa. Medido no SW2023.
    """
    import win32com.client

    math_util = cast_to(com_call(app, "GetMathUtility"), "IMathUtility")
    return com_call(math_util, "CreateTransform",
                    win32com.client.VARIANT(8197, [float(v) for v in array]))


def set_component_transform(app: Any, name: str, x_mm: float, y_mm: float, z_mm: float,
                            rotation_deg: list[float] | None = None,
                            fixed: bool | None = None) -> dict[str, Any]:
    """Põe o componente numa posição e rotação ABSOLUTAS na montagem.

    Componente fixo não aceita transformada: é liberado, posicionado e volta
    a fixar (ou fica como fixed pedir). Confere o que o SolidWorks gravou.
    """
    asm = _assembly(app)
    comp = _find_component(app, name)
    estava_fixo = bool(com_call(comp, "IsFixed"))
    if estava_fixo:
        com_call(comp, "Select4", False, None, False)
        com_call(asm, "UnfixComponent")
    alvo = transform_array((x_mm, y_mm, z_mm), rotation_deg or (0.0, 0.0, 0.0))
    comp.Transform2 = _create_transform(app, alvo)
    model = _model(_active_doc(app))
    com_call(model, "EditRebuild3")
    gravado = list(com_call(cast_to(com_get(comp, "Transform2"), "IMathTransform"), "ArrayData"))
    if any(abs(a - b) > 1e-6 for a, b in zip(gravado[:12], alvo[:12])):
        raise ComCallError("Transform2", (name,), None,
                           "o SolidWorks não aceitou a posição — o componente tem "
                           "posicionamentos (mates) que o prendem?")
    fixar = estava_fixo if fixed is None else fixed
    if fixar:
        com_call(comp, "Select4", False, None, False)
        com_call(asm, "FixComponent")
    com_call(model, "ClearSelection2", True)
    caixa = com_call(comp, "GetBox", False, False)
    return {"component": name, "origin_mm": [x_mm, y_mm, z_mm],
            "rotation_deg": list(rotation_deg or [0.0, 0.0, 0.0]), "fixed": fixar,
            "box_mm": [round(units.to_mm(v), 3) for v in caixa] if caixa else None}


def move_component(app: Any, name: str, dx_mm: float, dy_mm: float, dz_mm: float) -> None:
    """Translada um componente (soma ao transform atual). Mates podem limitar."""
    comp = _find_component(app, name)
    xform = com_get(comp, "Transform2")
    if xform is None:
        raise ComCallError("Transform2", (name,), None, "sem transform — componente suprimido?")
    data = list(com_call(cast_to(xform, "IMathTransform"), "ArrayData"))
    data[9] += units.from_mm(dx_mm)
    data[10] += units.from_mm(dy_mm)
    data[11] += units.from_mm(dz_mm)
    comp.Transform2 = _create_transform(app, data)
    com_call(_model(_active_doc(app)), "EditRebuild3")


def check_interference(app: Any) -> list[dict[str, Any]]:
    """Detecção de interferência entre componentes da montagem ativa."""
    asm = _assembly(app)
    mgr = com_call(asm, "InterferenceDetectionManager")
    if mgr is None:
        raise ComCallError("InterferenceDetectionManager", (), None, "indisponível nesta versão")
    mgr = cast_to(mgr, "IInterferenceDetectionMgr")
    mgr.TreatCoincidenceAsInterference = False
    mgr.IncludeMultibodyPartInterferences = True
    raw = com_call(mgr, "GetInterferences")
    out = []
    for item in raw or ():
        inter = cast_to(item, "IInterference")
        comps = com_call(inter, "Components")
        names = []
        for craw in comps or ():
            names.append(com_call(cast_to(craw, "IComponent2"), "Name2"))
        volume = com_get(inter, "Volume")  # m³
        out.append({"components": names, "volume_mm3": round(volume * 1e9, 3)})
    com_call(mgr, "Done")
    return out


ALIGNMENTS = {"aligned": "swMateAlignALIGNED", "anti_aligned": "swMateAlignANTI_ALIGNED",
              "closest": "swMateAlignCLOSEST"}


def add_mate(app: Any, mate_type: str, distance_mm: float = 0.0, angle_deg: float = 0.0,
             flip: bool = False, alignment: str = "closest") -> str:
    """Cria um mate entre as DUAS entidades selecionadas (select_entity com append).

    mate_type: coincident, concentric, distance, parallel, perpendicular,
    tangent, angle, lock. alignment: closest (o SolidWorks escolhe o mais
    perto da posição atual), aligned ou anti_aligned.
    """
    asm = _assembly(app)
    c = swconst()
    try:
        mtype = getattr(c, MATE_TYPES[mate_type])
    except KeyError:
        raise ComCallError("AddMate5", (mate_type,), None,
                           f"tipo inválido; use um de {sorted(MATE_TYPES)}") from None
    if alignment not in ALIGNMENTS:
        raise ComCallError("AddMate5", (alignment,), None,
                           f"alinhamento inválido; use um de {sorted(ALIGNMENTS)}")
    d = units.from_mm(distance_mm)
    a = units.from_deg(angle_deg)
    mate, error = com_call(
        asm, "AddMate5",
        mtype, getattr(c, ALIGNMENTS[alignment]), flip,
        d, d, d, 0.0, 0.0, a, a, a, False, False, 0, 0,
    )
    if mate is None or error != 1:  # swAddMateError_NoError = 1
        raise ComCallError("AddMate5", (mate_type,), None,
                           f"mate não criado (swAddMateError={error}) — as duas entidades estão selecionadas?")
    com_call(_model(_active_doc(app)), "ClearSelection2", True)
    return com_call(cast_to(mate, "IMate2"), "Name") if hasattr(mate, "Name") else mate_type
