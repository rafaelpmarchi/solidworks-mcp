"""Deixar QUALQUER esboço totalmente definido (escrita). Thread STA.

Regra da Gromar: esboço nenhum fica azul. fully_dimension_profile (em
dimensioning) resolve o perfil de revolução, com cota diametral; aqui é o caso
geral — perfil de chapa, retângulo, polilinha, círculos e os pontos soltos do
esboço de posição do assistente de furação:

1. relação horizontal/vertical em cada linha que já é horizontal/vertical;
2. ponto que está na origem fica coincidente com ela;
3. pontos soltos (centros de furo) alinhados em coluna/linha por relação e
   cotados em cadeia a partir da origem (domain.sketch_layout decide);
4. comprimento de cada linha e diâmetro de cada círculo;
5. o que ainda sobrar: cota horizontal/vertical de cada ponto até a origem.

Cada relação e cada cota é conferida: se sobredefinir o esboço é desfeita na
hora (EditUndo2) e contada em 'discarded'. As entidades do esboço morrem a cada
relação/cota (o SolidWorks as recria), então tudo é relocalizado por
coordenada no momento de usar — nunca guardado de um passo para o outro.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers import modeling
from swmcp.domain.sketch_layout import plan_points

log = logging.getLogger(__name__)

FULLY_CONSTRAINED = 3   # swConstrainedStatus_e
OVER_CONSTRAINED = 4
TOL_MM = 1e-4

SEG_LINE = 0            # swSketchSegments_e
SEG_ARC = 1


def _model(app: Any) -> Any:
    doc = com_get(app, "ActiveDoc")
    if doc is None:
        raise ComCallError("ActiveDoc", (), None, "nenhum documento ativo no SolidWorks")
    return cast_to(doc, "IModelDoc2")


def _skm(app: Any) -> Any:
    return cast_to(com_get(_model(app), "SketchManager"), "ISketchManager")


def _sketch(app: Any) -> Any:
    sk = com_get(_skm(app), "ActiveSketch")
    if sk is None:
        raise ComCallError("ActiveSketch", (), None, "não há esboço aberto")
    return cast_to(sk, "ISketch")


def _xy(ponto: Any) -> tuple[float, float]:
    return units.to_mm(com_get(ponto, "X")), units.to_mm(com_get(ponto, "Y"))


def _near(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) < TOL_MM and abs(a[1] - b[1]) < TOL_MM


# ------------------------------------------------------------ leitura do esboço

def _lines(app: Any) -> list[dict[str, Any]]:
    saida = []
    for raw in com_call(_sketch(app), "GetSketchSegments") or []:
        seg = cast_to(raw, "ISketchSegment")
        if com_call(seg, "GetType") != SEG_LINE:
            continue
        linha = cast_to(raw, "ISketchLine")
        a = _xy(cast_to(com_get(linha, "GetStartPoint2"), "ISketchPoint"))
        b = _xy(cast_to(com_get(linha, "GetEndPoint2"), "ISketchPoint"))
        saida.append({"seg": seg, "a": a, "b": b,
                      "horizontal": abs(a[1] - b[1]) < TOL_MM,
                      "vertical": abs(a[0] - b[0]) < TOL_MM})
    return saida


def _circles(app: Any) -> list[dict[str, Any]]:
    saida = []
    for raw in com_call(_sketch(app), "GetSketchSegments") or []:
        seg = cast_to(raw, "ISketchSegment")
        if com_call(seg, "GetType") != SEG_ARC:
            continue
        arco = cast_to(raw, "ISketchArc")
        centro = _xy(cast_to(com_call(arco, "GetCenterPoint2"), "ISketchPoint"))
        saida.append({"seg": seg, "center": centro,
                      "diameter": units.to_mm(com_call(arco, "GetRadius")) * 2.0,
                      "full": bool(com_call(arco, "IsCircle"))})
    return saida


def _line_at(app: Any, a: tuple[float, float], b: tuple[float, float]) -> Any:
    for s in _lines(app):
        if (_near(s["a"], a) and _near(s["b"], b)) or (_near(s["a"], b) and _near(s["b"], a)):
            return s["seg"]
    raise ComCallError("_line_at", (a, b), None, f"linha {a}→{b} sumiu do esboço")


def _circle_at(app: Any, centro: tuple[float, float], diametro: float) -> Any:
    for c in _circles(app):
        if _near(c["center"], centro) and abs(c["diameter"] - diametro) < TOL_MM:
            return c["seg"]
    raise ComCallError("_circle_at", (centro, diametro), None, "círculo sumiu do esboço")


def _point_at(app: Any, xy: tuple[float, float]) -> Any:
    for raw in com_call(_sketch(app), "GetSketchPoints2") or []:
        ponto = cast_to(raw, "ISketchPoint")
        if _near(_xy(ponto), xy):
            return ponto
    raise ComCallError("_point_at", (xy,), None, f"nenhum ponto do esboço em {xy}")


def _endpoints(linhas: list[dict[str, Any]]) -> list[tuple[float, float]]:
    vistos: list[tuple[float, float]] = []
    for s in linhas:
        for p in (s["a"], s["b"]):
            if not any(_near(p, v) for v in vistos):
                vistos.append(p)
    return vistos


def _loose_points(app: Any) -> list[tuple[float, float]]:
    """Pontos que não são ponta de linha: centros de furo e de círculo."""
    pontas = _endpoints(_lines(app))
    soltos: list[tuple[float, float]] = []
    for raw in com_call(_sketch(app), "GetSketchPoints2") or []:
        p = _xy(cast_to(raw, "ISketchPoint"))
        if any(_near(p, q) for q in pontas) or any(_near(p, q) for q in soltos):
            continue
        soltos.append(p)
    return soltos


# ------------------------------------------------------------------- seleção

def _select_origin(app: Any, append: bool) -> None:
    """Seleciona a origem da peça como ponto externo do esboço.

    Pela posição (0,0,0) funciona em qualquer plano que passe pela origem; se
    não pegar, vai pelo nome do ponto da feature Origem (que muda com o idioma).
    """
    model = _model(app)
    ext = com_get(model, "Extension")
    c = swconst()
    if com_call(ext, "SelectByID2", "", "EXTSKETCHPOINT", 0.0, 0.0, 0.0,
                append, 0, None, c.swSelectOptionDefault):
        return
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        if com_call(feat, "GetTypeName2") == "OriginProfileFeature":
            nome = com_call(feat, "Name")
            for ponto in ("Ponto1", "Point1"):
                if com_call(ext, "SelectByID2", f"{ponto}@{nome}", "EXTSKETCHPOINT",
                            0.0, 0.0, 0.0, append, 0, None, c.swSelectOptionDefault):
                    return
        raw = com_call(feat, "GetNextFeature")
    raise ComCallError("select_origin", (), None, "não consegui selecionar a origem da peça")


def _select(app: Any, *alvos: Any) -> None:
    """Seleciona na ordem: 'ORIGIN', ponto (x,y), ou objeto de esboço."""
    model = _model(app)
    com_call(model, "ClearSelection2", True)
    for alvo in alvos:
        if isinstance(alvo, str) and alvo == "ORIGIN":
            _select_origin(app, True)
            continue
        if isinstance(alvo, tuple):
            alvo = _point_at(app, alvo)
        if not com_call(alvo, "Select4", True, None):
            raise ComCallError("Select4", (), None, "entidade de esboço não selecionada")


# ------------------------------------------------------------------ definição

class _Definer:
    """Aplica relação/cota conferindo o estado; desfaz o que sobredefine."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.model = _model(app)
        self.relations = 0
        self.dimensions: list[dict[str, Any]] = []
        self.discarded = 0

    def status(self) -> int:
        return com_call(_sketch(self.app), "GetConstrainedStatus")

    def done(self) -> bool:
        return self.status() == FULLY_CONSTRAINED

    def _undo_if_over(self) -> bool:
        if self.status() == OVER_CONSTRAINED:
            com_call(self.model, "EditUndo2", 1)
            self.discarded += 1
            return True
        return False

    def relation(self, tipo: str, *alvos: Any) -> bool:
        if self.done():
            return False
        try:
            _select(self.app, *alvos)
        except ComCallError as exc:
            log.warning("relação %s não aplicada: %s", tipo, exc)
            return False
        com_call(self.model, "SketchAddConstraints", tipo)
        com_call(self.model, "ClearSelection2", True)
        if self._undo_if_over():
            return False
        self.relations += 1
        return True

    def dimension(self, kind: str, value_mm: float, criar: Callable[[], Any]) -> bool:
        if self.done():
            return False
        try:
            disp = criar()
        except ComCallError as exc:
            log.warning("cota %s não criada: %s", kind, exc)
            disp = None
        com_call(self.model, "ClearSelection2", True)
        if disp is None:
            self.discarded += 1
            return False
        if self._undo_if_over():
            return False
        nome = ""
        try:
            dim = cast_to(com_call(cast_to(disp, "IDisplayDimension"), "GetDimension2", 0), "IDimension")
            nome = com_get(dim, "FullName").split("@")[0]
        except ComCallError:
            pass
        self.dimensions.append({"name": nome, "kind": kind, "value_mm": round(value_mm, 4)})
        return True


