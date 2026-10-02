"""Modelagem 3D: sketches e features (escrita). Executa no thread STA.

Convenções:
- Entradas em mm/graus; conversão aqui (RNF-03).
- Toda operação retorna o que criou (nome da feature/sketch) ou levanta
  ComCallError com contexto — nunca sucesso silencioso (RNF-01).
- Nada aqui salva arquivo: salvar é decisão explícita (RNF-05).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from swmcp.com import units
from swmcp.com.constants import (
    SKETCH_MERGE_TOGGLES,
    SKETCH_SNAP_TOGGLES,
    SKETCH_TOLERANCE_MM,
)
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.domain.corners import EdgeCandidate, select_corner_edges

log = logging.getLogger(__name__)


def _model(doc: Any) -> Any:
    return cast_to(doc, "IModelDoc2")


def _active_doc(app: Any) -> Any:
    doc = com_get(app, "ActiveDoc")
    if doc is None:
        raise ComCallError("ActiveDoc", (), None, "nenhum documento ativo no SolidWorks")
    return doc


# ------------------------------------------------------------------ seleção

def select_entity(
    app: Any,
    name: str,
    entity_type: str,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
    z_mm: float = 0.0,
    append: bool = False,
    mark: int = 0,
) -> bool:
    """SelectByID2. Para FACE/EDGE/VERTEX sem nome, use as coordenadas (mm).

    entity_type: PLANE, FACE, EDGE, VERTEX, SKETCH, BODYFEATURE, AXIS,
    SKETCHSEGMENT, COMPONENT, DATUMPLANE etc. (nomes da API).
    """
    model = _model(_active_doc(app))
    ext = com_get(model, "Extension")
    ok = com_call(
        ext, "SelectByID2",
        name, entity_type,
        units.from_mm(x_mm), units.from_mm(y_mm), units.from_mm(z_mm),
        append, mark, None, swconst().swSelectOptionDefault,
    )
    if not ok:
        raise ComCallError(
            "SelectByID2", (name, entity_type, x_mm, y_mm, z_mm), None,
            "nada selecionado — confira nome/tipo/coordenadas (coordenadas em mm)",
        )
    return True


def clear_selection(app: Any) -> None:
    com_call(_model(_active_doc(app)), "ClearSelection2", True)


# ------------------------------------------------------------------ sketch

def insert_sketch(app: Any, plane_name: str | None = None) -> str:
    """Abre um sketch no plano/face indicado (ou na seleção atual)."""
    model = _model(_active_doc(app))
    if plane_name:
        try:
            select_entity(app, plane_name, "PLANE")
        except ComCallError:
            select_entity(app, plane_name, "FACE")
    skm = com_get(model, "SketchManager")
    _insert_sketch_retry(skm, want_open=True)
    if com_get(skm, "ActiveSketch") is None:
        raise ComCallError("InsertSketch", (plane_name,), None, "sketch não foi aberto")
    # nome via última feature da árvore (cast ISketch→IFeature resolve dispid errado)
    feat = cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature")
    return com_call(feat, "Name")


def exit_sketch(app: Any) -> None:
    """Fecha o sketch ativo (confirma)."""
    skm = com_get(_model(_active_doc(app)), "SketchManager")
    _insert_sketch_retry(skm, want_open=False)


RPC_E_SERVERFAULT = -2147417851  # 0x80010105: o SolidWorks lançou exceção interna


def _insert_sketch_retry(skm: Any, want_open: bool, attempts: int = 4) -> None:
    """InsertSketch(True) com repetição.

    Logo depois de abrir/fechar/ativar outro documento o SolidWorks às vezes
    responde 0x80010105 ("the server threw an exception") a InsertSketch —
    mas pode ter executado a ação mesmo assim (InsertSketch alterna abrir/
    fechar), por isso o estado é conferido antes de repetir. Medido no SW2023.
    """
    import time

    last: ComCallError | None = None
    for i in range(attempts):
        try:
            com_call(skm, "InsertSketch", True)
            return
        except ComCallError as exc:
            if exc.hresult != RPC_E_SERVERFAULT:
                raise
            last = exc
            time.sleep(1.0 + i)
            if (com_get(skm, "ActiveSketch") is not None) == want_open:
                log.warning("InsertSketch respondeu 0x80010105 mas o sketch ficou no estado pedido")
                return
            log.warning("InsertSketch recusado pelo SolidWorks (tentativa %d/%d); repetindo", i + 1, attempts)
    assert last is not None
    raise last


def _skm(app: Any) -> Any:
    model = _model(_active_doc(app))
    skm = com_get(model, "SketchManager")
    if com_get(skm, "ActiveSketch") is None:
        raise ComCallError("SketchManager", (), None, "não há sketch ativo — use create_sketch antes")
    return skm


# ------------------------------------------------- precisão do esboço (snaps)

@contextmanager
def precise_sketching(app: Any) -> Iterator[None]:
    """Desenha sem os snaps que arredondam a geometria, e restaura tudo depois.

    Os snaps da UI valem também para a API: com eles ligados o SolidWorks aceita
    as coordenadas pedidas e grava outras (medido no SW2023 — Ø67,6 vira 70; um
    canto em y=55 perto de um Ø120 vira 60), sem erro nenhum. Já swSketchInference
    e swSketchAutomaticRelations ficam LIGADOS de propósito: são eles que unem os
    endpoints coincidentes de linhas criadas em chamadas separadas — sem isso o
    contorno fica aberto e a feature falha sem dizer o motivo.

    As preferências são do SolidWorks (persistentes), por isso o estado anterior
    é restaurado no finally, inclusive quando a modelagem levanta exceção.
    """
    sc = swconst()
    anterior: dict[str, bool] = {}
    try:
        for nome in (*SKETCH_SNAP_TOGGLES, *SKETCH_MERGE_TOGGLES):
            flag = getattr(sc, nome)
            anterior[nome] = bool(com_call(app, "GetUserPreferenceToggle", flag))
        for nome in SKETCH_SNAP_TOGGLES:
            com_call(app, "SetUserPreferenceToggle", getattr(sc, nome), False)
        for nome in SKETCH_MERGE_TOGGLES:
            com_call(app, "SetUserPreferenceToggle", getattr(sc, nome), True)
        yield
    finally:
        for nome, valor in anterior.items():
            try:
                com_call(app, "SetUserPreferenceToggle", getattr(sc, nome), valor)
            except ComCallError:  # restaurar é best-effort; o resto tem que continuar
                log.exception("não consegui restaurar a preferência de esboço %s", nome)


@contextmanager
def no_dimension_prompt(app: Any) -> Iterator[None]:
    """Cota criada por API sem o diálogo "Modificar".

    Com swInputDimValOnCreate ligado (o padrão do usuário) cada AddDimension
    abre o diálogo modal e a chamada COM fica presa até alguém clicar —
    medido no SW2023 cotando um perfil por run_sw_script (12 diálogos, minutos
    parado). A preferência volta ao valor anterior no fim.
    """
    c = swconst()
    anterior = bool(com_call(app, "GetUserPreferenceToggle", c.swInputDimValOnCreate))
    com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, False)
    try:
        yield
    finally:
        try:
            com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, anterior)
        except ComCallError:
            log.exception("não consegui restaurar swInputDimValOnCreate")


def _segment_points_mm(segment: Any) -> list[tuple[float, float]]:
    """Endpoints de um ISketchSegment de linha, em mm."""
    line = cast_to(segment, "ISketchLine")
    saida = []
    for prop in ("GetStartPoint2", "GetEndPoint2"):
        ponto = cast_to(com_get(line, prop), "ISketchPoint")
        saida.append((units.to_mm(com_get(ponto, "X")), units.to_mm(com_get(ponto, "Y"))))
    return saida


def _check_points(op: str, args: tuple, pedidos: list[tuple[float, float]],
                  obtidos: list[tuple[float, float]]) -> None:
    """Falha se o SolidWorks gravou coordenadas diferentes das pedidas."""
    faltando = [p for p in pedidos
                if not any(abs(p[0] - o[0]) < SKETCH_TOLERANCE_MM
                           and abs(p[1] - o[1]) < SKETCH_TOLERANCE_MM for o in obtidos)]
    if faltando:
        raise ComCallError(
            op, args, None,
            f"o SolidWorks gravou coordenadas diferentes das pedidas {faltando} "
            f"(gravou {obtidos}) — algum snap de esboço continua ligado",
        )


def sketch_line(app: Any, x1: float, y1: float, x2: float, y2: float, centerline: bool = False) -> None:
    skm = _skm(app)
    method = "CreateCenterLine" if centerline else "CreateLine"
    with precise_sketching(app):
        seg = com_call(skm, method,
                       units.from_mm(x1), units.from_mm(y1), 0.0,
                       units.from_mm(x2), units.from_mm(y2), 0.0)
    if seg is None:
        raise ComCallError(method, (x1, y1, x2, y2), None, "segmento não criado")
    _check_points(method, (x1, y1, x2, y2), [(x1, y1), (x2, y2)], _segment_points_mm(seg))


def sketch_circle(app: Any, xc: float, yc: float, diameter: float) -> None:
    with precise_sketching(app):
        seg = com_call(_skm(app), "CreateCircleByRadius",
                       units.from_mm(xc), units.from_mm(yc), 0.0,
                       units.from_mm(diameter / 2.0))
    if seg is None:
        raise ComCallError("CreateCircleByRadius", (xc, yc, diameter), None, "círculo não criado")
    arco = cast_to(seg, "ISketchArc")
    raio = units.to_mm(com_call(arco, "GetRadius"))
    if abs(raio * 2.0 - diameter) > SKETCH_TOLERANCE_MM:
        raise ComCallError("CreateCircleByRadius", (xc, yc, diameter), None,
                           f"círculo saiu com Ø{raio * 2:.4f} em vez de Ø{diameter} "
                           "— algum snap de esboço continua ligado")


def model_to_sketch_mm(app: Any, points_mm: list[list[float]]) -> list[tuple[float, float, float]]:
    """Pontos da PEÇA (mm) → coordenadas do esboço ativo (mm). O 3º valor é a
    distância ao plano do esboço (≠ 0 = o ponto está fora dele)."""
    from swmcp.domain.placement import apply_transform

    sketch = cast_to(com_get(_skm(app), "ActiveSketch"), "ISketch")
    xf = list(com_get(cast_to(com_call(sketch, "ModelToSketchTransform"), "IMathTransform"),
                      "ArrayData"))
    return [apply_transform(xf, (p[0], p[1], p[2] if len(p) > 2 else 0.0)) for p in points_mm]


def _circle_spec(c: Any, center: tuple[float, float]) -> tuple[float, float, float]:
    """(x, y, Ø) de um item de sketch_circles: [x, y, d] ou {x, y, d} ou
    polar {r, angle_deg, d} em torno de center."""
    import math

    if isinstance(c, (list, tuple)):
        if len(c) != 3:
            raise ComCallError("sketch_circles", (c,), None, "item em lista é [x, y, diâmetro]")
        return float(c[0]), float(c[1]), float(c[2])
    d = float(c.get("d", c.get("diameter", 0)))
    if "r" in c or "radius_from_center" in c:
        r = float(c.get("r", c.get("radius_from_center")))
        ang = math.radians(float(c.get("angle_deg", 0.0)))
        return center[0] + r * math.cos(ang), center[1] + r * math.sin(ang), d
    return float(c["x"]), float(c["y"]), d


def sketch_circles(app: Any, circles: list[Any],
                   center: tuple[float, float] = (0.0, 0.0)) -> dict[str, Any]:
    """Vários círculos no esboço ativo numa chamada só, cada um conferido.

    Item: [x, y, Ø] | {"x","y","d"} | polar {"r","angle_deg","d"} em torno de
    center (furação: PCD/2 e ângulo). Desenha com os snaps desligados uma vez
    só — 30 furos chamando sketch_circle um a um levavam minutos."""
    specs = [_circle_spec(c, center) for c in circles]
    skm = _skm(app)
    errados = []
    with precise_sketching(app):
        for x, y, d in specs:
            if d <= 0:
                raise ComCallError("sketch_circles", (x, y, d), None, "diâmetro tem que ser > 0")
            seg = com_call(skm, "CreateCircleByRadius",
                           units.from_mm(x), units.from_mm(y), 0.0, units.from_mm(d / 2.0))
            if seg is None:
                raise ComCallError("CreateCircleByRadius", (x, y, d), None, "círculo não criado")
            raio = units.to_mm(com_call(cast_to(seg, "ISketchArc"), "GetRadius"))
            if abs(raio * 2.0 - d) > SKETCH_TOLERANCE_MM:
                errados.append({"x": x, "y": y, "pedido": d, "gravado": round(raio * 2, 4)})
    if errados:
        raise ComCallError("sketch_circles", (len(specs),), None,
                           f"círculos gravados com Ø diferente do pedido: {errados}")
    return {"circles": len(specs),
            "centers_mm": [[round(x, 4), round(y, 4)] for x, y, _ in specs]}


def sketch_rectangle(app: Any, x1: float, y1: float, x2: float, y2: float, center: bool = False) -> None:
    skm = _skm(app)
    metodo = "CreateCenterRectangle" if center else "CreateCornerRectangle"
    with precise_sketching(app):
        segs = com_call(skm, metodo,
                        units.from_mm(x1), units.from_mm(y1), 0.0,
                        units.from_mm(x2), units.from_mm(y2), 0.0)
    if not segs:
        raise ComCallError("CreateRectangle", (x1, y1, x2, y2), None, "retângulo não criado")
    if not center:
        obtidos = [p for s in segs for p in _segment_points_mm(s)]
        cantos = [(a, b) for a in (x1, x2) for b in (y1, y2)]
        _check_points(metodo, (x1, y1, x2, y2), cantos, obtidos)


def sketch_arc_center(app: Any, xc: float, yc: float, x1: float, y1: float, x2: float, y2: float,
                      direction: int = 1, short_arc: bool = True,
                      merge_ends: bool = True) -> dict[str, Any]:
    """Arco por centro + início + fim. direction: 1 anti-horário, -1 horário.

    short_arc (padrão): o arco tem que ser o CURTO entre as pontas — o
    CreateArc às vezes sai com o maior (medido no SW2023: o sentido depende
    da orientação do esboço), e isso passa despercebido até a massa mudar
    +10 000 mm³. O comprimento é conferido e o arco refeito no outro sentido.

    merge_ends (padrão): une cada ponta do arco ao ponto que já existe na
    mesma coordenada. Fechando um contorno de sketch_polyline, a inferência
    une só UMA das pontas (medido no SW2023, roda de polo 10006900433); a
    outra fica duplicada e o corte é recusado sem explicação.
    """
    resultado = _sketch_arc_center(app, xc, yc, x1, y1, x2, y2, direction, short_arc)
    if merge_ends:
        resultado["merged_ends"] = _merge_points_at(app, [(x1, y1), (x2, y2)])
    return resultado


def _sketch_arc_center(app: Any, xc: float, yc: float, x1: float, y1: float, x2: float, y2: float,
                       direction: int, short_arc: bool) -> dict[str, Any]:
    import math

    raio = math.hypot(x1 - xc, y1 - yc)
    tentativas = (direction, -direction) if short_arc else (direction,)
    with precise_sketching(app):
        for sentido in tentativas:
            seg = com_call(_skm(app), "CreateArc",
                           units.from_mm(xc), units.from_mm(yc), 0.0,
                           units.from_mm(x1), units.from_mm(y1), 0.0,
                           units.from_mm(x2), units.from_mm(y2), 0.0, sentido)
            if seg is None:
                raise ComCallError("CreateArc", (xc, yc), None, "arco não criado")
            comprimento = units.to_mm(com_call(cast_to(seg, "ISketchSegment"), "GetLength"))
            if not short_arc or comprimento <= math.pi * raio + 1e-3:
                return {"length_mm": round(comprimento, 4), "direction": sentido}
            model = _model(_active_doc(app))
            com_call(model, "ClearSelection2", True)
            com_call(seg, "Select4", False, None)
            com_call(model, "EditDelete")
    raise ComCallError("CreateArc", (xc, yc), None, "o arco curto não saiu em nenhum sentido")


def sketch_polyline(app: Any, points_mm: list[list[float]], close: bool = False,
                    close_with_centerline: bool = False) -> dict[str, Any]:
    """Perfil inteiro numa tacada: linhas ponto a ponto, com os snaps desligados.

    close fecha o contorno com uma linha comum do último ponto ao primeiro;
    close_with_centerline fecha com linha de CENTRO (é o eixo da revolução).
    Devolve quantos segmentos saíram e quantos contornos fechados o sketch tem —
    revolve/extrude exigem 1 contorno fechado.
    """
    if len(points_mm) < 2:
        raise ComCallError("sketch_polyline", (len(points_mm),), None,
                           "preciso de pelo menos 2 pontos")
    if close and close_with_centerline:
        raise ComCallError("sketch_polyline", (), None,
                           "escolha close OU close_with_centerline, não os dois")
    pontos = [(float(p[0]), float(p[1])) for p in points_mm]
    skm = _skm(app)
    criados = 0
    with precise_sketching(app):
        pares = list(zip(pontos, pontos[1:]))
        if close or close_with_centerline:
            pares.append((pontos[-1], pontos[0]))
        for i, (a, b) in enumerate(pares):
            ultimo = i == len(pares) - 1
            metodo = "CreateCenterLine" if (ultimo and close_with_centerline) else "CreateLine"
            seg = com_call(skm, metodo,
                           units.from_mm(a[0]), units.from_mm(a[1]), 0.0,
                           units.from_mm(b[0]), units.from_mm(b[1]), 0.0)
            if seg is None:
                raise ComCallError(metodo, (a, b), None, f"segmento {i + 1} não criado")
            _check_points(metodo, (a, b), [a, b], _segment_points_mm(seg))
            criados += 1
    if close or close_with_centerline:
        _merge_coincident_points(app)
    sketch = cast_to(com_get(skm, "ActiveSketch"), "ISketch")
    contornos = len(com_call(sketch, "GetSketchContours") or [])
    pontos_sketch = len(com_call(sketch, "GetSketchPoints2") or [])
    if (close or close_with_centerline) and contornos != 1:
        log.warning("perfil fechado esperava 1 contorno, saíram %d (%d pontos para %d segmentos)",
                    contornos, pontos_sketch, criados)
    return {"segments": criados, "closed_contours": contornos, "sketch_points": pontos_sketch}


def _merge_coincident_points(app: Any, limite: int = 200) -> int:
    """Une os endpoints que estão na mesma coordenada mas são pontos diferentes.

    A linha que FECHA um contorno volta a um ponto criado várias chamadas antes,
    e o SolidWorks não o mescla: o esboço fica com um vértice duplicado que
    GetSketchContours ainda conta como fechado, mas revolve/extrude rejeitam sem
    dizer por quê. Cada coincidência recria as entidades, então a lista é refeita
    a cada volta.

    Lê os pontos do esboço (GetSketchPoints2, um objeto por ponto) e não as
    pontas de cada linha: num perfil a ponta final de uma linha e a inicial da
    seguinte são o MESMO ponto, que contado duas vezes parecia duplicado — o
    laço rodava as 200 voltas em todo sketch_polyline fechado.
    """
    model = _model(_active_doc(app))
    unidos = 0
    total_anterior = None
    for _ in range(limite):
        skm = com_get(model, "SketchManager")
        ativo = com_get(skm, "ActiveSketch")
        if ativo is None:
            break
        sketch = cast_to(ativo, "ISketch")
        pontos_sk = [cast_to(p, "ISketchPoint")
                     for p in com_call(sketch, "GetSketchPoints2") or []]
        if total_anterior is not None and len(pontos_sk) >= total_anterior:
            log.warning("a coincidência não uniu os pontos duplicados; parando")
            unidos -= 1
            break
        total_anterior = len(pontos_sk)
        grupos: dict[tuple[float, float], list[Any]] = {}
        for ponto in pontos_sk:
            chave = (round(units.to_mm(com_get(ponto, "X")), 4),
                     round(units.to_mm(com_get(ponto, "Y")), 4))
            grupos.setdefault(chave, []).append(ponto)
        duplicado = next(((k, v) for k, v in grupos.items() if len(v) > 1), None)
        if duplicado is None:
            break
        _, pontos = duplicado
        com_call(model, "ClearSelection2", True)
        com_call(pontos[0], "Select4", False, None)
        com_call(pontos[1], "Select4", True, None)
        com_call(model, "SketchAddConstraints", "sgCOINCIDENT")
        unidos += 1
    com_call(model, "ClearSelection2", True)
    return unidos


def _merge_points_at(app: Any, coords_mm: list[tuple[float, float]], limite: int = 20) -> int:
    """Une os pontos do esboço ativo que caem em cada coordenada dada.

    Versão dirigida de _merge_coincident_points: olha só as coordenadas
    pedidas (as pontas de uma entidade recém-criada), em vez de varrer o
    contorno inteiro — sketch_arc é chamado em laço pelo desdobramento de
    malha, e a varredura completa a cada arco ficaria quadrática.
    """
    model = _model(_active_doc(app))
    alvos = [(float(x), float(y)) for x, y in coords_mm]
    unidos = 0
    total_anterior = None
    for _ in range(limite):
        ativo = com_get(com_get(model, "SketchManager"), "ActiveSketch")
        if ativo is None:
            break
        pontos = [cast_to(p, "ISketchPoint")
                  for p in com_call(cast_to(ativo, "ISketch"), "GetSketchPoints2") or []]
        if total_anterior is not None and len(pontos) >= total_anterior:
            log.warning("a coincidência não uniu os pontos em %s", alvos)
            unidos -= 1
            break
        total_anterior = len(pontos)
        par = None
        for ax, ay in alvos:
            juntos = [p for p in pontos
                      if abs(units.to_mm(com_get(p, "X")) - ax) < SKETCH_TOLERANCE_MM
                      and abs(units.to_mm(com_get(p, "Y")) - ay) < SKETCH_TOLERANCE_MM]
            if len(juntos) > 1:
                par = juntos[:2]
                break
        if par is None:
            break
        com_call(model, "ClearSelection2", True)
        com_call(par[0], "Select4", False, None)
        com_call(par[1], "Select4", True, None)
        com_call(model, "SketchAddConstraints", "sgCOINCIDENT")
        unidos += 1
    com_call(model, "ClearSelection2", True)
    return unidos


def sketch_polygon(app: Any, xc: float, yc: float, sides: int, diameter: float, inscribed: bool = True) -> None:
    segs = com_call(_skm(app), "CreatePolygon",
                    units.from_mm(xc), units.from_mm(yc), 0.0,
                    units.from_mm(xc + diameter / 2.0), units.from_mm(yc), 0.0,
                    sides, inscribed)
    if not segs:
        raise ComCallError("CreatePolygon", (xc, yc, sides), None, "polígono não criado")


# ------------------------------------------------------------------ features

def _feature_name(feat: Any, op: str) -> str:
    if feat is None:
        raise ComCallError(op, (), None, "feature não criada — o SolidWorks rejeitou a operação "
                                         "(sketch aberto/perfil inválido/seleção faltando?)")
    return com_call(cast_to(feat, "IFeature"), "Name")


def extrude(app: Any, depth_mm: float, cut: bool = False, flip: bool = False,
            through_all: bool = False, both_directions: bool = False,
            reverse_direction: bool = False) -> str:
    """Extrusão (boss ou corte) do sketch ativo/selecionado — só o nome.
    Ver extrude_detail."""
    return extrude_detail(app, depth_mm, cut, flip, through_all, both_directions,
                          reverse_direction, auto_reverse=False)["feature"]


def extrude_detail(app: Any, depth_mm: float, cut: bool = False, flip: bool = False,
                   through_all: bool = False, both_directions: bool = False,
                   reverse_direction: bool = False,
                   auto_reverse: bool = True) -> dict[str, Any]:
    """Extrusão (boss ou corte) do sketch ativo/selecionado.

    São três coisas diferentes, fáceis de confundir:
    - reverse_direction (Dir da API): para que lado do plano do sketch a
      extrusão cresce. É isto que se quer para cortar "para o outro lado".
      ATENÇÃO: no CORTE o sentido padrão é CONTRA a normal do plano (entra na
      face onde o esboço está), no ressalto é A FAVOR — o mesmo
      reverse_direction aponta para lados opostos nos dois.
    - both_directions (Sd=False): cresce para os dois lados do plano.
    - flip (Flip da API): em corte, inverte QUAL LADO do perfil vira material —
      passar flip=True por engano tira tudo menos o prisma do perfil.

    auto_reverse: corte que o SolidWorks recusa (devolve None — tipicamente
    porque do lado pedido não há material) é tentado de novo para o outro
    lado. O retorno diz qual sentido valeu em reverse_direction_used.
    """
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    _clear_selection_if_sketch_open(model)
    c = swconst()
    end = c.swEndCondThroughAll if through_all else c.swEndCondBlind
    d = units.from_mm(abs(depth_mm))
    single_ended = not both_directions

    def criar(rev: bool) -> Any:
        if cut:
            return com_call(
                fm, "FeatureCut4",
                single_ended, flip, rev, end, end, d, d, False, False, False, False,
                0.0, 0.0, False, False, False, False, False, True, True,
                True, True, False, c.swStartSketchPlane, 0.0, False, False,
            )
        return com_call(
            fm, "FeatureExtrusion3",
            single_ended, flip, rev, end, end, d, d, False, False, False, False,
            0.0, 0.0, False, False, False, False, True, True, True,
            c.swStartSketchPlane, 0.0, False,
        )

    usado = reverse_direction
    feat = criar(usado)
    if feat is None and cut and auto_reverse and not both_directions:
        log.warning("corte recusado com reverse_direction=%s; tentando o outro lado", usado)
        usado = not reverse_direction
        feat = criar(usado)
    name = _feature_name(feat, "FeatureCut4" if cut else "FeatureExtrusion3")
    log.info("extrusão %s criada: %s (%.2fmm, %s)", "corte" if cut else "boss", name, depth_mm,
             "duas direções" if both_directions else ("invertida" if usado else "normal"))
    out: dict[str, Any] = {"feature": name, "reverse_direction_used": usado}
    if usado != reverse_direction:
        out["aviso"] = ("o corte foi recusado para o lado pedido e saiu com "
                        f"reverse_direction={usado} — confira se era esse o lado")
    return out


def _clear_selection_if_sketch_open(model: Any) -> None:
    """Com esboço ABERTO, a feature usa as entidades selecionadas (contornos
    selecionados) em vez do esboço inteiro. A cotagem automática deixa linha
    selecionada e o revolve saía recusado sem motivo (medido no SW2023, perfil
    de disco com concordâncias). Esboço fechado e selecionado fica como está."""
    if com_get(com_get(model, "SketchManager"), "ActiveSketch") is not None:
        com_call(model, "ClearSelection2", True)


def revolve(app: Any, angle_deg: float = 360.0, cut: bool = False) -> str:
    """Revolução do sketch ativo (precisa de linha de centro no sketch)."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    _clear_selection_if_sketch_open(model)
    ang = units.from_deg(angle_deg)

    def criar() -> Any:
        return com_call(
            fm, "FeatureRevolve2",
            True, True, False, cut, False, False, 0, 0, ang, 0.0,
            False, False, 0.0, 0.0, 0, 0.0, 0.0, True, True, True,
        )

    feat = criar()
    if feat is None and com_get(com_get(model, "SketchManager"), "ActiveSketch") is not None:
        # medido no SW2023: logo depois da cotagem automática de um perfil com
        # concordâncias o 1º FeatureRevolve2 volta None e o 2º, no MESMO
        # esboço, sai certo
        import time

        log.warning("revolve recusado na 1ª tentativa com o esboço aberto; repetindo")
        time.sleep(1.0)
        _clear_selection_if_sketch_open(model)
        feat = criar()
    return _feature_name(feat, "FeatureRevolve2")


