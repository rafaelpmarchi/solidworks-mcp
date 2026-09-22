"""Cotagem de esboço: deixar o perfil totalmente definido (escrita).

Esboço criado por API nasce sub-definido (azul): a geometria está no lugar
certo, mas nada segura as cotas — qualquer arrasto ou edição de feature move o
perfil, e não há de onde parametrizar a peça. Aqui as cotas entram de verdade,
uma a uma, conferindo o estado do esboço a cada passo, até ele ficar totalmente
definido (preto).

Duas armadilhas da API, medidas no SW2023:
- criar cota abre a caixa "Modificar" e a automação trava esperando o usuário;
  a opção swInputDimValOnCreate precisa estar desligada durante a cotagem;
- a cota de uma linha contra a linha de centro só sai DIAMETRAL se o texto for
  posto do outro lado do eixo — do mesmo lado sai como raio.
"""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers import modeling

log = logging.getLogger(__name__)

# estados de ISketch::GetConstrainedStatus (swConstrainedStatus_e)
FULLY_CONSTRAINED = 3
OVER_CONSTRAINED = 4
TOL_MM = 1e-4


def _model(app: Any) -> Any:
    doc = com_get(app, "ActiveDoc")
    if doc is None:
        raise ComCallError("ActiveDoc", (), None, "nenhum documento ativo no SolidWorks")
    return cast_to(doc, "IModelDoc2")


def _active_sketch(app: Any) -> Any:
    skm = cast_to(com_get(_model(app), "SketchManager"), "ISketchManager")
    sk = com_get(skm, "ActiveSketch")
    if sk is None:
        raise ComCallError("ActiveSketch", (), None,
                           "não há sketch aberto — use edit_sketch antes")
    return cast_to(sk, "ISketch")


def _pt(ponto: Any) -> tuple[float, float]:
    return units.to_mm(com_get(ponto, "X")), units.to_mm(com_get(ponto, "Y"))


def _segments(sketch: Any) -> list[dict[str, Any]]:
    saida = []
    for raw in com_call(sketch, "GetSketchSegments") or []:
        seg = cast_to(raw, "ISketchSegment")
        if com_call(seg, "GetType") != 0:  # 0 = linha
            continue
        linha = cast_to(raw, "ISketchLine")
        p1 = cast_to(com_get(linha, "GetStartPoint2"), "ISketchPoint")
        p2 = cast_to(com_get(linha, "GetEndPoint2"), "ISketchPoint")
        a, b = _pt(p1), _pt(p2)
        saida.append({"seg": seg, "p1": p1, "p2": p2, "a": a, "b": b,
                      "construcao": bool(com_get(seg, "ConstructionGeometry")),
                      "horizontal": abs(a[1] - b[1]) < TOL_MM,
                      "vertical": abs(a[0] - b[0]) < TOL_MM})
    return saida


def _status(sketch: Any) -> int:
    return com_call(sketch, "GetConstrainedStatus")


# Cada relação/cota faz o SolidWorks recriar as entidades do esboço: um
# ISketchSegment guardado antes vira ponteiro morto ("object has disconnected").
# Por isso tudo é localizado por coordenada, na hora de usar.

def _centerline(app: Any) -> Any:
    for s in _segments(_active_sketch(app)):
        if s["construcao"]:
            return s["seg"]
    raise ComCallError("centerline", (), None,
                       "o esboço não tem linha de centro — ela é o eixo da revolução")


def _line_at_y(app: Any, y_mm: float) -> Any:
    for s in _segments(_active_sketch(app)):
        if s["construcao"] or not s["horizontal"]:
            continue
        if abs(s["a"][1] - y_mm) < TOL_MM:
            return s["seg"]
    raise ComCallError("_line_at_y", (y_mm,), None, f"nenhuma linha horizontal em y={y_mm}")


