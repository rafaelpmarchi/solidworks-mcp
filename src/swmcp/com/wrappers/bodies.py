"""Corpos da peça: listar, mostrar/ocultar, mover por matriz, virar superfície.

Nasceu da engenharia reversa da aranha de disco de freio (02/10/2026), onde
tudo isto foi run_sw_script:
- a malha de 2,5 M de triângulos visível deixava CADA chamada de API lenta
  (minutos) — ocultar o corpo enquanto modela resolve;
- levar a malha do SolidWorks para o sistema alinhado do motor exigiu
  Mover/Copiar corpo com a ordem dos ângulos medida na marra;
- a "superfície do lado escaneado" saiu de um sólido auxiliar por
  Superfície equidistante de 0 mm nas faces voltadas para o scan.

Executa no thread STA; entradas em mm/graus.
"""

from __future__ import annotations

import fnmatch
import logging
import math
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.domain.placement import euler_xyz_deg

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ listagem

def _part(app: Any) -> Any:
    doc = _active_doc(app)
    if com_call(_model(doc), "GetType") != swconst().swDocPART:
        raise ComCallError("bodies", (), None, "o documento ativo não é uma peça")
    return cast_to(doc, "IPartDoc")


def _all_bodies(app: Any) -> list[tuple[Any, str]]:
    """(IBody2, 'solid'|'surface') de todos os corpos, visíveis ou não."""
    c = swconst()
    part = _part(app)
    out = []
    for tipo, nome in ((c.swSolidBody, "solid"), (c.swSheetBody, "surface")):
        for raw in com_call(part, "GetBodies2", tipo, False) or []:
            out.append((cast_to(raw, "IBody2"), nome))
    return out


def _box_mm(body: Any) -> list[float]:
    return [round(units.to_mm(v), 3) for v in com_call(body, "GetBodyBox")]


def list_bodies(app: Any) -> list[dict[str, Any]]:
    """Nome, tipo, visibilidade, nº de faces e caixa (mm) de cada corpo."""
    out = []
    for body, tipo in _all_bodies(app):
        out.append({"name": com_get(body, "Name"), "type": tipo,
                    "visible": bool(com_get(body, "Visible")),
                    "faces": int(com_call(body, "GetFaceCount")),
                    "box_mm": _box_mm(body)})
    return out


def _find_body(app: Any, name: str = "") -> tuple[Any, str]:
    """Corpo pelo nome; sem nome, o de maior caixa (a malha importada ou o
    sólido principal)."""
    corpos = _all_bodies(app)
    if not corpos:
        raise ComCallError("GetBodies2", (), None, "a peça não tem corpos")
    if name:
        for body, tipo in corpos:
            if com_get(body, "Name") == name:
                return body, tipo
        raise ComCallError("GetBodies2", (name,), None,
                           f"corpo {name!r} não existe — nomes: "
                           f"{[com_get(b, 'Name') for b, _ in corpos]}")

    def diagonal(item):
        b = _box_mm(item[0])
        return math.dist(b[:3], b[3:])
    return max(corpos, key=diagonal)


# --------------------------------------------------------------- visibilidade

def set_body_visibility(app: Any, names: list[str] | None = None, visible: bool = False,
                        pattern: str = "", body_type: str = "") -> dict[str, Any]:
    """Mostra/oculta corpos por nome, por padrão glob ('*Importado*') ou por
    tipo ('solid'/'surface'). Sem filtro nenhum, recusa — ocultar tudo por
    engano é pior que não fazer nada."""
    if not names and not pattern and not body_type:
        raise ComCallError("set_body_visibility", (), None,
                           "passe names, pattern ou body_type")
    alterados = []
    for body, tipo in _all_bodies(app):
        nome = com_get(body, "Name")
        if names and nome not in names:
            continue
        if pattern and not fnmatch.fnmatch(nome, pattern):
            continue
        if body_type and tipo != body_type:
            continue
        com_call(body, "HideBody", not visible)
        alterados.append(nome)
    com_call(_model(_active_doc(app)), "GraphicsRedraw2")
    return {"changed": alterados, "visible": visible}