def fillet(app: Any, radius_mm: float) -> str:
    """Filete de raio constante nas arestas SELECIONADAS (select_entity EDGE)."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    # assinatura: (Options, R1, R2, Rho, Ftyp, OverflowType, ConicRhoType, + 7 arrays)
    # 195 = flags padrão dos exemplos oficiais; Ftyp 0 = raio constante
    feat = com_call(
        fm, "FeatureFillet3",
        195, units.from_mm(radius_mm), 0.0, 0.0, 0, 0, 0,
        None, None, None, None, None, None, None,
    )
    return _feature_name(feat, "FeatureFillet3")


# ------------------------------------------------------------ cantos de abertura

def _feature_by_name(model: Any, name: str) -> Any:
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        if com_call(feat, "Name") == name:
            return feat
        raw = com_call(feat, "GetNextFeature")
    raise ComCallError("FeatureByName", (name,), None, "feature não existe no documento ativo (use list_features)")


def _point_mm(pt: Any) -> tuple[float, float, float]:
    return (units.to_mm(pt[0]), units.to_mm(pt[1]), units.to_mm(pt[2]))


def _edge_candidate(edge: Any, plate_normal: tuple[float, float, float]) -> EdgeCandidate | None:
    """Descreve uma aresta para o domínio; None para aresta fechada (círculo inteiro)."""
    v1 = com_call(edge, "GetStartVertex")
    v2 = com_call(edge, "GetEndVertex")
    if v1 is None or v2 is None:
        return None
    start = _point_mm(com_call(cast_to(v1, "IVertex"), "GetPoint"))
    end = _point_mm(com_call(cast_to(v2, "IVertex"), "GetPoint"))
    # GetCurve().IsLine() responde 0x80010108 (objeto desconectado) em parte das
    # arestas vindas de IVertex.GetEdges; o tipo em GetCurveParams3 é estável.
    params = cast_to(com_call(edge, "GetCurveParams3"), "ICurveParamData")
    is_line = com_get(params, "CurveType") == swconst().LINE_TYPE
    mid_m = tuple(units.from_mm((start[k] + end[k]) / 2.0) for k in range(3))
    normals: list[tuple[float, float, float]] = []
    for raw_face in com_call(edge, "GetTwoAdjacentFaces2") or []:
        surf = cast_to(com_call(cast_to(raw_face, "IFace2"), "GetSurface"), "ISurface")
        ev = com_call(surf, "EvaluateAtPoint", *mid_m)  # [nx, ny, nz, ...]
        if ev:
            normals.append((ev[0], ev[1], ev[2]))
    return EdgeCandidate(start=start, end=end, plate_normal=plate_normal,
                         face_normals=tuple(normals), is_line=is_line)


def _opening_corner_candidates(feature: Any, include_outer: bool) -> tuple[list[EdgeCandidate], list[Any], int]:
    """Arestas que chegam aos vértices dos contornos das aberturas nas faces planas da feature.

    Devolve (candidatos, objetos IEdge na mesma ordem, nº de faces de chapa achadas).
    """
    cands: list[EdgeCandidate] = []
    edge_objs: list[Any] = []
    seen_vertices: set[tuple[float, float, float]] = set()
    n_plate_faces = 0
    for raw_face in com_call(feature, "GetFaces") or []:
        face = cast_to(raw_face, "IFace2")
        surf = cast_to(com_call(face, "GetSurface"), "ISurface")
        if not com_call(surf, "IsPlane"):
            continue
        loops = [cast_to(lp, "ILoop2") for lp in (com_call(face, "GetLoops") or [])]
        wanted = loops if include_outer else [lp for lp in loops if not com_call(lp, "IsOuter")]
        if not wanted:
            continue
        pp = com_call(surf, "PlaneParams")  # [nx, ny, nz, px, py, pz]
        normal = (pp[0], pp[1], pp[2])
        n_plate_faces += 1
        for loop in wanted:
            for raw_edge in com_call(loop, "GetEdges") or []:
                loop_edge = cast_to(raw_edge, "IEdge")
                for getter in ("GetStartVertex", "GetEndVertex"):
                    raw_v = com_call(loop_edge, getter)
                    if raw_v is None:
                        continue  # contorno fechado (furo redondo) não tem canto
                    vertex = cast_to(raw_v, "IVertex")
                    key = tuple(round(x, 3) for x in _point_mm(com_call(vertex, "GetPoint")))
                    if key in seen_vertices:
                        continue
                    seen_vertices.add(key)
                    for raw_e in com_call(vertex, "GetEdges") or []:
                        edge = cast_to(raw_e, "IEdge")
                        cand = _edge_candidate(edge, normal)
                        if cand is not None:
                            cands.append(cand)
                            edge_objs.append(edge)
    return cands, edge_objs, n_plate_faces


FILLET_ERROR_NO_EDGE = 13  # swFeatureErrorFilletNoEdge: o SW descartou arestas do filete


def fillet_opening_corners(
    app: Any,
    feature_name: str,
    radius_mm: float,
    region_mm: list[float] | None = None,
    include_outer: bool = False,
    preview: bool = False,
) -> dict[str, Any]:
    """Filete de raio constante em TODOS os cantos das aberturas de uma chapa.

    Os cantos são as arestas retas que atravessam a espessura nos contornos
    internos (furos/fendas/grelhas) das faces planas da feature. Arestas
    tangentes (costura de furo redondo, filete já existente) são ignoradas,
    então chamar de novo não duplica nada. Uma feature de filete por chamada.
    """
    if radius_mm <= 0:
        raise ValueError("radius_mm precisa ser positivo")
    model = _model(_active_doc(app))
    feat = _feature_by_name(model, feature_name)
    cands, edge_objs, n_plate = _opening_corner_candidates(feat, include_outer)
    if n_plate == 0:
        raise ComCallError(
            "fillet_opening_corners", (feature_name,), None,
            "a feature não tem face plana com contorno interno — não é uma chapa com "
            "abertura fechada (furo/fenda/grelha). Aberturas que tocam a borda entram "
            "só com include_outer=True",
        )
    sel = select_corner_edges(cands, region_mm)
    result: dict[str, Any] = {
        "source_feature": feature_name,
        "corners": len(sel.corners),
        "corner_points_mm": [[round(v, 2) for v in c.mid] for c in sel.corners],
        "thickness_mm": sorted({c.length_mm for c in sel.corners}),
        "skipped": sel.skipped,
        "fillet": None,
    }
    if preview:
        return result
    if not sel.corners:
        raise ComCallError(
            "fillet_opening_corners", (feature_name, radius_mm), None,
            f"nenhum canto vivo encontrado (descartes: {sel.skipped}) — já filetado? região errada?",
        )

    com_call(model, "ClearSelection2", True)
    selmgr = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    sel_data = cast_to(com_call(selmgr, "CreateSelectData"), "ISelectData")
    sel_data.Mark = 1  # FeatureFillet3 lê as arestas com marca 1
    for corner in sel.corners:
        entity = cast_to(edge_objs[corner.index], "IEntity")
        if not com_call(entity, "Select4", True, sel_data):
            raise ComCallError("Select4", (corner.mid,), None, "aresta de canto não pôde ser selecionada")
    n_sel = com_call(selmgr, "GetSelectedObjectCount2", -1)
    if n_sel != len(sel.corners):
        raise ComCallError("Select4", (n_sel, len(sel.corners)), None, "seleção incompleta das arestas de canto")

    name = fillet(app, radius_mm)
    com_call(model, "ClearSelection2", True)
    new_feat = _feature_by_name(model, name)
    code, is_warning = com_call(new_feat, "GetErrorCode2", True)
    n_faces = len(com_call(new_feat, "GetFaces") or [])
    result.update({"fillet": name, "radius_mm": radius_mm, "fillet_faces": n_faces,
                   "error_code": int(code), "warning": bool(is_warning)})
    if code:
        why = ("o SolidWorks descartou arestas — raio maior que o canto permite, ou canto de "
               "corpo separado que só encosta na chapa" if code == FILLET_ERROR_NO_EDGE
               else "confira a árvore de features")
        result["message"] = f"filete criado com aviso (código {code}): {why}"
        log.warning("%s: %s", name, result["message"])
    log.info("filete de cantos %s: R%.2f em %d cantos de %s", name, radius_mm, len(sel.corners), feature_name)
    return result


def chamfer(app: Any, distance_mm: float, angle_deg: float = 45.0) -> str:
    """Chanfro distância-ângulo nas arestas SELECIONADAS."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    feat = com_call(
        fm, "InsertFeatureChamfer",
        4, 1, units.from_mm(distance_mm), units.from_deg(angle_deg), 0.0, 0.0, 0.0, 0.0,
    )
    return _feature_name(feat, "InsertFeatureChamfer")


