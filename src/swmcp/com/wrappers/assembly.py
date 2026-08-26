"""Montagens: inserir componentes e mates básicos (escrita). Thread STA."""

from __future__ import annotations

import logging
import os
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.modeling import _active_doc, _model

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


def insert_component(app: Any, path: str, x_mm: float = 0, y_mm: float = 0, z_mm: float = 0) -> dict[str, Any]:
    """Insere um componente na montagem ativa (o arquivo é aberto se preciso)."""
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
    return {"component": com_call(cast_to(comp, "IComponent2"), "Name2"), "path": path}


def add_mate(app: Any, mate_type: str, distance_mm: float = 0.0, angle_deg: float = 0.0,
             flip: bool = False) -> str:
    """Cria um mate entre as DUAS entidades selecionadas (select_entity com append).

    mate_type: coincident, concentric, distance, parallel, perpendicular,
    tangent, angle, lock.
    """
    asm = _assembly(app)
    c = swconst()
    try:
        mtype = getattr(c, MATE_TYPES[mate_type])
    except KeyError:
        raise ComCallError("AddMate5", (mate_type,), None,
                           f"tipo inválido; use um de {sorted(MATE_TYPES)}") from None
    d = units.from_mm(distance_mm)
    a = units.from_deg(angle_deg)
    mate, error = com_call(
        asm, "AddMate5",
        mtype, c.swMateAlignCLOSEST, flip,
        d, d, d, 0.0, 0.0, a, a, a, False, False, 0, 0,
    )
    if mate is None or error != 1:  # swAddMateError_NoError = 1
        raise ComCallError("AddMate5", (mate_type,), None,
                           f"mate não criado (swAddMateError={error}) — as duas entidades estão selecionadas?")
    com_call(_model(_active_doc(app)), "ClearSelection2", True)
    return com_call(cast_to(mate, "IMate2"), "Name") if hasattr(mate, "Name") else mate_type
