"""Edição de perfil torneado (escrita): canal de alívio U1, recotagem limpa,
remover/mover chanfro de canto e volume teórico do perfil. Thread STA.

Nasceu do detalhe U1 do 3-50200-92000, que por script levou muitas voltas:
- CreateArc às vezes sai com o arco MAIOR (o sentido depende da ordem das
  pontas) — aqui todo arco é conferido pelo comprimento e refeito ao contrário;
- linha criada com inferência "gruda" num ponto do arco vizinho — tudo sai
  com AddToDB e as relações são postas explicitamente;
- cotagens repetidas acumulam cotas (chegou a 209 relações) e o esboço fica
  sub/sobredefinido sem explicação: sketch_redefine apaga TUDO, põe só as
  relações de forma (H/V e tangência onde a geometria é tangente de fato) e
  cota uma vez;
- a conferência de volume pelo perfil (Pappus) é o que pegou o arco errado.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers import holes, modeling
from swmcp.com.wrappers import sketch_define as sd
from swmcp.com.wrappers import sketch_edit as se
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.domain import profile, undercut

log = logging.getLogger(__name__)

TOL_MM = 1e-3
FULLY_CONSTRAINED = 3


# ------------------------------------------------------------ utilitários

def create_minor_arc(model: Any, center: tuple[float, float], start: tuple[float, float],
                     end: tuple[float, float]) -> Any:
    """Arco de start a end pelo lado CURTO. CreateArc às vezes dá o maior: o
    comprimento é conferido e o arco refeito no outro sentido."""
    skm = se._skm(model)
    r = math.dist(center, start)
    m = units.from_mm
    for a, b, sentido in ((start, end, 1), (start, end, -1), (end, start, 1), (end, start, -1)):
        seg = com_call(skm, "CreateArc", m(center[0]), m(center[1]), 0.0,
                       m(a[0]), m(a[1]), 0.0, m(b[0]), m(b[1]), 0.0, sentido)
        if seg is None:
            continue
        if units.to_mm(com_call(cast_to(seg, "ISketchSegment"), "GetLength")) <= math.pi * r + TOL_MM:
            return cast_to(seg, "ISketchSegment")
        se._select(model, seg)
        com_call(model, "EditDelete")
    raise ComCallError("CreateArc", (center, start, end), None, "arco curto não criado")


def _subfeatures(feat: Any) -> list[Any]:
    saida = []
    raw = com_call(feat, "GetFirstSubFeature")
    while raw is not None:
        saida.append(raw)
        raw = com_call(cast_to(raw, "IFeature"), "GetNextSubFeature")
    return saida


def _sketch_feature(model: Any, nome: str) -> Any:
    return modeling._feature_by_name(model, nome)


def _open_sketch_name(model: Any) -> str:
    """Nome do esboço ABERTO. Não é a última feature da árvore: esboço reaberto
    dentro de uma revolução daria "Revolução1" (e a limpeza apagaria as cotas
    erradas). Acha a ProfileFeature cujo ISketch é o ativo, por identidade COM."""
    ativo = com_get(se._skm(model), "ActiveSketch")
    if ativo is None:
        raise ComCallError("_open_sketch_name", (), None, "não há esboço aberto")
    alvo = ativo._oleobj_
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        for f in (feat, *(cast_to(s, "IFeature") for s in _subfeatures(feat))):
            if com_call(f, "GetTypeName2") == "ProfileFeature":
                sk = com_call(f, "GetSpecificFeature2")
                if sk is not None and sk._oleobj_ == alvo:
                    return com_call(f, "Name")
        raw = com_call(feat, "GetNextFeature")
    # esboço recém-criado (ainda não tem feature pai): é a última da árvore
    return com_call(cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature"), "Name")


# --------------------------------------------------------------- canal U1

def sketch_relief_groove(app: Any, corner_mm: list[float], depth_mm: float, height_mm: float,
                         radius_mm: float) -> dict[str, Any]:
    """Canal de alívio U1 no canto parede × ressalto do esboço ABERTO.

    Raio R tangente ao ressalto e ao fundo, fundo a depth_mm dentro da
    parede e entrada em arco R tangente ao fundo, cortando a parede a
    height_mm do ressalto. As linhas do canto são encurtadas (não
    recriadas); os arcos saem pelo lado curto, conferidos.
    """
    model = _model(_active_doc(app))
    sketch = se._active_sketch(model)
    canto = (float(corner_mm[0]), float(corner_mm[1]))
    centro = next((ln for ln in se._lines(sketch) if ln["construction"]), None)
    if centro is None:
        raise ComCallError("relief_groove", canto, None, "o esboço não tem linha de centro (eixo)")
    eixo = se._unit(centro["b"][0] - centro["a"][0], centro["b"][1] - centro["a"][1])
    l1, l2 = se._corner_lines(sketch, canto)

    def direcao(ln: dict[str, Any]) -> tuple[float, float]:
        outro = ln["b"] if se._near(ln["a"], canto) else ln["a"]
        return se._unit(outro[0] - canto[0], outro[1] - canto[1])

    d1, d2 = direcao(l1), direcao(l2)
    par1 = abs(d1[0] * eixo[0] + d1[1] * eixo[1]) > 0.999
    par2 = abs(d2[0] * eixo[0] + d2[1] * eixo[1]) > 0.999
    if par1 == par2:
        raise ComCallError("relief_groove", canto, None,
                           "no canto uma linha tem de ser a parede (paralela ao eixo) e a outra o ressalto")
    parede, ress = (l1, l2) if par1 else (l2, l1)
    u = d1 if par1 else d2
    v = d2 if par1 else d1
    n = (-v[0], -v[1])
    try:
        g = undercut.relief_groove(canto, u, n, float(depth_mm), float(height_mm), float(radius_mm))
    except ValueError as exc:
        raise ComCallError("relief_groove", (canto, depth_mm, height_mm, radius_mm), None, str(exc)) from exc

    def P(su: float, sn: float) -> tuple[float, float]:
        return canto[0] + u[0] * su + n[0] * sn, canto[1] + u[1] * su + n[1] * sn

    c = swconst()
    antes = se._dims_snapshot(model)
    entrada_manual = com_call(app, "GetUserPreferenceToggle", c.swInputDimValOnCreate)
    com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, False)
    skm = se._skm(model)
    add_db = com_get(skm, "AddToDB")
    try:
        ordem = sorted(((ress, g.shoulder), (parede, g.wall)),
                       key=lambda item: 0 if se._near(item[0]["b"], canto) else 1)
        feito = False
        for ln, alvo in ordem:
            atual = se._line_at(sketch, ln["a"], ln["b"])
            se._shorten_line(model, sketch, atual, canto, alvo, feito)
            feito = True
        skm.AddToDB = True
        skm.DisplayWhenAdded = False
        com_call(model, "ClearSelection2", True)
        pe = create_minor_arc(model, g.foot_center, g.shoulder, g.floor_start)
        m = units.from_mm
        fundo = com_call(skm, "CreateLine", m(g.floor_start[0]), m(g.floor_start[1]), 0.0,
                         m(g.floor_end[0]), m(g.floor_end[1]), 0.0)
        entrada = create_minor_arc(model, g.entry_center, g.floor_end, g.wall)
        if fundo is None:
            raise ComCallError("CreateLine", canto, None, "fundo do canal não criado")
        skm.AddToDB = add_db
        skm.DisplayWhenAdded = True
        fundo = cast_to(fundo, "ISketchSegment")
        ress_seg = se._line_at(sketch, *se._endpoints_after(sketch, ress, canto, g.shoulder))["seg"]
        par_seg = se._line_at(sketch, *se._endpoints_after(sketch, parede, canto, g.wall))["seg"]
        for objs, rel in (((fundo, par_seg), "sgPARALLEL"), ((pe, fundo), "sgTANGENT"),
                          ((pe, ress_seg), "sgTANGENT"), ((entrada, fundo), "sgTANGENT")):
            se._select(model, *objs)
            com_call(model, "SketchAddConstraints", rel)
        r = float(radius_mm)
        criadas = []
        for rotulo, objs, pos in (
            ("R pé", (pe,), P(r / 2, depth_mm - 3 * r)),
            ("R entrada", (entrada,), P(height_mm, depth_mm + 2 * r)),
            ("profundidade", (fundo, par_seg), P(height_mm / 2, depth_mm + 3 * r)),
            ("altura", (se._end_point_at(sketch, g.wall), ress_seg), P(height_mm / 2, depth_mm + 5 * r)),
        ):
            try:
                d = se._add_dim(model, pos[0], pos[1], *objs)
                criadas.append({"kind": rotulo, "value_mm": round(units.to_mm(com_get(d, "SystemValue")), 4)})
            except ComCallError as exc:
                criadas.append({"kind": rotulo, "error": str(exc)[:120]})
        com_call(model, "ClearSelection2", True)
    finally:
        skm.AddToDB = add_db
        skm.DisplayWhenAdded = True
        com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, entrada_manual)
    depois = se._dims_snapshot(model)
    estado = com_call(sketch, "GetConstrainedStatus")
    return {"corner_mm": list(canto),
            "points_mm": {k: [round(x, 4) for x in getattr(g, k)]
                          for k in ("shoulder", "floor_start", "floor_end", "wall")},
            "dimensions": criadas, "lost_dimensions": [antes[k] for k in antes if k not in depois],
            "sketch_status": estado, "fully_defined": estado == FULLY_CONSTRAINED}


# ------------------------------------------------------- recotagem limpa

def _segments(sketch: Any) -> list[dict[str, Any]]:
    saida = []
    for raw in com_call(sketch, "GetSketchSegments") or []:
        seg = cast_to(raw, "ISketchSegment")
        tipo = com_call(seg, "GetType")
        if tipo not in (0, 1):
            continue
        g = cast_to(raw, "ISketchLine" if tipo == 0 else "ISketchArc")
        p1 = cast_to(com_call(g, "GetStartPoint2"), "ISketchPoint")
        p2 = cast_to(com_call(g, "GetEndPoint2"), "ISketchPoint")
        item = {"seg": seg, "type": "line" if tipo == 0 else "arc", "a": se._xy(p1), "b": se._xy(p2),
                "construction": bool(com_get(seg, "ConstructionGeometry"))}
        if tipo == 1:
            item["center"] = se._xy(cast_to(com_call(g, "GetCenterPoint2"), "ISketchPoint"))
            item["ccw"] = com_call(g, "GetRotationDir") == 1
        saida.append(item)
    return saida


def _clear_all(model: Any, nome: str) -> dict[str, int]:
    """Apaga TODAS as cotas (pelo nome completo) e relações do esboço aberto.

    Esboço absorvido por uma feature (revolução, extrusão) pendura as cotas
    na FEATURE, não no esboço — por isso a busca varre a árvore toda e fica
    com as cotas cujo nome completo é "Dn@<esboço>@...". Sem isso a limpeza
    não achava nada e cada recotagem empilhava mais cotas (26 para 8 linhas).
    """
    nomes: list[str] = []
    marca = f"@{nome}@"
    raw_feat = com_call(model, "FirstFeature")
    while raw_feat is not None:
        feat = cast_to(raw_feat, "IFeature")
        for f in (feat, *(cast_to(s, "IFeature") for s in _subfeatures(feat))):
            raw = com_call(f, "GetFirstDisplayDimension")
            while raw is not None:
                d = cast_to(com_call(cast_to(raw, "IDisplayDimension"), "GetDimension2", 0), "IDimension")
                cheio = com_get(d, "FullName")
                if marca in cheio and cheio not in nomes:
                    nomes.append(cheio)
                raw = com_call(f, "GetNextDisplayDimension", raw)
        raw_feat = com_call(feat, "GetNextFeature")
    ext = com_get(model, "Extension")
    cotas = 0
    for n in nomes:
        com_call(model, "ClearSelection2", True)
        if com_call(ext, "SelectByID2", n, "DIMENSION", 0.0, 0.0, 0.0, False, 0, None, 0):
            com_call(model, "EditDelete")
            cotas += 1
    sketch = se._active_sketch(model)
    rm = cast_to(com_call(sketch, "RelationManager"), "ISketchRelationManager")
    c = swconst()
    tipo_ponto = getattr(c, "swSketchRelationEntityType_Point", None)
    rels, mantidas = 0, 0
    for r in list(com_call(rm, "GetRelations", 0) or []):
        rel = cast_to(r, "ISketchRelation")
        # coincidência PONTO-PONTO é topologia (liga as pontas do contorno), não
        # amarração: apagá-la solta o contorno e o esboço fica sub-definido sem
        # nenhuma entidade "solta" para mostrar
        if com_call(rel, "GetRelationType") in (c.swConstraintType_COINCIDENT, c.swConstraintType_MERGEPOINTS):
            tipos = list(com_call(rel, "GetEntitiesType") or [])
            if tipo_ponto is not None and tipos and all(t == tipo_ponto for t in tipos):
                mantidas += 1
                continue
        if com_call(rm, "DeleteRelation", r):
            rels += 1
    com_call(model, "ClearSelection2", True)
    return {"dimensions": cotas, "relations": rels, "kept_point_coincident": mantidas}


def _tangent(arc: dict[str, Any], line: dict[str, Any]) -> bool:
    """A linha é tangente ao arco na ponta que compartilham (raio ⟂ linha)?"""
    for pa in (arc["a"], arc["b"]):
        for pl in (line["a"], line["b"]):
            if math.dist(pa, pl) < TOL_MM:
                rx, ry = pa[0] - arc["center"][0], pa[1] - arc["center"][1]
                lx, ly = line["b"][0] - line["a"][0], line["b"][1] - line["a"][1]
                nr, nl = math.hypot(rx, ry), math.hypot(lx, ly)
                return nr > 0 and nl > 0 and abs(rx * lx + ry * ly) / (nr * nl) < 1e-4
    return False


def sketch_redefine(app: Any, sketch_name: str = "") -> dict[str, Any]:
    """Recota um esboço DO ZERO: apaga todas as cotas e relações, põe só as de
    forma (horizontal/vertical, tangência onde a geometria é tangente, linha
    de centro presa na origem) e cota uma vez até ficar totalmente definido.

    É o remédio para esboço que acumulou cotas de várias tentativas e ficou
    sub/sobredefinido sem explicação. A geometria não muda — só a amarração.
    """
    model = _model(_active_doc(app))
    abriu = False
    if sketch_name:
        modeling.edit_sketch(app, sketch_name)
        abriu = True
    nome = sketch_name or _open_sketch_name(model)
    try:
        limpeza = _clear_all(model, nome)
        sketch = se._active_sketch(model)
        forma = 0
        segs = _segments(sketch)
        for s in segs:
            if s["type"] != "line":
                continue
            if abs(s["a"][1] - s["b"][1]) < 1e-6:
                se._select(model, s["seg"]); com_call(model, "SketchAddConstraints", "sgHORIZONTAL2D"); forma += 1
            elif abs(s["a"][0] - s["b"][0]) < 1e-6:
                se._select(model, s["seg"]); com_call(model, "SketchAddConstraints", "sgVERTICAL2D"); forma += 1
        for arco in (s for s in _segments(sketch) if s["type"] == "arc"):
            for ln in (s for s in _segments(sketch) if s["type"] == "line" and not s["construction"]):
                if _tangent(arco, ln):
                    se._select(model, arco["seg"], ln["seg"])
                    com_call(model, "SketchAddConstraints", "sgTANGENT")
                    forma += 1
        eixo = next((s for s in _segments(sketch) if s["type"] == "line" and s["construction"]), None)
        if eixo is not None:
            ax, ay = eixo["a"]; bx, by = eixo["b"]
            dist_origem = abs((bx - ax) * ay - (by - ay) * ax) / max(math.hypot(bx - ax, by - ay), 1e-9)
            if dist_origem < TOL_MM:
                com_call(model, "ClearSelection2", True)
                com_call(com_get(model, "Extension"), "SelectByID2", "", "EXTSKETCHPOINT",
                         0.0, 0.0, 0.0, False, 0, None, 0)
                com_call(eixo["seg"], "Select4", True, None)
                com_call(model, "SketchAddConstraints", "sgCOINCIDENT")
                forma += 1
        com_call(model, "ClearSelection2", True)
        estado_forma = com_call(se._active_sketch(model), "GetConstrainedStatus")
        definicao = sd.fully_define_sketch(app)
    finally:
        if abriu:
            modeling.exit_sketch(app)
            com_call(model, "ForceRebuild3", False)
    return {"sketch": nome, "cleared": limpeza, "shape_relations": forma,
            "status_after_relations": estado_forma, "dimensions": len(definicao.get("dimensions", [])),
            "status": definicao["status"], "fully_defined": definicao["fully_defined"]}


# ------------------------------------------------------ chanfro de canto

def _line_intersection(p1: tuple[float, float], p2: tuple[float, float],
                       q1: tuple[float, float], q2: tuple[float, float]) -> tuple[float, float]:
    d1 = (p2[0] - p1[0], p2[1] - p1[1]); d2 = (q2[0] - q1[0], q2[1] - q1[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12:
        raise ComCallError("chanfro", (p1, q1), None, "as linhas vizinhas do chanfro são paralelas")
    t = ((q1[0] - p1[0]) * d2[1] - (q1[1] - p1[1]) * d2[0]) / den
    return p1[0] + t * d1[0], p1[1] + t * d1[1]


def remove_sketch_chamfer(app: Any, from_mm: list[float], to_mm: list[float]) -> dict[str, Any]:
    """Tira o chanfro (a linha de from_mm a to_mm) do esboço ABERTO e devolve o
    canto vivo, prolongando as duas linhas vizinhas até se encontrarem.

    Se as cotas prendem as pontas, o esboço é limpo e recotado do zero
    (sketch_redefine) — o retorno diz se isso aconteceu.
    """
    model = _model(_active_doc(app))
    sketch = se._active_sketch(model)
    a, b = (float(from_mm[0]), float(from_mm[1])), (float(to_mm[0]), float(to_mm[1]))
    linhas = [ln for ln in se._lines(sketch) if not ln["construction"]]
    chanfro = next((ln for ln in linhas if (se._near(ln["a"], a) and se._near(ln["b"], b))
                    or (se._near(ln["a"], b) and se._near(ln["b"], a))), None)
    if chanfro is None:
        raise ComCallError("remove_sketch_chamfer", (a, b), None, "não há linha entre esses dois pontos")

    def vizinha(p: tuple[float, float]) -> dict[str, Any]:
        cands = [ln for ln in linhas if ln is not chanfro and (se._near(ln["a"], p) or se._near(ln["b"], p))]
        if len(cands) != 1:
            raise ComCallError("remove_sketch_chamfer", p, None, f"{len(cands)} linhas chegam em {p}")
        return cands[0]

    va, vb = vizinha(a), vizinha(b)
    canto = _line_intersection(va["a"], va["b"], vb["a"], vb["b"])
    se._select(model, chanfro["seg"])
    com_call(model, "EditDelete")
    nome = _open_sketch_name(model)

    def mover() -> bool:
        ok = True
        for p in (a, b):
            ponto = se._end_point_at(se._active_sketch(model), p)
            com_call(ponto, "SetCoords", units.from_mm(canto[0]), units.from_mm(canto[1]), 0.0)
        for p in (a, b):
            try:
                se._end_point_at(se._active_sketch(model), p)
                ok = False           # ainda há ponta no lugar antigo: a cota segurou
            except ComCallError:
                pass
        return ok

    recotado = False
    if not mover():
        _clear_all(model, nome)
        recotado = True
        if not mover():
            raise ComCallError("remove_sketch_chamfer", (a, b), None, "as pontas não foram para o canto")
    pontos = [cast_to(p, "ISketchPoint") for p in com_call(se._active_sketch(model), "GetSketchPoints2") or []]
    no_canto = [p for p in pontos if math.dist(se._xy(p), canto) < TOL_MM]
    if len(no_canto) >= 2:
        # sgMERGEPOINTS não une nada por API (medido no SW2023): coincidência explícita
        se._select(model, no_canto[0], no_canto[1])
        com_call(model, "SketchAddConstraints", "sgCOINCIDENT")
    com_call(model, "ClearSelection2", True)
    redefinicao = sketch_redefine(app) if recotado else None
    return {"corner_mm": [round(v, 4) for v in canto], "redefined": recotado,
            "redefine": redefinicao,
            "sketch_status": com_call(se._active_sketch(model), "GetConstrainedStatus")}


def move_sketch_chamfer(app: Any, from_mm: list[float], to_mm: list[float], new_corner_mm: list[float],
                        new_from_mm: list[float], new_to_mm: list[float]) -> dict[str, Any]:
    """Tira o chanfro (from→to) e põe outro no canto new_corner_mm, com as
    pontas EXATAS new_from_mm/new_to_mm (é assim que o desenho cota: 2,5
    axial × 0,91 radial) — sem depender de qual distância o SolidWorks aplica
    em qual linha."""
    removido = remove_sketch_chamfer(app, from_mm, to_mm)
    canto = (float(new_corner_mm[0]), float(new_corner_mm[1]))
    pa, pb = tuple(map(float, new_from_mm)), tuple(map(float, new_to_mm))
    da, db = math.dist(canto, pa), math.dist(canto, pb)
    model = _model(_active_doc(app))
    for d1, d2 in ((da, db), (db, da)):
        r = se.sketch_corner_chamfer(app, list(canto), d1, d2)
        feito = {tuple(round(v, 3) for v in r["chamfer_from_mm"]), tuple(round(v, 3) for v in r["chamfer_to_mm"])}
        if feito == {tuple(round(v, 3) for v in pa), tuple(round(v, 3) for v in pb)}:
            return {"removed": removido, "chamfer": r}
        com_call(model, "EditUndo2", 1)
    raise ComCallError("move_sketch_chamfer", (new_from_mm, new_to_mm), None,
                       "o chanfro novo não saiu com as pontas pedidas")


# ---------------------------------------------------- volume do perfil

def profile_volume(app: Any, sketch_name: str) -> dict[str, Any]:
    """Volume teórico do sólido de revolução do perfil (Pappus, com arcos) e o
    volume atual do corpo. Compare antes/depois de editar o perfil: a
    variação do corpo tem que bater com a do perfil."""
    model = _model(_active_doc(app))
    feat = _sketch_feature(model, sketch_name)
    sketch = cast_to(com_call(feat, "GetSpecificFeature2"), "ISketch")
    segs = _segments(sketch)
    eixo = next((s for s in segs if s["type"] == "line" and s["construction"]), None)
    if eixo is None:
        raise ComCallError("profile_volume", (sketch_name,), None, "o esboço não tem linha de centro")
    partes = [profile.Segment(s["a"], s["b"], s.get("center"), s.get("ccw", True))
              for s in segs if not s["construction"]]
    try:
        contorno = profile.chain(partes)
    except ValueError as exc:
        raise ComCallError("profile_volume", (sketch_name,), None, str(exc)) from exc
    v = profile.revolved_volume(contorno, eixo["a"], (eixo["b"][0] - eixo["a"][0], eixo["b"][1] - eixo["a"][1]))
    arcos_maiores = [{"center_mm": [round(x, 4) for x in s["center"]],
                      "length_mm": round(profile.arc_length(profile.Segment(s["a"], s["b"], s["center"], s["ccw"])), 4)}
                     for s in segs if s["type"] == "arc"
                     and profile.arc_length(profile.Segment(s["a"], s["b"], s["center"], s["ccw"]))
                     > math.pi * math.dist(s["center"], s["a"]) + TOL_MM]
    return {"sketch": sketch_name, "profile_volume_mm3": round(v, 3),
            "body_volume_mm3": round(holes._volume_mm3(app), 3),
            "major_arcs": arcos_maiores}