def shell(app: Any, thickness_mm: float) -> str:
    """Casca com as faces SELECIONADAS removidas."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    feat = com_call(fm, "InsertFeatureShell", units.from_mm(thickness_mm), False)
    return _feature_name(feat, "InsertFeatureShell")


def reference_plane_offset(app: Any, base_plane: str, offset_mm: float, flip: bool = False) -> str:
    """Plano de referência paralelo a um plano/face com offset."""
    model = _model(_active_doc(app))
    select_entity(app, base_plane, "PLANE")
    fm = com_get(model, "FeatureManager")
    c = swconst()
    flag = c.swRefPlaneReferenceConstraint_Distance
    if flip:
        flag |= c.swRefPlaneReferenceConstraint_OptionFlip
    feat = com_call(fm, "InsertRefPlane", flag, units.from_mm(offset_mm), 0, 0.0, 0, 0.0)
    if feat is None:
        raise ComCallError("InsertRefPlane", (base_plane, offset_mm), None, "plano não criado")
    # cast IRefPlane→IFeature resolve dispid errado; nome via árvore
    last = cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature")
    return com_call(last, "Name")


def sketch_point(app: Any, x: float, y: float) -> None:
    if com_call(_skm(app), "CreatePoint", units.from_mm(x), units.from_mm(y), 0.0) is None:
        raise ComCallError("CreatePoint", (x, y), None, "ponto não criado")


def sketch_ellipse(app: Any, xc: float, yc: float, major_radius: float, minor_radius: float) -> None:
    seg = com_call(_skm(app), "CreateEllipse",
                   units.from_mm(xc), units.from_mm(yc), 0.0,
                   units.from_mm(xc + major_radius), units.from_mm(yc), 0.0,
                   units.from_mm(xc), units.from_mm(yc + minor_radius), 0.0)
    if seg is None:
        raise ComCallError("CreateEllipse", (xc, yc), None, "elipse não criada")


def sketch_slot(app: Any, x1: float, y1: float, x2: float, y2: float, width: float) -> None:
    """Rasgo (slot) reto entre dois centros, com a largura dada."""
    c = swconst()
    segs = com_call(_skm(app), "CreateSketchSlot",
                    c.swSketchSlotCreationType_line, c.swSketchSlotLengthType_CenterCenter,
                    units.from_mm(width),
                    units.from_mm(x1), units.from_mm(y1), 0.0,
                    units.from_mm(x2), units.from_mm(y2), 0.0,
                    0.0, 0.0, 0.0, 1, False)
    if not segs:
        raise ComCallError("CreateSketchSlot", (x1, y1, x2, y2, width), None, "slot não criado")


def sketch_spline(app: Any, points_mm: list[list[float]]) -> None:
    """Spline pelos pontos [[x,y], ...] (mínimo 3)."""
    if len(points_mm) < 3:
        raise ValueError("spline precisa de ao menos 3 pontos")
    flat: list[float] = []
    for p in points_mm:
        flat += [units.from_mm(p[0]), units.from_mm(p[1]), 0.0]
    import win32com.client

    arr = win32com.client.VARIANT(8197, flat)  # VT_ARRAY|VT_R8
    seg = com_call(_skm(app), "CreateSpline2", arr, True)
    if seg is None:
        raise ComCallError("CreateSpline2", (len(points_mm),), None, "spline não criada")


def sketch_3d_splines(app: Any, curves_mm: list[list[list[float]]]) -> str:
    """Sketch 3D novo com uma spline por curva ([[x,y,z], ...] em mm cada).

    Usado pelo 3D Sketch sobre o scan: as curvas vêm do viewer com os pontos
    grudados na malha."""
    import win32com.client

    model = _model(_active_doc(app))
    skm = com_get(model, "SketchManager")
    com_call(skm, "Insert3DSketch", True)
    if com_get(skm, "ActiveSketch") is None:
        raise ComCallError("Insert3DSketch", (), None, "sketch 3D não abriu")
    try:
        for pts in curves_mm:
            if len(pts) < 2:
                continue
            flat: list[float] = []
            for p in pts:
                flat += [units.from_mm(p[0]), units.from_mm(p[1]),
                         units.from_mm(p[2])]
            arr = win32com.client.VARIANT(8197, flat)  # VT_ARRAY|VT_R8
            seg = com_call(skm, "CreateSpline2", arr, True)
            if seg is None:
                raise ComCallError("CreateSpline2", (len(pts),), None,
                                   "spline 3D não criada")
    finally:
        com_call(skm, "Insert3DSketch", True)  # fecha o sketch 3D
    feat = cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature")
    return com_call(feat, "Name")


def sketch_text(app: Any, x: float, y: float, text: str, height_mm: float = 5.0) -> None:
    """Texto de sketch (extrudável) posicionado em (x, y)."""
    _skm(app)  # exige sketch ativo
    model = _model(_active_doc(app))
    seg = com_call(model, "InsertSketchText",
                   units.from_mm(x), units.from_mm(y), 0.0, text, 0, 0, 0, 100, 0)
    if seg is None:
        raise ComCallError("InsertSketchText", (text,), None, "texto não criado")


def sketch_fillet(app: Any, radius_mm: float) -> None:
    """Arredonda o canto entre as DUAS linhas selecionadas do sketch ativo."""
    seg = com_call(_skm(app), "CreateFillet", units.from_mm(radius_mm),
                   swconst().swConstrainedCornerKeepGeometry)
    if seg is None:
        raise ComCallError("CreateFillet", (radius_mm,), None,
                           "filete de sketch não criado — duas entidades selecionadas?")


def sketch_offset(app: Any, distance_mm: float, reverse: bool = False) -> None:
    """Offset das entidades de sketch selecionadas."""
    ok = com_call(_skm(app), "SketchOffset2", units.from_mm(distance_mm),
                  reverse, True, swconst().swSkOffsetArcEndCondition,
                  swconst().swSkOffsetMakeConstruction_No, False)
    if not ok:
        raise ComCallError("SketchOffset2", (distance_mm,), None, "offset falhou")


def convert_entities(app: Any) -> None:
    """Projeta as arestas/faces selecionadas no sketch ativo (Converter entidades)."""
    model = _model(_active_doc(app))
    if not com_call(model, "SketchUseEdge3", False, False):
        raise ComCallError("SketchUseEdge3", (), None, "nada convertido — selecione arestas/face antes")


def edit_sketch(app: Any, sketch_name: str) -> str:
    """Reabre um sketch existente para edição (feche com exit_sketch)."""
    model = _model(_active_doc(app))
    com_call(model, "ClearSelection2", True)
    ext = com_get(model, "Extension")
    if not com_call(ext, "SelectByID2", sketch_name, "SKETCH", 0.0, 0.0, 0.0,
                    False, 0, None, swconst().swSelectOptionDefault):
        raise ComCallError("SelectByID2", (sketch_name,), None, "sketch não encontrado pelo nome")
    com_call(model, "EditSketch")
    if com_get(com_get(model, "SketchManager"), "ActiveSketch") is None:
        raise ComCallError("EditSketch", (sketch_name,), None, "sketch não entrou em edição")
    return sketch_name


def add_sketch_dimension(app: Any, x_mm: float, y_mm: float, value_mm: float | None = None) -> str:
    """Cota a entidade de sketch SELECIONADA, posicionando o texto em (x,y).

    Se value_mm vier, a cota é ajustada para esse valor (dirige a geometria).
    """
    model = _model(_active_doc(app))
    with no_dimension_prompt(app):
        raw = com_call(model, "AddDimension2", units.from_mm(x_mm), units.from_mm(y_mm), 0.0)
    if raw is None:
        raise ComCallError("AddDimension2", (x_mm, y_mm), None,
                           "cota não criada — selecione a entidade do sketch antes")
    dd = cast_to(raw, "IDisplayDimension")
    dim = cast_to(com_call(dd, "GetDimension2", 0), "IDimension")
    name = com_get(dim, "FullName")
    if value_mm is not None:
        com_call(dim, "SetSystemValue3", units.from_mm(value_mm),
                 swconst().swSetValue_InThisConfiguration, None)
        com_call(model, "EditRebuild3")
    return name


# ------------------------------------------------------- features avançadas

def linear_pattern(app: Any, count1: int, spacing1_mm: float, count2: int = 1,
                   spacing2_mm: float = 0.0, flip1: bool = False, flip2: bool = False) -> str:
    """Padrão linear das features selecionadas.

    Seleção esperada: features com mark=4; direção 1 (aresta/eixo) mark=1;
    direção 2 opcional mark=2.
    """
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    selecao = _snapshot_selection(model)

    def cria(f1: bool) -> Any:
        # (Num1, Spacing1, Num2, Spacing2, FlipDir1, FlipDir2, DName1, DName2,
        #  GeometryPattern, VaryInstance, HasOffset1, HasOffset2, CtrlByNum1,
        #  CtrlByNum2, FromCentroid1, FromCentroid2, RevOffset1, RevOffset2,
        #  Offset1, Offset2, D2PatternSeedOnly, SyncSubAssemblies)
        return com_call(
            fm, "FeatureLinearPattern5",
            count1, units.from_mm(spacing1_mm), count2, units.from_mm(spacing2_mm),
            f1, flip2, "NULL", "NULL",
            False, False, False, False, True, True, False, False, False, False, 0.0, 0.0,
            False, False,
        )

    feat = cria(flip1)
    if feat is None and selecao:
        # A direção vem da aresta, e o sentido dela é arbitrário: se as cópias
        # caem fora da peça (abaixo do pé de uma coluna) o SolidWorks recusa
        # sem dizer por quê. Tenta o outro sentido antes de desistir.
        _restore_selection(model, selecao)
        feat = cria(not flip1)
        if feat is not None:
            log.warning("padrão linear só saiu com a direção 1 invertida (flip1=%s)", not flip1)
    return _feature_name(feat, "FeatureLinearPattern5")


def _snapshot_selection(model: Any) -> list[tuple[Any, int]]:
    """(objeto, mark) de cada item selecionado, para refazer a seleção."""
    sm = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    itens = []
    for i in range(1, (com_call(sm, "GetSelectedObjectCount2", -1) or 0) + 1):
        itens.append((com_call(sm, "GetSelectedObject6", i, -1),
                      com_call(sm, "GetSelectedObjectMark", i)))
    return itens


def _restore_selection(model: Any, itens: list[tuple[Any, int]]) -> None:
    sm = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    com_call(model, "ClearSelection2", True)
    for obj, mark in itens:
        try:
            sd = cast_to(com_call(sm, "CreateSelectData"), "ISelectData")
            sd.Mark = mark
            com_call(cast_to(obj, "IEntity"), "Select4", True, sd)
        except (ComCallError, AttributeError):   # feature não é IEntity
            com_call(cast_to(obj, "IFeature"), "Select2", True, mark)


def _solid_volume_mm3(app: Any) -> float:
    part = cast_to(_active_doc(app), "IPartDoc")
    return sum(com_call(cast_to(b, "IBody2"), "GetMassProperties", 1.0)[3] * 1e9
               for b in com_call(part, "GetBodies2", 0, True) or [])


def _selected_features(model: Any, mark: int) -> list[Any]:
    sm = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    feats = []
    for i in range(1, (com_call(sm, "GetSelectedObjectCount2", -1) or 0) + 1):
        if com_call(sm, "GetSelectedObjectMark", i) != mark:
            continue
        obj = com_call(sm, "GetSelectedObject6", i, -1)
        try:
            feats.append(cast_to(obj, "IFeature"))
        except Exception:  # noqa: BLE001 — item com a marca que não é feature
            continue
    return feats


def _seed_effect_mm3(app: Any, model: Any, seeds: list[Any]) -> float:
    """Quanto as features-semente mudam o volume: suprime, mede, devolve.

    Negativo para corte, positivo para ressalto. É a régua para conferir o
    padrão: cada instância tem que mudar o volume o mesmo tanto.
    """
    com_call(model, "EditRebuild3")
    com_volume = _solid_volume_mm3(app)
    for f in seeds:
        com_call(f, "SetSuppression2", 0, 2, None)
    try:
        com_call(model, "EditRebuild3")
        sem_volume = _solid_volume_mm3(app)
    finally:
        for f in seeds:
            com_call(f, "SetSuppression2", 1, 2, None)
        com_call(model, "EditRebuild3")
    return com_volume - sem_volume


def circular_pattern(app: Any, count: int, angle_deg: float = 360.0,
                     equal_spacing: bool = True, flip: bool = False,
                     features: list[str] | None = None,
                     axis_edge_center_mm: list[float] | None = None,
                     axis_edge_diameter_mm: float = 0.0,
                     check_tolerance_pct: float = 5.0) -> dict[str, Any]:
    """Padrão circular das features-semente, CONFERIDO pelo volume.

    Seleção: features= (nomes) e axis_edge_* (aresta circular, casada pela
    geometria) montam a seleção aqui; sem eles vale a seleção prévia
    (features mark=4, eixo mark=1).

    Medido no SW2023 (roda de polo 10006900433): com a FACE cilíndrica do furo
    como eixo, o padrão de 30 saiu com ~3 instâncias e nenhum erro — a
    definição dizia 30. Por isso o efeito de volume da semente é medido antes
    (suprime/mede/volta) e o do padrão depois: instances_measured tem que dar
    count. Diferença maior que check_tolerance_pct volta ok=False — instâncias
    que se sobrepõem ou saem da peça também dão isso, e aí é para olhar.
    """
    model = _model(_active_doc(app))
    sm = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    if features or axis_edge_center_mm:
        if not (features and axis_edge_center_mm and axis_edge_diameter_mm > 0):
            raise ComCallError("circular_pattern", (features, axis_edge_center_mm), None,
                               "passe features E axis_edge_center_mm/axis_edge_diameter_mm "
                               "juntos (ou nenhum, usando a seleção prévia)")
        from swmcp.com.wrappers import holes
        aresta = holes._find_circular_edge(app, axis_edge_center_mm, axis_edge_diameter_mm,
                                           holes.EDGE_MATCH_TOLERANCE_MM)
        if aresta is None:
            raise ComCallError("circular_pattern", (axis_edge_center_mm, axis_edge_diameter_mm),
                               None, "nenhuma aresta circular com esse centro e diâmetro "
                                     "(use list_circular_edges)")
        seeds = [_feature_by_name(model, n) for n in features]
    else:
        seeds = _selected_features(model, 4)
        if not seeds:
            raise ComCallError("circular_pattern", (), None,
                               "nenhuma feature selecionada com mark=4 — ou passe features=")
        selecao = _snapshot_selection(model)

    efeito_semente = _seed_effect_mm3(app, model, seeds)
    volume_antes = _solid_volume_mm3(app)

    com_call(model, "ClearSelection2", True)
    if features:
        for f in seeds:
            com_call(f, "Select2", True, 4)
        sd = cast_to(com_call(sm, "CreateSelectData"), "ISelectData")
        sd.Mark = 1
        com_call(cast_to(aresta, "IEntity"), "Select4", True, sd)
    else:
        _restore_selection(model, selecao)

    fm = com_get(model, "FeatureManager")
    # (Number, Spacing, FlipDirection, DName, GeometryPattern, EqualSpacing,
    #  VaryInstance, SyncSubAssemblies, BDir2, BSymmetric, Number2, Spacing2,
    #  DName2, EqualSpacing2)
    feat = com_call(
        fm, "FeatureCircularPattern5",
        count, units.from_deg(angle_deg), flip, "NULL", False, equal_spacing,
        False, False, False, False, 1, 0.0, "NULL", False,
    )
    nome = _feature_name(feat, "FeatureCircularPattern5")
    com_call(model, "EditRebuild3")
    efeito_padrao = _solid_volume_mm3(app) - volume_antes

    resultado: dict[str, Any] = {"feature": nome, "instances_expected": count,
                                 "seed_volume_effect_mm3": round(efeito_semente, 3),
                                 "pattern_volume_effect_mm3": round(efeito_padrao, 3)}
    if abs(efeito_semente) < 1e-3:
        resultado.update(ok=None, warning="a semente não muda o volume — não dá para conferir")
        return resultado
    medidas = 1 + efeito_padrao / efeito_semente
    resultado["instances_measured"] = round(medidas, 2)
    desvio = abs(medidas - count) / count * 100.0
    resultado["ok"] = desvio <= check_tolerance_pct
    if not resultado["ok"]:
        resultado["warning"] = (
            f"o volume mudou como {medidas:.1f} instâncias, não {count} — eixo errado "
            "(use a ARESTA circular em axis_edge_*), instâncias fora da peça ou sobrepostas; "
            "confira com screenshot antes de seguir")
        log.warning("padrão circular %s: %s", nome, resultado["warning"])
    return resultado


def mirror_feature(app: Any) -> str:
    """Espelha as features selecionadas (mark=1) pelo plano selecionado (mark=2)."""
    fm = com_get(_model(_active_doc(app)), "FeatureManager")
    feat = com_call(fm, "InsertMirrorFeature2", False, False, False, False,
                    swconst().swFeatureScope_AllBodies)
    return _feature_name(feat, "InsertMirrorFeature2")


def sweep(app: Any, cut: bool = False) -> str:
    """Varredura: perfil selecionado com mark=1 e caminho com mark=4."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    c = swconst()
    data = com_call(fm, "CreateDefinition",
                    c.swFmSweepCut if cut else c.swFmSweep)
    if data is None:
        raise ComCallError("CreateDefinition", ("sweep",), None, "definição de sweep indisponível")
    feat = com_call(fm, "CreateFeature", data)
    return _feature_name(feat, "CreateFeature(sweep)")