def set_reference_visibility(app: Any, names: list[str] | None = None,
                             visible: bool = False, kinds: list[str] | None = None) -> dict[str, Any]:
    """Mostra/oculta planos, eixos e sistemas de coordenadas pelo nome ou por
    tipo (kinds: 'plane', 'axis', 'csys'). Os 3 planos padrão só entram se
    nomeados — eles são a referência de quase todo esboço."""
    tipos = {"plane": "RefPlane", "axis": "RefAxis", "csys": "CoordSys"}
    alvo_tipos = {tipos[k] for k in (kinds or []) if k in tipos}
    if not names and not alvo_tipos:
        raise ComCallError("set_reference_visibility", (), None, "passe names ou kinds")
    model = _model(_active_doc(app))
    alterados, planos_vistos = [], 0
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        tipo = com_call(feat, "GetTypeName2")
        nome = com_call(feat, "Name")
        if tipo == "RefPlane":
            planos_vistos += 1
        escolhido = (names and nome in names) or (
            tipo in alvo_tipos and not (tipo == "RefPlane" and planos_vistos <= 3))
        if escolhido:
            com_call(model, "ClearSelection2", True)
            com_call(feat, "Select2", False, 0)
            com_call(model, "UnblankRefGeom" if visible else "BlankRefGeom")
            alterados.append(nome)
        raw = com_call(feat, "GetNextFeature")
    com_call(model, "ClearSelection2", True)
    return {"changed": alterados, "visible": visible}


# ------------------------------------------------------------- mover corpo

# InsertMoveCopyBody2(..., ang1, ang2, ang3, ...): medido no SW2023 — o 1º
# ângulo gira em torno de Z e o 3º em torno de X (ordem inversa do nome dos
# parâmetros). Um feature por eixo evita depender da ordem de composição.
_PARAM_ROT = {"x": 2, "y": 1, "z": 0}


def _move_copy(app: Any, model: Any, body_name: str, body_type: str,
               translate_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
               axis: str = "", angle_deg: float = 0.0) -> str:
    fm = com_get(model, "FeatureManager")
    ext = com_get(model, "Extension")
    com_call(model, "ClearSelection2", True)
    sel_tipo = "SOLIDBODY" if body_type == "solid" else "SURFACEBODY"
    if not com_call(ext, "SelectByID2", body_name, sel_tipo, 0.0, 0.0, 0.0, False, 1, None, 0):
        raise ComCallError("SelectByID2", (body_name, sel_tipo), None, "corpo não selecionado")
    ang = [0.0, 0.0, 0.0]
    if axis:
        ang[_PARAM_ROT[axis]] = math.radians(angle_deg)
    feat = com_call(fm, "InsertMoveCopyBody2",
                    *(units.from_mm(v) for v in translate_mm), 0.0,
                    0.0, 0.0, 0.0, *ang, False, 1)
    if feat is None:
        raise ComCallError("InsertMoveCopyBody2", (body_name, axis, angle_deg), None,
                           "Mover/Copiar corpo não foi criado")
    return com_call(cast_to(feat, "IFeature"), "Name")


