"""Edição de canto num esboço existente: chanfro, filete e alívio DIN 509.

Tudo aqui trabalha no esboço ABERTO, localizando o canto pela coordenada em
vez de exigir um clique. O ponto de partida é um perfil já cotado — o de uma
peça torneada, por exemplo — e a regra é não perder o que já está lá: as
linhas originais são mantidas (encurtadas), não apagadas, para as cotas e
tolerâncias penduradas nelas sobreviverem.

Como encurtar uma linha sem perder a identidade (medido no SW2023):
- SplitOpenSegment divide a linha e a IDENTIDADE fica com o pedaço que
  contém o ponto INICIAL; as cotas vão com ela. Então, se o canto está no
  fim da linha, dividir e apagar o pedaço do canto preserva tudo;
- se o canto está no INÍCIO, apagar o pedaço do canto apagaria a linha
  original. Nesse caso o ponto inicial é simplesmente movido (SetCoords) —
  o que só é seguro depois de a outra linha do canto ter sido encurtada,
  porque até então o ponto é compartilhado pelas duas;
- SketchTrim "mais próximo" (opção 3) apaga ora um lado, ora o outro,
  conforme o ponto clicado coincide ou não com uma interseção — por isso
  não é usado.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers import dimensions as dims
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.domain import undercut

log = logging.getLogger(__name__)

TOL_MM = 1e-3
FULLY_CONSTRAINED = 3



# ----------------------------------------------------------------- leitura

def _skm(model: Any) -> Any:
    return cast_to(com_get(model, "SketchManager"), "ISketchManager")


def _active_sketch(model: Any) -> Any:
    sk = com_get(_skm(model), "ActiveSketch")
    if sk is None:
        raise ComCallError("ActiveSketch", (), None, "não há esboço aberto — use edit_sketch antes")
    return cast_to(sk, "ISketch")


def _xy(p: Any) -> tuple[float, float]:
    return units.to_mm(com_get(p, "X")), units.to_mm(com_get(p, "Y"))


def _near(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) < TOL_MM and abs(a[1] - b[1]) < TOL_MM


def _lines(sketch: Any) -> list[dict[str, Any]]:
    """Linhas do esboço com endpoints (objetos vivos — releia após cada edição)."""
    saida = []
    for raw in com_call(sketch, "GetSketchSegments") or []:
        seg = cast_to(raw, "ISketchSegment")
        if com_call(seg, "GetType") != 0:
            continue
        linha = cast_to(raw, "ISketchLine")
        p1 = cast_to(com_call(linha, "GetStartPoint2"), "ISketchPoint")
        p2 = cast_to(com_call(linha, "GetEndPoint2"), "ISketchPoint")
        saida.append({"seg": seg, "p1": p1, "p2": p2, "a": _xy(p1), "b": _xy(p2),
                      "construction": bool(com_get(seg, "ConstructionGeometry"))})
    return saida


def _corner_lines(sketch: Any, corner: tuple[float, float]) -> list[dict[str, Any]]:
    achadas = [ln for ln in _lines(sketch) if not ln["construction"]
               and (_near(ln["a"], corner) or _near(ln["b"], corner))]
    if len(achadas) != 2:
        raise ComCallError("corner", corner, None,
                           f"o canto precisa juntar exatamente 2 linhas; em {corner} há {len(achadas)}")
    return achadas


def _line_at(sketch: Any, a: tuple[float, float], b: tuple[float, float]) -> dict[str, Any]:
    for ln in _lines(sketch):
        if _near(ln["a"], a) and _near(ln["b"], b):
            return ln
    raise ComCallError("_line_at", (a, b), None, "linha não encontrada (o esboço mudou?)")


def _unit(dx: float, dy: float) -> tuple[float, float]:
    n = math.hypot(dx, dy)
    if n < TOL_MM:
        raise ComCallError("_unit", (dx, dy), None, "linha degenerada")
    return dx / n, dy / n


def _select(model: Any, *objs: Any) -> None:
    com_call(model, "ClearSelection2", True)
    for i, o in enumerate(objs):
        if not com_call(o, "Select4", i > 0, None):
            raise ComCallError("Select4", (), None, "entidade do esboço não selecionada")


def _dims_snapshot(model: Any) -> dict[str, dict[str, Any]]:
    """Cotas de todas as features, por nome completo — para saber o que se perdeu."""
    return {d["name"]: d for d in dims.list_dimensions_of(model)}


# ------------------------------------------------------------ chanfro/filete

def sketch_corner_chamfer(app: Any, corner_mm: list[float], distance_mm: float,
                          distance2_mm: float | None = None) -> dict[str, Any]:
    """Chanfro de esboço no canto em corner_mm (distância × distância).

    Usa o chanfro do próprio esboço (CreateChamfer), que encurta as duas linhas
    sem recriá-las — cotas e relações existentes continuam válidas.
    """
    model = _model(_active_doc(app))
    sketch = _active_sketch(model)
    canto = (float(corner_mm[0]), float(corner_mm[1]))
    linhas = _corner_lines(sketch, canto)
    ponto = linhas[0]["p1"] if _near(linhas[0]["a"], canto) else linhas[0]["p2"]
    _select(model, ponto)
    c = swconst()
    d2 = distance_mm if distance2_mm is None else distance2_mm
    tipo = c.swSketchChamfer_DistanceEqual if distance2_mm is None else c.swSketchChamfer_DistanceDistance
    seg = com_call(_skm(model), "CreateChamfer", tipo, units.from_mm(distance_mm), units.from_mm(d2))
    if seg is None:
        raise ComCallError("CreateChamfer", (corner_mm, distance_mm), None, "chanfro de esboço não criado")
    novo = cast_to(seg, "ISketchLine")
    a = _xy(cast_to(com_call(novo, "GetStartPoint2"), "ISketchPoint"))
    b = _xy(cast_to(com_call(novo, "GetEndPoint2"), "ISketchPoint"))
    return {"corner_mm": list(canto), "chamfer_from_mm": [round(v, 4) for v in a],
            "chamfer_to_mm": [round(v, 4) for v in b],
            "sketch_status": com_call(sketch, "GetConstrainedStatus")}


def sketch_corner_fillet(app: Any, corner_mm: list[float], radius_mm: float) -> dict[str, Any]:
    """Filete de esboço no canto em corner_mm (CreateFillet nas duas linhas)."""
    model = _model(_active_doc(app))
    sketch = _active_sketch(model)
    canto = (float(corner_mm[0]), float(corner_mm[1]))
    linhas = _corner_lines(sketch, canto)
    _select(model, linhas[0]["seg"], linhas[1]["seg"])
    seg = com_call(_skm(model), "CreateFillet", units.from_mm(radius_mm),
                   swconst().swConstrainedCornerKeepGeometry)
    if seg is None:
        raise ComCallError("CreateFillet", (corner_mm, radius_mm), None, "filete de esboço não criado")
    arco = cast_to(seg, "ISketchArc")
    centro = _xy(cast_to(com_call(arco, "GetCenterPoint2"), "ISketchPoint"))
    return {"corner_mm": list(canto), "radius_mm": radius_mm,
            "center_mm": [round(v, 4) for v in centro],
            "sketch_status": com_call(sketch, "GetConstrainedStatus")}


# --------------------------------------------------------------- DIN 509

def _shorten_line(model: Any, sketch: Any, linha: dict[str, Any], corner: tuple[float, float],
                  novo_ponto: tuple[float, float], other_done: bool) -> str:
    """Encurta a linha pelo lado do canto até novo_ponto, preservando a identidade.

    Devolve como foi feito ('split' ou 'moved'). Ver o cabeçalho do módulo.
    """
    skm = _skm(model)
    canto_no_fim = _near(linha["b"], corner)
    if canto_no_fim:
        _select(model, linha["seg"])
        if com_call(skm, "SplitOpenSegment", units.from_mm(novo_ponto[0]), units.from_mm(novo_ponto[1]), 0.0) is None:
            raise ComCallError("SplitOpenSegment", novo_ponto, None, "não dividiu a linha nesse ponto")
        pedaco = _line_at(sketch, novo_ponto, corner)
        _select(model, pedaco["seg"])
        com_call(model, "EditDelete")
        return "split"
    if not other_done:
        raise ComCallError("_shorten_line", corner, None,
                           "canto no início das duas linhas — encurte a outra antes")
    com_call(linha["p1"], "SetCoords", units.from_mm(novo_ponto[0]), units.from_mm(novo_ponto[1]), 0.0)
    return "moved"


def _add_dim(model: Any, x: float, y: float, *objs: Any) -> Any:
    _select(model, *objs)
    raw = com_call(model, "AddDimension2", units.from_mm(x), units.from_mm(y), 0.0)
    if raw is None:
        raise ComCallError("AddDimension2", (x, y), None, "cota do alívio não criada")
    return cast_to(com_call(cast_to(raw, "IDisplayDimension"), "GetDimension2", 0), "IDimension")


def sketch_undercut_din509(app: Any, corner_mm: list[float], radius_mm: float = 0.8,
                           depth_mm: float = 0.3, width_mm: float = 0.0,
                           ramp_angle_deg: float = undercut.RAMP_DEG) -> dict[str, Any]:
    """Alívio DIN 509 forma E no canto interno em corner_mm do esboço aberto.

    O canto junta a linha da superfície cilíndrica (paralela à linha de centro
    do esboço) e a linha do ressalto. O alívio entra na superfície cilíndrica:
    raio r tangente ao ressalto e ao fundo, fundo t abaixo da superfície,
    largura f (padrão da norma para o par r×t) e rampa de
    saída em ramp_angle_deg. Serve para furo (material por fora) e eixo
    (material por dentro): o lado do material é lido das próprias linhas.

    As linhas originais são encurtadas, não recriadas. Cotas que ficavam num
    pedaço apagado são listadas em lost_dimensions para serem refeitas — o
    valor e a tolerância que tinham vêm junto.
    """
    r, t = float(radius_mm), float(depth_mm)
    model = _model(_active_doc(app))
    sketch = _active_sketch(model)
    canto = (float(corner_mm[0]), float(corner_mm[1]))
    c = swconst()

    # eixo: a linha de centro (construção) do esboço
    centro = next((ln for ln in _lines(sketch) if ln["construction"]), None)
    if centro is None:
        raise ComCallError("din509", canto, None, "o esboço não tem linha de centro (eixo da revolução)")
    eixo = _unit(centro["b"][0] - centro["a"][0], centro["b"][1] - centro["a"][1])

    l1, l2 = _corner_lines(sketch, canto)

    def direcao(ln: dict[str, Any]) -> tuple[float, float]:
        outro = ln["b"] if _near(ln["a"], canto) else ln["a"]
        return _unit(outro[0] - canto[0], outro[1] - canto[1])

    d1, d2 = direcao(l1), direcao(l2)
    par1 = abs(d1[0] * eixo[0] + d1[1] * eixo[1]) > 0.999
    par2 = abs(d2[0] * eixo[0] + d2[1] * eixo[1]) > 0.999
    if par1 == par2:
        raise ComCallError("din509", canto, None,
                           "no canto uma linha tem de ser paralela ao eixo (cilindro) e a outra não (ressalto)")
    cil, ress = (l1, l2) if par1 else (l2, l1)
    u = d1 if par1 else d2          # ao longo do cilindro, saindo do canto
    v = d2 if par1 else d1          # ao longo do ressalto, saindo do canto
    n = (-v[0], -v[1])              # para dentro do material
    try:
        geo = undercut.din509_e(canto, u, n, r, t, float(width_mm) or None, ramp_angle_deg)
    except ValueError as exc:
        raise ComCallError("din509", (canto, r, t, width_mm), None, str(exc)) from exc
    f = geo.width
    p_ress, p_fundo1, p_fundo2, p_cil = geo.shoulder, geo.floor_start, geo.floor_end, geo.cylinder
    centro_arco = geo.arc_center

    def P(su: float, sn: float) -> tuple[float, float]:
        return canto[0] + u[0] * su + n[0] * sn, canto[1] + u[1] * su + n[1] * sn

    antes = _dims_snapshot(model)
    entrada_manual = com_call(app, "GetUserPreferenceToggle", c.swInputDimValOnCreate)
    com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, False)
    skm = _skm(model)
    add_db = com_get(skm, "AddToDB")
    modos = {}
    try:
        # 1) encurtar as duas linhas: primeiro a que tem o canto no FIM (split),
        #    depois a outra (ponto movido, já sem compartilhar o canto)
        ordem = sorted(((ress, p_ress, "shoulder"), (cil, p_cil, "cylinder")),
                       key=lambda item: 0 if _near(item[0]["b"], canto) else 1)
        feito = False
        for ln, alvo, rotulo in ordem:
            atual = _line_at(sketch, ln["a"], ln["b"])
            modos[rotulo] = _shorten_line(model, sketch, atual, canto, alvo, feito)
            feito = True

        # 2) os segmentos novos, sem snap (AddToDB) — os endpoints coincidem
        #    exatamente com as pontas encurtadas e o SolidWorks os funde
        skm.AddToDB = True
        skm.DisplayWhenAdded = False
        com_call(model, "ClearSelection2", True)
        m = units.from_mm
        arco = None
        for sentido in (1, -1):   # o sentido que dá o arco CURTO depende da orientação do canto
            arco = com_call(skm, "CreateArc", m(centro_arco[0]), m(centro_arco[1]), 0.0,
                            m(p_ress[0]), m(p_ress[1]), 0.0, m(p_fundo1[0]), m(p_fundo1[1]), 0.0, sentido)
            if arco is None:
                break
            if units.to_mm(com_call(cast_to(arco, "ISketchSegment"), "GetLength")) < math.pi * r:
                break
            _select(model, arco)
            com_call(model, "EditDelete")
            arco = None
        fundo = com_call(skm, "CreateLine", m(p_fundo1[0]), m(p_fundo1[1]), 0.0, m(p_fundo2[0]), m(p_fundo2[1]), 0.0)
        rampa_seg = com_call(skm, "CreateLine", m(p_fundo2[0]), m(p_fundo2[1]), 0.0, m(p_cil[0]), m(p_cil[1]), 0.0)
        if arco is None or fundo is None or rampa_seg is None:
            raise ComCallError("CreateArc/CreateLine", canto, None, "segmento do alívio não criado")
        skm.AddToDB = add_db
        skm.DisplayWhenAdded = True

        # 3) relações e cotas do alívio
        arco = cast_to(arco, "ISketchSegment"); fundo = cast_to(fundo, "ISketchSegment")
        rampa_seg = cast_to(rampa_seg, "ISketchSegment")
        ress_seg = _line_at(sketch, *(_endpoints_after(sketch, ress, canto, p_ress)))["seg"]
        cil_seg = _line_at(sketch, *(_endpoints_after(sketch, cil, canto, p_cil)))["seg"]
        _select(model, fundo, cil_seg); com_call(model, "SketchAddConstraints", "sgPARALLEL")
        _select(model, arco, fundo); com_call(model, "SketchAddConstraints", "sgTANGENT")
        _select(model, arco, ress_seg); com_call(model, "SketchAddConstraints", "sgTANGENT")
        meio = P(f / 2.0, t + 2.0 * r)
        criadas = []
        for rotulo, objs, pos in (
            ("R", (arco,), P(r, t - 3.0 * r)),
            ("t", (fundo, cil_seg), P(f / 2.0, t + r)),
            ("f", (_end_point_at(sketch, p_cil), ress_seg), meio),
            ("angle", (rampa_seg, fundo), P(f, t + r)),
        ):
            d = _add_dim(model, pos[0], pos[1], *objs)
            criadas.append({"kind": rotulo, "name": dims._short_name(com_get(d, "FullName")),
                            "value": round(units.to_deg(com_get(d, "SystemValue")), 4) if rotulo == "angle"
                            else round(units.to_mm(com_get(d, "SystemValue")), 4)})
        com_call(model, "ClearSelection2", True)
    finally:
        skm.AddToDB = add_db
        skm.DisplayWhenAdded = True
        com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, entrada_manual)

    depois = _dims_snapshot(model)
    perdidas = [antes[nome] for nome in antes if nome not in depois]
    estado = com_call(sketch, "GetConstrainedStatus")
    return {"corner_mm": list(canto), "form": f"E{r}x{t}", "width_mm": f,
            "ramp_angle_deg": ramp_angle_deg, "material_side": [round(n[0], 3), round(n[1], 3)],
            "points_mm": {"shoulder": [round(x, 4) for x in p_ress], "floor_start": [round(x, 4) for x in p_fundo1],
                          "floor_end": [round(x, 4) for x in p_fundo2], "cylinder": [round(x, 4) for x in p_cil]},
            "lines": modos, "dimensions": criadas, "lost_dimensions": perdidas,
            "sketch_status": estado, "fully_defined": estado == FULLY_CONSTRAINED}


def _endpoints_after(sketch: Any, ln: dict[str, Any], corner: tuple[float, float],
                     novo: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    """Endpoints que a linha passou a ter depois de encurtada pelo canto."""
    if _near(ln["a"], corner):
        return novo, ln["b"]
    return ln["a"], novo


def _end_point_at(sketch: Any, xy: tuple[float, float]) -> Any:
    for ln in _lines(sketch):
        for chave in ("p1", "p2"):
            if _near(_xy(ln[chave]), xy):
                return ln[chave]
    raise ComCallError("_end_point_at", xy, None, "ponto não encontrado no esboço")