def loft(app: Any, cut: bool = False) -> str:
    """Loft entre perfis selecionados (todos com mark=1, na ordem)."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    # (Closed, KeepTangency, ForceNonRational, TessToleranceFactor,
    #  StartMatchingType, EndMatchingType, StartTangentLength, EndTangentLength,
    #  StartTangentDir, EndTangentDir, IsThinBody, Thickness1, Thickness2,
    #  ThinType, Merge, UseFeatScope, UseAutoSelect, GuideCurveInfluence)
    if cut:
        feat = com_call(fm, "InsertCutBlend2",
                        False, True, False, 1.0, 0, 0, 1.0, 1.0, True, True,
                        False, 0.0, 0.0, 0, True, True, True, 0)
    else:
        feat = com_call(fm, "InsertProtrusionBlend2",
                        False, True, False, 1.0, 0, 0, 1.0, 1.0, True, True,
                        False, 0.0, 0.0, 0, True, True, True, 0)
    if feat is None:
        raise ComCallError("InsertBlend2", (), None,
                           "loft não criado — os perfis estão selecionados (mark=1) na ordem?")
    last = cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature")
    return com_call(last, "Name")


def rename_feature(app: Any, old_name: str, new_name: str) -> None:
    model = _model(_active_doc(app))
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        if com_call(feat, "Name") == old_name:
            feat.Name = new_name
            return
        raw = com_call(feat, "GetNextFeature")
    raise ComCallError("rename_feature", (old_name,), None, "feature não encontrada")


def undo(app: Any) -> bool:
    return bool(com_call(_model(_active_doc(app)), "EditUndo2", 1))


def rebuild(app: Any) -> bool:
    """Reconstrói o documento ativo (EditRebuild3)."""
    return bool(com_call(_model(_active_doc(app)), "EditRebuild3"))


def zoom_to_fit(app: Any) -> None:
    com_call(_model(_active_doc(app)), "ViewZoomtofit2")


def list_planes(app: Any) -> list[str]:
    """Nomes dos planos de referência do documento ativo (na língua da UI)."""
    model = _model(_active_doc(app))
    planes = []
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        if com_call(feat, "GetTypeName2") == "RefPlane":
            planes.append(com_call(feat, "Name"))
        raw = com_call(feat, "GetNextFeature")
    return planes