def move_body_by_matrix(app: Any, matrix: list[float], body_name: str = "",
                        expected_box_mm: list[float] | None = None,
                        tolerance_mm: float = 2.0) -> dict[str, Any]:
    """Aplica uma transformação rígida 4x4 (16 números por linha, vetor-coluna:
    p' = R·p + t, em mm — a convenção do motor de malha) a um corpo, com
    features Mover/Copiar corpo: giro em X, em Y, em Z (eixos fixos, pela
    origem) e a translação. Confere a caixa final contra expected_box_mm
    [xmin,ymin,zmin,xmax,ymax,zmax] quando vier."""
    if len(matrix) != 16:
        raise ComCallError("move_body_by_matrix", (len(matrix),), None, "matriz precisa de 16 números")
    rot = [[float(matrix[4 * i + j]) for j in range(3)] for i in range(3)]
    t = tuple(float(matrix[4 * i + 3]) for i in range(3))
    det = (rot[0][0] * (rot[1][1] * rot[2][2] - rot[1][2] * rot[2][1])
           - rot[0][1] * (rot[1][0] * rot[2][2] - rot[1][2] * rot[2][0])
           + rot[0][2] * (rot[1][0] * rot[2][1] - rot[1][1] * rot[2][0]))
    if abs(det - 1.0) > 1e-3:
        raise ComCallError("move_body_by_matrix", (det,), None,
                           "a matriz não é uma rotação pura (det ≠ 1) — espelho/escala não")
    rx, ry, rz = euler_xyz_deg(rot)

    model = _model(_active_doc(app))
    body, tipo = _find_body(app, body_name)
    nome = com_get(body, "Name")
    antes = _box_mm(body)
    features = []
    for axis, ang in (("x", rx), ("y", ry), ("z", rz)):
        if abs(ang) > 1e-7:
            features.append(_move_copy(app, model, nome, tipo, axis=axis, angle_deg=ang))
            nome = features[-1]
    if any(abs(v) > 1e-6 for v in t):
        features.append(_move_copy(app, model, nome, tipo, translate_mm=t))
        nome = features[-1]
    # o corpo movido ganha o nome da última feature
    try:
        body, _ = _find_body(app, nome)
    except ComCallError:
        body, _ = _find_body(app)
        nome = com_get(body, "Name")
    depois = _box_mm(body)
    out: dict[str, Any] = {"body": nome, "features": features,
                           "rotation_xyz_deg": [round(rx, 6), round(ry, 6), round(rz, 6)],
                           "translation_mm": [round(v, 4) for v in t],
                           "box_before_mm": antes, "box_after_mm": depois}
    if expected_box_mm:
        erro = max(abs(a - b) for a, b in zip(depois, expected_box_mm))
        out["box_error_mm"] = round(erro, 3)
        out["ok"] = erro <= tolerance_mm
        if not out["ok"]:
            out["aviso"] = (f"a caixa do corpo movido difere {erro:.2f} mm da esperada — "
                            "o corpo não era a malha original deste alinhamento?")
    return out


# ------------------------------------------------- superfície a partir de faces

def _face_mean_normal(face: Any) -> tuple[float, float, float] | None:
    nrm = com_call(face, "GetTessNorms")
    if not nrm:
        return None
    k = len(nrm) // 3
    return tuple(sum(nrm[3 * i + j] for i in range(k)) / k for j in range(3))  # type: ignore[return-value]


def surface_from_faces(app: Any, body_name: str = "",
                       direction: list[float] | None = None, min_dot: float = -0.3,
                       distance_mm: float = 0.0, feature_name: str = "",
                       hide_source: bool = False) -> dict[str, Any]:
    """Superfície equidistante (offset) das faces de um corpo sólido cuja
    normal média aponta para `direction` (produto escalar > min_dot).

    O padrão (direção +Z, min_dot -0,3) pega as faces de cima e as paredes
    laterais e deixa de fora as de baixo — é "o lado que o scanner viu" de uma
    peça escaneada por cima. distance_mm 0 = cópia exata das faces."""
    d = [float(v) for v in (direction or [0.0, 0.0, 1.0])]
    norma = math.sqrt(sum(v * v for v in d)) or 1.0
    d = [v / norma for v in d]
    if body_name:
        body, _ = _find_body(app, body_name)
    else:
        solidos = [b for b, t in _all_bodies(app) if t == "solid"]
        if not solidos:
            raise ComCallError("surface_from_faces", (), None, "a peça não tem corpo sólido")
        body = max(solidos, key=lambda b: math.dist(_box_mm(b)[:3], _box_mm(b)[3:]))
    model = _model(_active_doc(app))
    com_call(model, "ClearSelection2", True)
    escolhidas = 0
    total = 0
    for raw in com_call(body, "GetFaces") or []:
        face = cast_to(raw, "IFace2")
        total += 1
        n = _face_mean_normal(face)
        if n is None:
            continue
        if sum(a * b for a, b in zip(n, d)) > min_dot:
            if com_call(cast_to(face, "IEntity"), "Select4", True, None):
                escolhidas += 1
    if not escolhidas:
        raise ComCallError("surface_from_faces", (d, min_dot), None,
                           "nenhuma face aponta para essa direção")
    com_call(model, "InsertOffsetSurface", units.from_mm(distance_mm), False)
    feat = cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature")
    nome = com_call(feat, "Name")
    if feature_name:
        feat.Name = feature_name
        nome = com_call(feat, "Name")
    com_call(model, "ClearSelection2", True)
    if hide_source:
        com_call(body, "HideBody", True)
    superficies = [com_get(b, "Name") for b, t in _all_bodies(app) if t == "surface"]
    return {"feature": nome, "faces_selected": escolhidas, "faces_total": total,
            "source_body": com_get(body, "Name"), "surface_bodies": superficies}