def _define_active(app: Any) -> dict[str, Any]:
    d = _Definer(app)
    model = d.model
    m = lambda v: units.from_mm(v)  # noqa: E731

    # 1) linhas: horizontal/vertical por relação
    for s in [dict(s) for s in _lines(app)]:
        if s["horizontal"] or s["vertical"]:
            tipo = "sgHORIZONTAL2D" if s["horizontal"] else "sgVERTICAL2D"
            d.relation(tipo, _line_at(app, s["a"], s["b"]))

    # 2) o que está na origem fica coincidente com ela
    for p in _endpoints(_lines(app)):
        if abs(p[0]) < TOL_MM and abs(p[1]) < TOL_MM:
            d.relation("sgCOINCIDENT", p, "ORIGIN")
            break

    # 3) pontos soltos: colunas/linhas por relação, cadeia de cotas
    soltos = _loose_points(app)
    plano = plan_points(soltos)
    for i in plano.at_origin:
        d.relation("sgCOINCIDENT", soltos[i], "ORIGIN")
    for grupo in plano.columns:
        for a, b in zip(grupo, grupo[1:]):
            d.relation("sgVERTICALPOINTS2D", soltos[a], soltos[b])
    for grupo in plano.rows:
        for a, b in zip(grupo, grupo[1:]):
            d.relation("sgHORIZONTALPOINTS2D", soltos[a], soltos[b])
    for i in plano.vertical_to_origin:
        d.relation("sgVERTICALPOINTS2D", soltos[i], "ORIGIN")
    for i in plano.horizontal_to_origin:
        d.relation("sgHORIZONTALPOINTS2D", soltos[i], "ORIGIN")

    # 4) comprimento de cada linha, diâmetro de cada círculo
    for s in [dict(s) for s in _lines(app)]:
        comprimento = ((s["a"][0] - s["b"][0]) ** 2 + (s["a"][1] - s["b"][1]) ** 2) ** 0.5
        meio = ((s["a"][0] + s["b"][0]) / 2.0, (s["a"][1] + s["b"][1]) / 2.0)
        desloc = max(comprimento * 0.08, 5.0)
        texto = (meio[0] - desloc, meio[1]) if s["vertical"] else (meio[0], meio[1] + desloc)

        def criar(a=s["a"], b=s["b"], texto=texto):
            _select(app, _line_at(app, a, b))
            return com_call(model, "AddDimension2", m(texto[0]), m(texto[1]), 0.0)
        d.dimension("comprimento", comprimento, criar)
    for c in [dict(c) for c in _circles(app)]:
        def criar(c=c):
            _select(app, _circle_at(app, c["center"], c["diameter"]))
            return com_call(model, "AddDimension2", m(c["center"][0] + c["diameter"]),
                            m(c["center"][1] + c["diameter"]), 0.0)
        d.dimension("diâmetro" if c["full"] else "raio", c["diameter"], criar)

    # 5) cadeias dos pontos soltos (colunas na horizontal, linhas na vertical)
    def ref(i):
        return "ORIGIN" if i is None else soltos[i]

    def coord(i, eixo):
        return 0.0 if i is None else soltos[i][eixo]

    for r, i in plano.horizontal_chain:
        valor = abs(soltos[i][0] - coord(r, 0))

        def criar(r=r, i=i):
            _select(app, ref(r), soltos[i])
            return com_call(model, "AddHorizontalDimension2",
                            m((coord(r, 0) + soltos[i][0]) / 2.0), m(soltos[i][1] - 12.0), 0.0)
        d.dimension("horizontal", valor, criar)
    for r, i in plano.vertical_chain:
        valor = abs(soltos[i][1] - coord(r, 1))

        def criar(r=r, i=i):
            _select(app, ref(r), soltos[i])
            return com_call(model, "AddVerticalDimension2",
                            m(soltos[i][0] - 12.0), m((coord(r, 1) + soltos[i][1]) / 2.0), 0.0)
        d.dimension("vertical", valor, criar)

    # 6) o que sobrou (perfil solto no plano, linha inclinada): cada ponto até a origem
    if not d.done():
        restantes = sorted(_endpoints(_lines(app)) + soltos, key=lambda p: abs(p[0]) + abs(p[1]))
        for p in restantes:
            if d.done():
                break
            if abs(p[0]) > TOL_MM:
                def criar(p=p):
                    _select(app, "ORIGIN", p)
                    return com_call(model, "AddHorizontalDimension2",
                                    m(p[0] / 2.0), m(p[1] + 10.0), 0.0)
                d.dimension("horizontal", abs(p[0]), criar)
            if abs(p[1]) > TOL_MM and not d.done():
                def criar(p=p):
                    _select(app, "ORIGIN", p)
                    return com_call(model, "AddVerticalDimension2",
                                    m(p[0] + 10.0), m(p[1] / 2.0), 0.0)
                d.dimension("vertical", abs(p[1]), criar)

    com_call(model, "ClearSelection2", True)
    estado = d.status()
    return {"relations": d.relations, "dimensions": d.dimensions,
            "discarded": d.discarded, "status": estado,
            "fully_defined": estado == FULLY_CONSTRAINED}