def _point_at_xy(app: Any, x_mm: float, abs_y_mm: float) -> Any:
    for s in _segments(_active_sketch(app)):
        for chave in ("p1", "p2"):
            x, y = _pt(s[chave])
            if abs(x - x_mm) < TOL_MM and abs(abs(y) - abs_y_mm) < TOL_MM:
                return s[chave]
    raise ComCallError("_point_at_xy", (x_mm, abs_y_mm), None,
                       f"nenhum ponto do perfil em x={x_mm}, |y|={abs_y_mm}")


def _point_at_x(app: Any, x_mm: float) -> Any:
    for s in _segments(_active_sketch(app)):
        for chave in ("p1", "p2"):
            if abs(_pt(s[chave])[0] - x_mm) < TOL_MM:
                return s[chave]
    raise ComCallError("_point_at_x", (x_mm,), None, f"nenhum ponto do perfil em x={x_mm}")


def _sketch_feature(app: Any, name: str) -> Any:
    """A feature da árvore com esse nome (as cotas penduram nela, não no ISketch)."""
    model = _model(app)
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        if com_call(feat, "Name") == name:
            return feat
        raw = com_call(feat, "GetNextFeature")
    raise ComCallError("_sketch_feature", (name,), None, f"esboço {name} não está na árvore")


def _clear_dimensions_and_relations(app: Any, sketch_name: str) -> dict[str, int]:
    """Apaga cotas e relações do esboço aberto, para recotar do zero."""
    model = _model(app)
    sketch = _active_sketch(app)
    feature = _sketch_feature(app, sketch_name)
    apagadas = 0
    for _ in range(500):   # apagar invalida a cadeia: recomeça da primeira a cada volta
        raw = com_call(_sketch_feature(app, sketch_name), "GetFirstDisplayDimension")
        if raw is None:
            break
        # quem se seleciona é a anotação da cota, não o IDisplayDimension
        anotacao = com_call(cast_to(raw, "IDisplayDimension"), "GetAnnotation")
        if anotacao is None:
            break
        com_call(model, "ClearSelection2", True)
        if not com_call(cast_to(anotacao, "IAnnotation"), "Select3", False, None):
            break
        com_call(model, "DeleteSelection", False)
        apagadas += 1
    rm = com_get(sketch, "RelationManager")
    relacoes = 0
    if rm is not None:
        com_call(cast_to(rm, "ISketchRelationManager"), "DeleteAllRelations")
        relacoes = -1   # a API não diz quantas eram; -1 = "todas"
    com_call(model, "ClearSelection2", True)
    return {"dimensions": apagadas, "relations": relacoes}


