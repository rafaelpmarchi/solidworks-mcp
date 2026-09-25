"""Referências de montagem: ler mates, achar entidades de componente pela
geometria, replicar um componente com os mesmos mates e substituir arquivo
(escrita). Executa no thread STA.

O que foi medido no SW2023 (montagem da prateleira, porta-etiqueta no rasgo):
- IMateEntity2.EntityParams guarda um ponto QUALQUER do plano/reta infinitos
  (a ponta de um rasgo veio com y=450, 50 mm fora da face) — achar a entidade
  de volta é teste geométrico, com desempate por proximidade
  (domain.entity_match);
- os corpos de IComponent2.GetBodies3 têm a geometria em coordenadas da PEÇA,
  mas as faces/arestas deles selecionam no contexto da montagem — então o
  ponto da montagem é levado para a peça (domain.placement.to_local) antes
  de comparar, e a entidade achada é selecionada direto (IEntity.Select4);
- GetBodies3 devolve (corpos, tipos) em algumas chamadas pelo pywin32.
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers import assembly as asm_w
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.domain import entity_match as em
from swmcp.domain.placement import apply_transform, direction_to_local, to_local

log = logging.getLogger(__name__)

# swSelectType_e — o que IMateEntity2.ReferenceType2 devolve
SEL_EDGES = 1
SEL_FACES = 2
SEL_VERTICES = 3
SEL_DATUMPLANES = 4

KIND_BY_SELTYPE = {SEL_EDGES: "edge", SEL_FACES: "face", SEL_VERTICES: "vertex",
                   SEL_DATUMPLANES: "plane"}
SELTYPE_BY_KIND = {v: k for k, v in KIND_BY_SELTYPE.items()}

ALIGNMENTS = asm_w.ALIGNMENTS

# mates que o replicate sabe refazer (os que só dependem de 2 entidades + valor)
REPLICABLE = {"coincident", "concentric", "perpendicular", "parallel", "tangent",
              "distance", "angle"}

TOL_MM = 0.02


def _mate_type_names() -> dict[int, str]:
    c = swconst()
    return {getattr(c, enum): nome for nome, enum in asm_w.MATE_TYPES.items()}


def _align_names() -> dict[int, str]:
    c = swconst()
    return {getattr(c, enum): nome for nome, enum in ALIGNMENTS.items()}


def _array(comp: Any) -> list[float]:
    xf = com_get(comp, "Transform2")
    if xf is None:
        raise ComCallError("Transform2", (com_get(comp, "Name2"),), None,
                           "componente sem transformada — está suprimido?")
    return list(com_get(cast_to(xf, "IMathTransform"), "ArrayData"))


def _bodies(comp: Any) -> list[Any]:
    r = com_call(comp, "GetBodies3", 0, None)
    if isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], tuple):
        r = r[0]
    return list(r or [])


def _box_center(comp: Any) -> list[float]:
    b = [units.to_mm(v) for v in com_call(comp, "GetBox", False, False)]
    return [(b[i] + b[i + 3]) / 2.0 for i in range(3)]


def _mm3(vals: Any) -> list[float]:
    return [units.to_mm(v) for v in vals[:3]]


# --------------------------------------------------------- achar entidade

def find_entity(comp: Any, kind: str, point_mm: list[float],
                direction: list[float] | None = None, radius_mm: float = 0.0,
                hint_mm: list[float] | None = None, tol_mm: float = TOL_MM) -> Any:
    """Entidade do componente que casa com a geometria dada (montagem, mm).

    kind: face (plana ou cilíndrica), edge (reta ou circular), vertex, plane
    (plano de referência da peça). Com direction o casamento é geométrico
    (plano/reta/eixo); sem direction é "a entidade desse tipo mais perto do
    ponto". radius_mm > 0 exige cilindro/círculo desse raio. Entre várias
    que casam, fica a mais perto de hint_mm (padrão: o próprio ponto).
    """
    arr = _array(comp)
    lp = to_local(arr, point_mm)
    ld = direction_to_local(arr, direction) if direction else None
    lh = to_local(arr, hint_mm or point_mm)
    alvo_h = [units.from_mm(v) for v in lh]
    melhor: tuple[float, Any] | None = None

    def considera(entidade: Any, perto_mm: list[float]) -> None:
        nonlocal melhor
        d = em.distance(perto_mm, lh)
        if melhor is None or d < melhor[0]:
            melhor = (d, entidade)

    if kind == "plane":
        mdl = cast_to(com_call(comp, "GetModelDoc2"), "IModelDoc2")
        raw = com_call(mdl, "FirstFeature")
        while raw is not None:
            feat = cast_to(raw, "IFeature")
            if com_call(feat, "GetTypeName2") == "RefPlane":
                plano = cast_to(com_call(feat, "GetSpecificFeature2"), "IRefPlane")
                t = list(com_get(cast_to(com_get(plano, "Transform"), "IMathTransform"), "ArrayData"))
                origem, normal = [units.to_mm(v) for v in t[9:12]], t[6:9]
                if ld is None or em.same_plane(lp, ld, origem, normal, tol_mm):
                    comp_feat = com_call(comp, "FeatureByName", com_call(feat, "Name"))
                    if comp_feat is not None:
                        considera(comp_feat, lp if ld is not None else origem)
            raw = com_call(feat, "GetNextFeature")
        return None if melhor is None else melhor[1]

    for rb in _bodies(comp):
        body = cast_to(rb, "IBody2")
        if kind == "face":
            for rf in com_call(body, "GetFaces") or []:
                face = cast_to(rf, "IFace2")
                s = cast_to(com_call(face, "GetSurface"), "ISurface")
                if ld is not None:
                    if com_call(s, "IsPlane") and not radius_mm:
                        pp = com_call(s, "PlaneParams")
                        if not em.same_plane(lp, ld, _mm3(pp[3:6]), pp[:3], tol_mm):
                            continue
                    elif radius_mm and com_call(s, "IsCylinder"):
                        # só com raio: sem ele, um ponto no eixo "casaria" o
                        # cilindro quando se pediu a face plana da ponta
                        cp = com_call(s, "CylinderParams")
                        if not em.same_line(lp, ld, _mm3(cp), cp[3:6], tol_mm):
                            continue
                        if abs(units.to_mm(cp[6]) - radius_mm) > tol_mm:
                            continue
                    else:
                        continue
                perto = com_call(face, "GetClosestPointOn", *alvo_h)
                considera(face, _mm3(perto))
        elif kind == "edge":
            for re_ in com_call(body, "GetEdges") or []:
                aresta = cast_to(re_, "IEdge")
                cv = cast_to(com_call(aresta, "GetCurve"), "ICurve")
                if ld is not None:
                    if com_call(cv, "IsLine") and not radius_mm:
                        lpar = com_call(cv, "LineParams")
                        if not em.same_line(lp, ld, _mm3(lpar), lpar[3:6], tol_mm):
                            continue
                    elif radius_mm and com_call(cv, "IsCircle"):
                        cpar = com_call(cv, "CircleParams")
                        if em.distance(lp, _mm3(cpar)) > tol_mm or not em.parallel(ld, cpar[3:6]):
                            continue
                        if abs(units.to_mm(cpar[6]) - radius_mm) > tol_mm:
                            continue
                    else:
                        continue
                perto = com_call(aresta, "GetClosestPointOn", *alvo_h)
                considera(aresta, _mm3(perto))
        elif kind == "vertex":
            vistos = set()
            for re_ in com_call(body, "GetEdges") or []:
                aresta = cast_to(re_, "IEdge")
                for prop in ("GetStartVertex", "GetEndVertex"):
                    v = com_call(aresta, prop)
                    if v is None:
                        continue
                    pt = _mm3(com_call(cast_to(v, "IVertex"), "GetPoint"))
                    chave = tuple(round(x, 4) for x in pt)
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    if em.distance(pt, lp) <= max(tol_mm, 0.1) or ld is None:
                        considera(v, pt)
        else:
            raise ComCallError("find_entity", (kind,), None,
                               "kind deve ser face, edge, vertex ou plane")
    if melhor is None:
        return None
    if ld is None and melhor[0] > max(tol_mm, 0.1) and kind != "vertex":
        return None   # sem direção: só vale entidade passando pelo ponto
    return melhor[1]


def _select_with_mark(app: Any, entidade: Any, append: bool, mark: int) -> bool:
    model = _model(_active_doc(app))
    sm = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    sd = cast_to(com_call(sm, "CreateSelectData"), "ISelectData")
    sd.Mark = mark
    try:
        return bool(com_call(cast_to(entidade, "IEntity"), "Select4", append, sd))
    except (ComCallError, AttributeError):   # plano de referência é IFeature
        return bool(com_call(cast_to(entidade, "IFeature"), "Select2", append, mark))


def select_component_entity(app: Any, component: str, kind: str, point_mm: list[float],
                            direction: list[float] | None = None, radius_mm: float = 0.0,
                            append: bool = False, mark: int = 0,
                            tol_mm: float = 0.1) -> dict[str, Any]:
    """Seleciona face/aresta/vértice/plano de um componente pela geometria."""
    comp = asm_w._find_component(app, component)
    ent = find_entity(comp, kind, point_mm, direction, radius_mm, None, tol_mm)
    if ent is None:
        raise ComCallError("select_component_entity", (component, kind, point_mm), None,
                           f"nenhum(a) {kind} de {component} casa com esse ponto/direção "
                           "(coordenadas da MONTAGEM, mm)")
    model = _model(_active_doc(app))
    if not append:
        com_call(model, "ClearSelection2", True)
    if not _select_with_mark(app, ent, True, mark):
        raise ComCallError("Select4", (component, kind), None, "entidade achada mas não selecionada")
    n = com_call(cast_to(com_get(model, "SelectionManager"), "ISelectionMgr"),
                 "GetSelectedObjectCount2", -1)
    return {"selected": True, "component": component, "kind": kind, "selection_count": n}


# ------------------------------------------------------------------- mates

def _raw_mates(comp: Any) -> list[Any]:
    return [cast_to(m, "IMate2") for m in (com_call(comp, "GetMates") or [])]


def _mate_value(mate: Any, tipo: str) -> float | None:
    """Valor de mate de distância (mm) ou ângulo (graus); None se não tiver."""
    if tipo not in ("distance", "angle"):
        return None
    try:
        disp = com_call(mate, "DisplayDimension2", 0)
        dim = cast_to(com_call(cast_to(disp, "IDisplayDimension"), "GetDimension2", 0), "IDimension")
        valor = com_get(dim, "SystemValue")
        return units.to_deg(valor) if tipo == "angle" else units.to_mm(valor)
    except (ComCallError, AttributeError):
        return None


def _describe(mate: Any) -> dict[str, Any]:
    tipos, alinhs = _mate_type_names(), _align_names()
    tipo = tipos.get(com_get(mate, "Type"), f"tipo {com_get(mate, 'Type')}")
    entidades = []
    for i in range(com_get(mate, "GetMateEntityCount")):
        me = cast_to(com_call(mate, "MateEntity", i), "IMateEntity2")
        p = list(com_get(me, "EntityParams"))
        ref = com_get(me, "ReferenceComponent")
        seltype = com_get(me, "ReferenceType2")
        ent = {"component": com_get(cast_to(ref, "IComponent2"), "Name2") if ref else None,
               "kind": KIND_BY_SELTYPE.get(seltype, f"seltype {seltype}"),
               "point_mm": [round(units.to_mm(v), 4) for v in p[:3]]}
        if len(p) >= 6 and ent["kind"] != "vertex":
            ent["direction"] = [round(v, 6) for v in p[3:6]]
        if len(p) >= 7 and p[6]:
            ent["radius_mm"] = round(units.to_mm(p[6]), 4)
        entidades.append(ent)
    return {"type": tipo, "alignment": alinhs.get(com_get(mate, "Alignment"), "?"),
            "flipped": bool(com_get(mate, "Flipped")),
            "value": _mate_value(mate, tipo), "entities": entidades}


def list_mates(app: Any, component: str) -> list[dict[str, Any]]:
    """Mates de um componente: tipo, alinhamento, valor e entidades (montagem, mm)."""
    comp = asm_w._find_component(app, component)
    return [_describe(m) for m in _raw_mates(comp)]


def _add_mate(app: Any, tipo: str, alinhamento: str, flip: bool,
              valor: float | None) -> tuple[bool, int]:
    c = swconst()
    asm = asm_w._assembly(app)
    d = units.from_mm(valor or 0.0) if tipo == "distance" else 0.0
    a = units.from_deg(valor or 0.0) if tipo == "angle" else 0.0
    r = com_call(asm, "AddMate5", getattr(c, asm_w.MATE_TYPES[tipo]),
                 getattr(c, ALIGNMENTS[alinhamento]), flip,
                 d, d, d, 0.0, 0.0, a, a, a, False, False, 0, 0)
    mate, erro = r if isinstance(r, tuple) else (r, None)
    return mate is not None and erro in (None, 1), erro


def mate_errors(app: Any) -> list[dict[str, Any]]:
    """Mates da montagem com erro/aviso de reconstrução (referência perdida)."""
    model = _model(_active_doc(app))
    saida = []
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        if com_call(feat, "GetTypeName2") == "MateGroup":
            sub = com_get(feat, "GetFirstSubFeature")
            while sub is not None:
                s = cast_to(sub, "IFeature")
                codigo = com_call(s, "GetErrorCode2")
                cod, aviso = (codigo if isinstance(codigo, tuple) else (codigo, False))
                if cod:
                    saida.append({"mate": com_call(s, "Name"), "error_code": cod,
                                  "warning_only": bool(aviso)})
                sub = com_get(s, "GetNextSubFeature")
        raw = com_call(feat, "GetNextFeature")
    return saida


# --------------------------------------------------------------- replicar

def replicate_component(app: Any, source: str, offsets_mm: list[list[float]]) -> dict[str, Any]:
    """Cópias de um componente deslocadas, com os MESMOS mates refeitos.

    Cada cópia entra com a mesma rotação do original, transladada pelo
    offset; cada mate do original é refeito com as entidades correspondentes
    — as da própria cópia e as do outro componente deslocadas pelo mesmo
    offset (o rasgo vizinho, o furo seguinte). Mate que não acha a entidade
    correspondente é relatado e pulado. No fim confere que a cópia não saiu
    do lugar: se os mates a moverem, a referência pegou a entidade errada.
    Original sem mates (fixo) gera cópias fixas.
    """
    if not offsets_mm or any(len(o) != 3 for o in offsets_mm):
        raise ComCallError("replicate_component", (source,), None,
                           "offsets_mm é uma lista de [dx, dy, dz] em mm")
    model = _model(_active_doc(app))
    asm = asm_w._assembly(app)
    orig = asm_w._find_component(app, source)
    arr0 = _array(orig)
    caminho = com_call(orig, "GetPathName")
    config = com_get(orig, "ReferencedConfiguration")
    mates = [(_describe(m)) for m in _raw_mates(orig)]
    centro0 = _box_center(orig)
    fixo0 = bool(com_call(orig, "IsFixed"))

    copias = []
    for off in offsets_mm:
        nome = asm_w.insert_component(app, caminho)["component"]
        comp = asm_w._find_component(app, nome)
        if config:
            comp.ReferencedConfiguration = config
        alvo = list(arr0)
        for i in range(3):
            alvo[9 + i] += units.from_mm(off[i])
        comp.Transform2 = asm_w._create_transform(app, alvo)
        com_call(model, "EditRebuild3")
        comp = asm_w._find_component(app, nome)
        hint = em.shifted(centro0, off)
        relatorio = []
        for mate in mates:
            if mate["type"] not in REPLICABLE:
                relatorio.append({"type": mate["type"], "ok": False,
                                  "reason": "tipo de mate não replicável"})
                continue
            entidades = []
            for e in mate["entities"]:
                dono = comp if e["component"] == source else asm_w._find_component(app, e["component"])
                ent = find_entity(dono, e["kind"], em.shifted(e["point_mm"], off),
                                  e.get("direction"), e.get("radius_mm", 0.0), hint)
                entidades.append((e, ent))
            faltando = [e["component"] for e, ent in entidades if ent is None]
            if faltando:
                relatorio.append({"type": mate["type"], "ok": False,
                                  "reason": f"entidade correspondente não achada em {faltando}"})
                continue
            com_call(model, "ClearSelection2", True)
            for i, (_, ent) in enumerate(entidades):
                _select_with_mark(app, ent, i > 0, 0)
            ok, erro = _add_mate(app, mate["type"], mate["alignment"], mate["flipped"], mate["value"])
            relatorio.append({"type": mate["type"], "ok": ok, "error": erro})
        com_call(model, "ClearSelection2", True)
        com_call(model, "EditRebuild3")
        comp = asm_w._find_component(app, nome)
        if not mates and fixo0:
            com_call(comp, "Select4", False, None, False)
            com_call(asm, "FixComponent")
            com_call(model, "ClearSelection2", True)
        depois = _array(comp)
        moveu_mm = max(abs(units.to_mm(depois[9 + i] - alvo[9 + i])) for i in range(3))
        girou = max(abs(depois[i] - alvo[i]) for i in range(9))
        copias.append({"component": nome, "offset_mm": off, "mates": relatorio,
                       "mates_ok": sum(1 for r in relatorio if r["ok"]),
                       "moved_mm": round(moveu_mm, 4), "rotated": girou > 1e-6,
                       "box_mm": [round(units.to_mm(v), 3) for v in com_call(comp, "GetBox", False, False)]})
        if moveu_mm > 1e-3 or girou > 1e-6:
            log.warning("%s saiu do lugar depois dos mates (%.4f mm) — referência errada?", nome, moveu_mm)
    return {"source": source, "copies": copias, "mate_errors": mate_errors(app)}


# ------------------------------------------------------------- substituir

def replace_component(app: Any, component: str, new_path: str,
                      all_instances: bool = False) -> dict[str, Any]:
    """Troca o arquivo de um componente mantendo posição e mates.

    Confere que o componente passou a apontar para o arquivo novo e devolve
    os mates que ficaram com erro (referência que não existe na peça nova).
    """
    import os

    new_path = os.path.abspath(new_path)
    if not os.path.exists(new_path):
        raise FileNotFoundError(f"arquivo não existe: {new_path}")
    model = _model(_active_doc(app))
    asm = asm_w._assembly(app)
    comp = asm_w._find_component(app, component)
    arr = _array(comp)
    com_call(model, "ClearSelection2", True)
    com_call(comp, "Select4", False, None, False)
    if not com_call(asm, "ReplaceComponents2", new_path, "", all_instances, 0, True):
        raise ComCallError("ReplaceComponents2", (component, new_path), None,
                           "o SolidWorks recusou a substituição")
    com_call(model, "EditRebuild3")
    trocados = []
    for info in asm_w.list_components(app):
        if os.path.normcase(info["path"] or "") == os.path.normcase(new_path):
            c = asm_w._find_component(app, info["name"])
            depois = _array(c)
            trocados.append({"component": info["name"], "fixed": info["fixed"],
                             "same_place": all(abs(a - b) < 1e-7 for a, b in zip(depois[:12], arr[:12]))
                             if not all_instances else None})
    if not trocados:
        raise ComCallError("ReplaceComponents2", (component, new_path), None,
                           "nenhum componente aponta para o arquivo novo depois da troca")
    return {"replaced": trocados, "mate_errors": mate_errors(app)}


def component_transform(app: Any, component: str) -> dict[str, Any]:
    """Posição da origem da peça e rotação (matriz) do componente na montagem."""
    arr = _array(asm_w._find_component(app, component))
    return {"component": component,
            "origin_mm": [round(v, 4) for v in apply_transform(arr, (0.0, 0.0, 0.0))],
            "x_axis": [round(v, 6) for v in arr[0:3]],
            "y_axis": [round(v, 6) for v in arr[3:6]],
            "z_axis": [round(v, 6) for v in arr[6:9]]}