def fully_define_sketch(app: Any, sketch_name: str = "") -> dict[str, Any]:
    """Deixa o esboço totalmente definido; devolve o que foi feito e o estado final.

    Sem sketch_name trabalha no esboço ABERTO e o deixa aberto (para seguir
    com extrude/flange). Com sketch_name abre esse esboço — inclusive o
    esboço de posição dentro de uma feature de furo — e fecha no fim,
    reconstruindo a peça.
    """
    skm = _skm(app)
    abriu = False
    if sketch_name:
        if com_get(skm, "ActiveSketch") is not None:
            raise ComCallError("fully_define_sketch", (sketch_name,), None,
                               "já há um esboço aberto — feche-o antes de definir outro pelo nome")
        modeling.edit_sketch(app, sketch_name)
        abriu = True
    elif com_get(skm, "ActiveSketch") is None:
        raise ComCallError("fully_define_sketch", (), None,
                           "não há esboço aberto — informe sketch_name")
    nome = sketch_name or com_call(
        cast_to(com_call(_model(app), "FeatureByPositionReverse", 0), "IFeature"), "Name")
    c = swconst()
    entrada_manual = com_call(app, "GetUserPreferenceToggle", c.swInputDimValOnCreate)
    com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, False)
    try:
        if com_call(_sketch(app), "GetConstrainedStatus") == FULLY_CONSTRAINED:
            resultado = {"relations": 0, "dimensions": [], "discarded": 0,
                         "status": FULLY_CONSTRAINED, "fully_defined": True}
        else:
            resultado = _define_active(app)
    finally:
        com_call(app, "SetUserPreferenceToggle", c.swInputDimValOnCreate, entrada_manual)
        if abriu:
            modeling.exit_sketch(app)
            com_call(_model(app), "ForceRebuild3", False)
    if not resultado["fully_defined"]:
        log.warning("esboço %s ficou com status %s depois da cotagem automática",
                    nome, resultado["status"])
    return {"sketch": nome, **resultado}