def fully_dimension_profile(app: Any, sketch_name: str = "",
                            axial_baseline_mm: float = 0.0,
                            reset: bool = False) -> dict[str, Any]:
    """Cota um perfil de revolução até ele ficar totalmente definido.

    Espera o perfil desenhado no plano frontal, eixo em X e a linha de centro
    da revolução no próprio esboço. Põe relação horizontal/vertical em cada
    linha, cota o DIÂMETRO de cada degrau (linha × linha de centro) e a posição
    axial de cada degrau a partir de axial_baseline_mm (a face de referência).
    Cada cota é conferida: a que sobredefine o esboço é desfeita na hora.
    reset=True apaga as cotas e relações que já existem antes de recomeçar —
    é o que torna a cotagem repetível num esboço já mexido.
    """
    model = _model(app)
    if sketch_name:
        modeling.edit_sketch(app, sketch_name)
    sketch = _active_sketch(app)
    nome_sketch = sketch_name or com_call(
        cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature"), "Name")
    c = swconst()
    entrada_manual = com_call(app, "GetUserPreferenceToggle", c.swInputDimValOnCreate)
    com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, False)
    relacoes = 0
    cotas: list[dict[str, Any]] = []
    descartadas = 0
    limpeza = None
    try:
        if reset:
            limpeza = _clear_dimensions_and_relations(app, nome_sketch)
            sketch = _active_sketch(app)
        segmentos = _segments(sketch)
        _centerline(app)  # falha cedo se não houver eixo

        # 1) relações: o que é horizontal/vertical no desenho passa a ser por relação.
        #    A lista é refeita a cada volta porque cada relação recria as entidades.
        pendentes = [(s["a"], s["b"], "sgHORIZONTAL" if s["horizontal"] else "sgVERTICAL")
                     for s in segmentos if s["horizontal"] or s["vertical"]]
        for a, b, tipo in pendentes:
            atual = next((s for s in _segments(_active_sketch(app))
                          if abs(s["a"][0] - a[0]) < TOL_MM and abs(s["a"][1] - a[1]) < TOL_MM
                          and abs(s["b"][0] - b[0]) < TOL_MM and abs(s["b"][1] - b[1]) < TOL_MM), None)
            if atual is None:
                continue
            com_call(model, "ClearSelection2", True)
            com_call(atual["seg"], "Select4", False, None)
            com_call(model, "SketchAddConstraints", tipo)
            relacoes += 1

        # 2) âncora: sem prender o perfil na origem ele fica solto mesmo cotado.
        #    A origem é ponto EXTERNO ao esboço (EXTSKETCHPOINT), não aparece em
        #    GetSketchPoints2 — por isso vai por SelectByID2.
        ext = com_get(model, "Extension")
        com_call(model, "ClearSelection2", True)
        achou_origem = com_call(ext, "SelectByID2", "", "EXTSKETCHPOINT", 0.0, 0.0, 0.0,
                                False, 0, None, c.swSelectOptionDefault)
        if achou_origem:
            ponto_base = next((s[chave] for s in _segments(_active_sketch(app))
                               for chave in ("p1", "p2")
                               if abs(_pt(s[chave])[0]) < TOL_MM and abs(_pt(s[chave])[1]) < TOL_MM), None)
            if ponto_base is not None:
                com_call(ponto_base, "Select4", True, None)
                com_call(model, "SketchAddConstraints", "sgCOINCIDENT")
                relacoes += 1
            else:
                log.warning("perfil sem ponto na origem; ele fica cotado mas solto no plano")
        com_call(model, "ClearSelection2", True)

        # 3) degraus do mesmo diâmetro andam juntos: colinear em vez de cota repetida
        por_nivel: dict[float, list[tuple]] = {}
        for s in segmentos:
            if s["construcao"] or not s["horizontal"] or abs(s["a"][1]) < TOL_MM:
                continue
            por_nivel.setdefault(round(s["a"][1], 4), []).append((s["a"], s["b"]))
        for y, linhas in por_nivel.items():
            for a, b in linhas[1:]:
                com_call(model, "ClearSelection2", True)
                com_call(_line_at_y(app, y), "Select4", False, None)
                atual = next((s for s in _segments(_active_sketch(app))
                              if not s["construcao"] and abs(s["a"][0] - a[0]) < TOL_MM
                              and abs(s["b"][0] - b[0]) < TOL_MM
                              and abs(s["a"][1] - a[1]) < TOL_MM), None)
                if atual is None:
                    continue
                com_call(atual["seg"], "Select4", True, None)
                com_call(model, "SketchAddConstraints", "sgCOLINEAR")
                relacoes += 1
        com_call(model, "ClearSelection2", True)

        raio_max = max((abs(p) for s in segmentos for p in (s["a"][1], s["b"][1])), default=10.0)

        def tenta(criar, descricao: str, valor: float) -> bool:
            nonlocal descartadas
            antes = _status(sketch)
            if antes == FULLY_CONSTRAINED:
                return False
            disp = criar()
            if disp is None:
                descartadas += 1
                return False
            if _status(sketch) == OVER_CONSTRAINED:
                com_call(model, "EditUndo2", 1)   # essa cota sobrava
                descartadas += 1
                return False
            dim = cast_to(com_call(cast_to(disp, "IDisplayDimension"), "GetDimension2", 0), "IDimension")
            cotas.append({"name": com_get(dim, "FullName").split("@")[0],
                          "kind": descricao, "value_mm": round(valor, 4)})
            return True

        # 2) diâmetros: uma cota por degrau, texto do outro lado do eixo (sai diametral)
        niveis: dict[float, dict[str, Any]] = {}
        for s in segmentos:
            if s["construcao"] or not s["horizontal"] or abs(s["a"][1]) < TOL_MM:
                continue
            niveis.setdefault(round(s["a"][1], 4), s)
        for y, s in sorted(niveis.items(), key=lambda kv: -abs(kv[0])):
            meio_x = (s["a"][0] + s["b"][0]) / 2.0
            def criar(meio_x=meio_x, y=y):
                com_call(model, "ClearSelection2", True)
                com_call(_line_at_y(app, y), "Select4", False, None)
                com_call(_centerline(app), "Select4", True, None)
                # texto do outro lado do eixo: é o que faz a cota sair diametral
                return com_call(model, "AddDimension2",
                                units.from_mm(meio_x), units.from_mm(-y - raio_max * 0.4), 0.0)
            tenta(criar, "diâmetro", abs(y) * 2)

        # 3) posições axiais: cada degrau cotado a partir da face de referência
        _point_at_x(app, axial_baseline_mm)  # falha cedo se a referência não existe
        vistos: set[float] = {round(axial_baseline_mm, 4)}
        for s in segmentos:            # coordenadas já lidas: os objetos daqui já morreram
            for ponta in ("a", "b"):
                vistos.add(round(s[ponta][0], 4))
        alvos = sorted(x for x in vistos if abs(x - axial_baseline_mm) > TOL_MM)
        for x in alvos:
            def criar(x=x):
                com_call(model, "ClearSelection2", True)
                com_call(_point_at_x(app, axial_baseline_mm), "Select4", False, None)
                com_call(_point_at_x(app, x), "Select4", True, None)
                return com_call(model, "AddHorizontalDimension2",
                                units.from_mm((axial_baseline_mm + x) / 2.0),
                                units.from_mm(raio_max * 1.4), 0.0)
            tenta(criar, "comprimento", abs(x - axial_baseline_mm))

        # 6) o que sobrou: ponto que não pertence a nenhuma linha horizontal (a
        #    ponta de um chanfro, por exemplo) fica com o diâmetro solto — cota
        #    o ponto contra a linha de centro.
        if _status(sketch) != FULLY_CONSTRAINED:
            soltos = sorted({(round(s[ponta][0], 4), round(abs(s[ponta][1]), 4))
                             for s in segmentos for ponta in ("a", "b")
                             if abs(s[ponta][1]) > TOL_MM},
                            key=lambda p: (-p[1], p[0]))
            for ponto_x, y in soltos:
                if _status(sketch) == FULLY_CONSTRAINED:
                    break
                def criar(ponto_x=ponto_x, y=y):
                    com_call(model, "ClearSelection2", True)
                    com_call(_point_at_xy(app, ponto_x, y), "Select4", False, None)
                    com_call(_centerline(app), "Select4", True, None)
                    return com_call(model, "AddDimension2",
                                    units.from_mm(ponto_x), units.from_mm(-y - raio_max * 0.6), 0.0)
                tenta(criar, "diâmetro", y * 2)

        com_call(model, "ClearSelection2", True)
        estado = _status(sketch)
    finally:
        com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, entrada_manual)
    log.info("cotagem de %s: %d relações, %d cotas, status %d",
             nome_sketch, relacoes, len(cotas), estado)
    return {"sketch": nome_sketch, "relations": relacoes, "dimensions": cotas,
            "discarded": descartadas, "status": estado, "cleared": limpeza,
            "fully_defined": estado == FULLY_CONSTRAINED}
