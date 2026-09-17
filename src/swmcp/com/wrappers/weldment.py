"""Estruturas soldadas (weldments): perfis, membros estruturais, lista de corte.

Executa no thread STA. Convenções do projeto: mm/graus na entrada, conversão
aqui; falha vira ComCallError com contexto; nada salva em disco.

Aprendizados (SW2023 PT-BR, confirmados ao vivo):
- IStructuralMemberGroup.Segments e o parâmetro Groups de
  InsertStructuralWeldment5 precisam ser VARIANT(VT_ARRAY|VT_DISPATCH) com os
  ``_oleobj_`` — lista Python de proxies gen_py marshalla errado e o método
  devolve None sem erro.
- ConnectedSegmentsOption=0 devolve None; usar swConnectedSegments_SimpleCut
  (1) ou CopedCut (2).
- CornerTreatmentType do grupo: 0=miter, 2=butt1, 3=butt2 (medido; o enum
  swCornerTreatmentTrim_e NÃO se aplica aqui — ver CORNER_TYPES).
- Sem a feature Weldment ('Soldagem') os corpos não viram itens de lista de
  corte: insert_structural_member a cria antes.
- Os tamanhos de um perfil configurado são as configurações do .sldlfp:
  ISldWorks::GetConfigurationNames(path) lê sem abrir o arquivo.
- As propriedades da lista de corte vêm localizadas (COMPRIMENTO, ÂNGULO1);
  a chave canônica está na fórmula ("LENGTH@@@…") — ver domain/weldment.py.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers.drawing_build import _active_drawing
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.domain import weldment as dom

log = logging.getLogger(__name__)

SW_ROOT = r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS"
DEFAULT_PROFILE_ROOT = os.path.join(SW_ROOT, "data", "weldment profiles")
DEFAULT_CUT_LIST_TEMPLATES = [
    os.path.join(SW_ROOT, "lang", "portuguese-brazilian", "cut list.sldwldtbt"),
    os.path.join(SW_ROOT, "lang", "english", "cut list.sldwldtbt"),
]

# IStructuralMemberGroup.CornerTreatmentType NÃO usa swCornerTreatmentTrim_e.
# Medido no SW2023 com um L de tubo 20x20 (300 + 200 mm), lendo a lista de
# corte: 0 e 1 → miter (45°/45°, 310 + 210); 2 → End Butt1 (1º segmento
# inteiro 310, 2º aparado 190); 3 → End Butt2 (1º aparado 290, 2º inteiro 210).
CORNER_TYPES = {
    "miter": 0,
    "butt1": 2,
    "butt2": 3,
}
# swConnectedSegments_e
CONNECTED_OPTIONS = {
    "simple": "swConnectedSegments_SimpleCut",
    "coped": "swConnectedSegments_CopedCut",
}
# swMirrorProfileOrAlignmentAxis_e
MIRROR_AXES = {
    "horizontal": "swMirrorProfileOrAlignmentAxis_Horizontal",
    "vertical": "swMirrorProfileOrAlignmentAxis_Vertical",
}


# ------------------------------------------------------------------ perfis

def profile_folders(app: Any) -> list[str]:
    """Pastas de perfis: preferência do usuário + biblioteca padrão da instalação."""
    # File Locations respondem por GetUserPreferenceStringValue (a variante
    # StringListValue devolve "" no SW2023, medido)
    raw = com_call(app, "GetUserPreferenceStringValue", swconst().swFileLocationsWeldmentProfiles) or ""
    folders = [p.strip() for p in raw.split(";") if p.strip()]
    if os.path.isdir(DEFAULT_PROFILE_ROOT):
        folders.append(DEFAULT_PROFILE_ROOT)
    out: list[str] = []
    seen: set[str] = set()
    for f in folders:
        key = os.path.normcase(os.path.abspath(f))
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def profile_sizes(app: Any, path: str) -> list[str]:
    """Configurações do .sldlfp (= tamanhos), sem abrir o documento."""
    names = com_call(app, "GetConfigurationNames", path)
    return list(names or ())


def list_profiles(app: Any, standard: str | None = None, kind: str | None = None) -> dict[str, Any]:
    folders = profile_folders(app)
    catalog = dom.scan_profile_folders(folders)
    if standard:
        catalog = [p for p in catalog if p.standard.lower() == standard.strip().lower()]
    if kind:
        catalog = [p for p in catalog if p.kind.lower() == kind.strip().lower()]
    # tamanhos só quando o filtro estreitou a lista: cada leitura é uma
    # chamada COM, e a biblioteca inteira passa de 60 arquivos
    with_sizes = bool(standard or kind)
    profiles = []
    for p in catalog:
        item: dict[str, Any] = {"standard": p.standard, "type": p.kind, "path": p.path}
        if with_sizes:
            item["sizes"] = list(p.sizes) or profile_sizes(app, p.path)
        profiles.append(item)
    return {
        "folders": folders,
        "standards": sorted({p.standard for p in dom.scan_profile_folders(folders)}, key=str.lower),
        "profiles": profiles,
    }


def resolve_profile(app: Any, standard: str, kind: str, size: str | None) -> tuple[str, str]:
    """(caminho do .sldlfp, nome da configuração) — erro rico se não existir."""
    catalog = dom.scan_profile_folders(profile_folders(app))
    prof = dom.find_profile(catalog, standard, kind, size)
    if prof is None:
        kinds = sorted({p.kind for p in catalog if p.standard.lower() == standard.strip().lower()}, key=str.lower)
        hint = f"tipos em {standard!r}: {kinds}" if kinds else f"norma {standard!r} não existe — use list_weldment_profiles"
        raise ComCallError("resolve_profile", (standard, kind), None, f"perfil não encontrado; {hint}")
    if prof.sizes:
        # layout legado (<tipo>/<tamanho>.sldlfp): o tamanho é o arquivo e a
        # configuração a passar é a única que existe dentro dele ("Default")
        if size is not None and size.strip().lower() != prof.sizes[0].lower():
            kinds = sorted({p.sizes[0] for p in catalog if p.standard.lower() == standard.strip().lower()
                            and p.kind.lower() == kind.strip().lower() and p.sizes}, key=str.lower)
            raise ComCallError("resolve_profile", (standard, kind, size), None, f"tamanho não existe; disponíveis: {kinds}")
        configs = profile_sizes(app, prof.path)
        return prof.path, (configs[0] if configs else "")
    sizes = profile_sizes(app, prof.path)
    if size is None:
        if len(sizes) == 1:
            return prof.path, sizes[0]
        raise ComCallError("resolve_profile", (standard, kind), None, f"informe o tamanho; disponíveis: {sizes}")
    for s in sizes:
        if s.strip().lower() == size.strip().lower():
            return prof.path, s
    raise ComCallError("resolve_profile", (standard, kind, size), None, f"tamanho não existe; disponíveis: {sizes}")


# ------------------------------------------------------------------ features

def _features(model: Any):
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        feat = cast_to(raw, "IFeature")
        yield feat
        raw = com_call(feat, "GetNextFeature")


def _feature_by_name(model: Any, name: str) -> Any:
    for feat in _features(model):
        if com_call(feat, "Name") == name:
            return feat
    raise ComCallError("FeatureByName", (name,), None, "feature não existe no documento ativo (use list_features)")


def _feature_by_type(model: Any, type_name: str) -> Any | None:
    for feat in _features(model):
        if com_call(feat, "GetTypeName2") == type_name:
            return feat
    return None


def _part_model(app: Any) -> Any:
    model = _model(_active_doc(app))
    if com_call(model, "GetType") != swconst().swDocPART:
        raise ComCallError("ActiveDoc", (), None, "weldment só existe em peça (.sldprt) — documento ativo não é peça")
    return model


def insert_weldment_feature(app: Any) -> dict[str, Any]:
    """Marca a peça como weldment (feature 'Soldagem'). Idempotente."""
    model = _part_model(app)
    existing = _feature_by_type(model, "WeldmentFeature")
    if existing is not None:
        return {"feature": com_call(existing, "Name"), "created": False}
    raw = com_call(com_get(model, "FeatureManager"), "InsertWeldmentFeature")
    if raw is None:
        raise ComCallError("InsertWeldmentFeature", (), None, "feature de weldment não criada")
    return {"feature": com_call(cast_to(raw, "IFeature"), "Name"), "created": True}


def _dispatch_array(objs: list[Any]) -> Any:
    import pythoncom
    from win32com.client import VARIANT

    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [o._oleobj_ for o in objs])


def _com_set(obj: Any, prop: str, value: Any) -> None:
    import pywintypes

    try:
        setattr(obj, prop, value)
    except pywintypes.com_error as exc:
        raise ComCallError(f"set {prop}", (value,), exc.args[0] if exc.args else None, str(exc)) from exc


def insert_structural_member(
    app: Any,
    standard: str,
    kind: str,
    size: str | None,
    sketch: str,
    segments: list[str] | None = None,
    corner: str | None = "miter",
    connected: str = "simple",
    angle_deg: float = 0.0,
    mirror: str | None = None,
    gap_mm: float = 0.0,
    merge_arc_bodies: bool = False,
) -> dict[str, Any]:
    """InsertStructuralWeldment5 com um grupo formado pelos segmentos do sketch."""
    c = swconst()
    if corner is not None and corner not in CORNER_TYPES:
        raise ValueError(f"corner deve ser um de {sorted(CORNER_TYPES)} ou None")
    if connected not in CONNECTED_OPTIONS:
        raise ValueError(f"connected deve ser um de {sorted(CONNECTED_OPTIONS)}")
    if mirror is not None and mirror not in MIRROR_AXES:
        raise ValueError(f"mirror deve ser um de {sorted(MIRROR_AXES)} ou None")

    model = _part_model(app)
    path, config = resolve_profile(app, standard, kind, size)

    feat = _feature_by_name(model, sketch)
    if com_call(feat, "GetTypeName2") not in ("ProfileFeature", "3DProfileFeature"):
        raise ComCallError("sketch", (sketch,), None, f"{sketch!r} não é um sketch (tipo {com_call(feat, 'GetTypeName2')})")
    sk = cast_to(com_call(feat, "GetSpecificFeature2"), "ISketch")
    all_segs = [cast_to(s, "ISketchSegment") for s in (com_call(sk, "GetSketchSegments") or ())]
    by_name = {com_call(s, "GetName"): s for s in all_segs}
    if not by_name:
        raise ComCallError("GetSketchSegments", (sketch,), None, "sketch sem segmentos")
    if segments:
        missing = [n for n in segments if n not in by_name]
        if missing:
            raise ComCallError("segments", tuple(missing), None, f"segmentos inexistentes; o sketch tem {sorted(by_name)}")
        chosen = [by_name[n] for n in segments]
    else:
        chosen = list(by_name.values())

    weld = insert_weldment_feature(app)

    com_call(model, "ClearSelection2", True)
    fm = com_get(model, "FeatureManager")
    group = cast_to(com_call(fm, "CreateStructuralMemberGroup"), "IStructuralMemberGroup")
    _com_set(group, "Segments", _dispatch_array(chosen))
    if com_call(group, "GetSegmentsCount") != len(chosen):
        raise ComCallError("Segments", (len(chosen),), None, "grupo não aceitou os segmentos")
    _com_set(group, "ApplyCornerTreatment", corner is not None)
    if corner is not None:
        _com_set(group, "CornerTreatmentType", CORNER_TYPES[corner])
    _com_set(group, "Angle", units.from_deg(angle_deg))
    _com_set(group, "GapWithinGroup", units.from_mm(gap_mm))
    _com_set(group, "MergeArcSegmentBodies", merge_arc_bodies)
    _com_set(group, "MirrorProfile", mirror is not None)
    if mirror is not None:
        _com_set(group, "MirrorProfileAxis", getattr(c, MIRROR_AXES[mirror]))

    raw = com_call(
        fm, "InsertStructuralWeldment5",
        path, getattr(c, CONNECTED_OPTIONS[connected]), True, _dispatch_array([group]), config,
    )
    if raw is None:
        raise ComCallError(
            "InsertStructuralWeldment5", (path, config, sketch), None,
            "membro não criado — o SolidWorks recusa sem dizer por quê; causas comuns: segmentos "
            "que não formam caminho contínuo no mesmo plano, segmento já usado por outro membro, "
            "perfil sem essa configuração",
        )
    feature = cast_to(raw, "IFeature")
    name = com_call(feature, "Name")
    log.info("membro estrutural %s (%s %s %s) em %s", name, standard, kind, config, sketch)
    return {
        "feature": name,
        "profile": {"standard": standard, "type": kind, "size": config, "path": path},
        "sketch": sketch,
        "segments": [com_call(s, "GetName") for s in chosen],
        "weldment_feature": weld["feature"],
        "corner": corner,
        "saved": False,
    }


# ------------------------------------------------------------------ lista de corte

def get_cut_list(app: Any, update: bool = True) -> dict[str, Any]:
    """Itens da lista de corte da peça ativa (pasta 'Corpos sólidos')."""
    model = _part_model(app)
    folder_feat = _feature_by_type(model, "SolidBodyFolder")
    if folder_feat is None:
        raise ComCallError("SolidBodyFolder", (), None, "peça sem pasta de corpos sólidos")
    folder = cast_to(com_call(folder_feat, "GetSpecificFeature2"), "IBodyFolder")
    updated = bool(com_call(folder, "UpdateCutList")) if update else None

    items: list[dict[str, Any]] = []
    _collect_cut_list_items(folder_feat, items)
    is_weldment = _feature_by_type(model, "WeldmentFeature") is not None
    return {
        "document": com_call(model, "GetTitle"),
        "is_weldment": is_weldment,
        "automatic_cut_list": bool(com_call(folder, "GetAutomaticCutList")),
        "automatic_update": bool(com_call(folder, "GetAutomaticUpdate")),
        "updated": updated,
        "items": items,
        "total_bodies": sum(i["bodies"] for i in items),
        "note": "length/total_length nas unidades do documento (mm salvo indicação contrária em sw_status)",
    }


def _collect_cut_list_items(parent: Any, items: list[dict[str, Any]]) -> None:
    raw = com_call(parent, "GetFirstSubFeature")
    while raw is not None:
        sub = cast_to(raw, "IFeature")
        t = com_call(sub, "GetTypeName2")
        if t == "CutListFolder":
            items.append(_cut_list_item(sub))
        elif t == "SubWeldFolder":
            _collect_cut_list_items(sub, items)
        raw = com_call(sub, "GetNextSubFeature")


def _cut_list_item(feat: Any) -> dict[str, Any]:
    name = com_call(feat, "Name")
    folder = cast_to(com_call(feat, "GetSpecificFeature2"), "IBodyFolder")
    bodies = int(com_call(folder, "GetBodyCount") or 0)
    body_names = []
    for b in com_call(folder, "GetBodies") or ():
        body_names.append(com_call(cast_to(b, "IBody2"), "Name"))
    cpm = com_call(feat, "CustomPropertyManager")
    raw_props: dict[str, tuple[str, str]] = {}
    for prop in com_call(cpm, "GetNames") or ():
        result = com_call(cpm, "Get6", prop, False)
        # early binding: (status, ValOut, ResolvedValOut, WasResolved, LinkToProperty)
        raw_props[prop] = (str(result[1]), str(result[2]))
    return dom.normalize_cut_list_item(name, raw_props, bodies, body_names)


# ------------------------------------------------------------------ tabela no desenho

def _view_by_name(dwg: Any, name: str) -> Any:
    sheet_view = com_call(dwg, "GetFirstView")
    raw = com_call(cast_to(sheet_view, "IView"), "GetNextView") if sheet_view is not None else None
    names = []
    while raw is not None:
        view = cast_to(raw, "IView")
        n = com_call(view, "GetName2")
        if n == name:
            return view
        names.append(n)
        raw = com_call(view, "GetNextView")
    raise ComCallError("view", (name,), None, f"vista não existe na folha ativa; vistas: {names}")


def cut_list_template(app: Any, template: str | None) -> str:
    if template:
        if not os.path.isfile(template):
            raise FileNotFoundError(f"template de lista de corte não existe: {template}")
        return template
    raw = com_call(app, "GetUserPreferenceStringValue", swconst().swFileLocationsWeldmentCutListTemplates) or ""
    for folder in [p.strip() for p in raw.split(";") if p.strip()]:
        for entry in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
            if entry.lower().endswith(".sldwldtbt"):
                return os.path.join(folder, entry)
    for cand in DEFAULT_CUT_LIST_TEMPLATES:
        if os.path.isfile(cand):
            return cand
    raise FileNotFoundError("nenhum template .sldwldtbt encontrado — informe template=")


def insert_cut_list_table(
    app: Any, view: str, x_mm: float, y_mm: float, template: str | None = None, configuration: str = "",
) -> dict[str, Any]:
    """Tabela de lista de corte ancorada em (x,y) mm da folha, ligada à vista."""
    dwg = _active_drawing(app)
    tpl = cut_list_template(app, template)
    v = _view_by_name(dwg, view)
    raw = com_call(
        v, "InsertWeldmentTable",
        False, units.from_mm(x_mm), units.from_mm(y_mm),
        swconst().swBOMConfigurationAnchor_TopLeft, configuration, tpl,
    )
    if raw is None:
        raise ComCallError(
            "InsertWeldmentTable", (view, tpl), None,
            "tabela não criada — a vista precisa referenciar uma peça weldment com lista de corte",
        )
    table = cast_to(raw, "ITableAnnotation")
    rows = com_get(table, "RowCount")
    cols = com_get(table, "ColumnCount")
    return {"view": view, "template": tpl, "rows": rows, "columns": cols, "saved": False}


# ------------------------------------------------------------------ corte normal ao tubo (laser)

def _solid_bodies(part: Any) -> list[Any]:
    return [cast_to(b, "IBody2") for b in (com_call(part, "GetBodies2", swconst().swSolidBody, True) or ())]


def _body_by_name(part: Any, name: str | None) -> Any:
    bodies = _solid_bodies(part)
    if not bodies:
        raise ComCallError("GetBodies2", (), None, "peça sem corpos sólidos")
    names = [com_call(b, "Name") for b in bodies]
    if name is None:
        if len(bodies) == 1:
            return bodies[0]
        raise ComCallError("body", (), None, f"peça com vários corpos — informe body; opções: {names}")
    for b, n in zip(bodies, names):
        if n == name:
            return b
    raise ComCallError("body", (name,), None, f"corpo não existe; opções: {names}")


def _vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    import math
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


class _TubeFrame:
    """Eixo do tubo (ponto P0, direção A) e base (U, V) perpendicular; metros."""

    def __init__(self, p0, axis):
        self.p0 = tuple(p0)
        self.a = _norm(axis)
        e = min((abs(self.a[i]), i) for i in range(3))[1]
        ref = tuple(1.0 if i == e else 0.0 for i in range(3))
        self.u = _norm(_cross(self.a, ref))
        self.v = _cross(self.a, self.u)

    def to_local(self, p):
        """(s ao longo do eixo, ângulo em graus, raio)."""
        import math
        d = _vec_sub(p, self.p0)
        s = _dot(d, self.a)
        r = (d[0] - s * self.a[0], d[1] - s * self.a[1], d[2] - s * self.a[2])
        return s, math.degrees(math.atan2(_dot(r, self.v), _dot(r, self.u))), math.sqrt(_dot(r, r))

    def to_world(self, s, angle_deg, radius):
        import math
        t = math.radians(angle_deg)
        c_, s_ = math.cos(t), math.sin(t)
        return tuple(self.p0[i] + s * self.a[i] + radius * (c_ * self.u[i] + s_ * self.v[i]) for i in range(3))

    def coaxial(self, p, axis, tol=1e-6):
        a = _norm(axis)
        if abs(abs(_dot(a, self.a)) - 1.0) > 1e-6:
            return False
        d = _vec_sub(p, self.p0)
        s = _dot(d, self.a)
        r = (d[0] - s * self.a[0], d[1] - s * self.a[1], d[2] - s * self.a[2])
        return _dot(r, r) < tol * tol


def _face_kind(face: Any):
    s = cast_to(com_call(face, "GetSurface"), "ISurface")
    if com_call(s, "IsCylinder"):
        p = com_call(s, "CylinderParams")
        return "cyl", (p[0:3], p[3:6], p[6])
    if com_call(s, "IsPlane"):
        p = com_call(s, "PlaneParams")
        return "plane", (p[0:3], p[3:6], None)
    return "other", None


def _classify_tube(body: Any) -> dict[str, Any]:
    """Separa faces do tubo (externa, interna, topos) das faces de corte (boca)."""
    faces = [cast_to(f, "IFace2") for f in (com_call(body, "GetFaces") or ())]
    cyls = []
    for f in faces:
        kind, prm = _face_kind(f)
        if kind == "cyl":
            cyls.append((com_call(f, "GetArea"), f, prm))
    if not cyls:
        raise ComCallError("tube", (), None, "corpo sem face cilíndrica — não é tubo")
    cyls.sort(key=lambda x: -x[0])
    _, _outer, (p0, axis, r_out) = cyls[0]
    frame = _TubeFrame(p0, axis)
    outer_faces, inner_faces, ends, cope = [], [], [], []
    for f in faces:
        kind, prm = _face_kind(f)
        if kind == "cyl" and frame.coaxial(prm[0], prm[1]):
            (outer_faces if abs(prm[2] - r_out) < 1e-7 else inner_faces).append((f, prm[2]))
        elif kind == "plane" and abs(abs(_dot(_norm(prm[0]), frame.a)) - 1.0) < 1e-6:
            ends.append(f)
        else:
            cope.append(f)
    if not inner_faces:
        raise ComCallError("tube", (), None, "tubo sem face interna coaxial — só tubo de parede é suportado")
    r_in = max(r for _, r in inner_faces)
    return {"frame": frame, "outer": [f for f, _ in outer_faces], "inner": [f for f, _ in inner_faces],
            "ends": ends, "cope": cope, "r_out": r_out, "r_in": r_in}


def _classify_tube_safe(body: Any):
    try:
        return _classify_tube(body)
    except ComCallError:
        return None


def _sample_edge(edge: Any, n: int = 120) -> list[tuple[float, float, float]]:
    """Pontos ao longo da aresta (metros).

    Aresta aberta: tesselação entre os vértices (GetTessPts) — avaliar a curva
    pelos parâmetros de GetCurveParams2 devolve trechos errados em curvas de
    interseção abertas (medido: desvio de 30 mm). Aresta fechada (sem
    vértices): avaliação por parâmetro, que aí é confiável.
    """
    import pythoncom
    from win32com.client import VARIANT

    cv = cast_to(com_call(edge, "GetCurve"), "ICurve")
    sv = com_call(edge, "GetStartVertex")
    if sv is not None:
        sp = com_call(cast_to(sv, "IVertex"), "GetPoint")
        ep = com_call(cast_to(com_call(edge, "GetEndVertex"), "IVertex"), "GetPoint")
        tess = com_call(cv, "GetTessPts", 0.00002, 0.0,
                        VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, list(sp)),
                        VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, list(ep)))
        return [(tess[i], tess[i + 1], tess[i + 2]) for i in range(0, len(tess), 3)]
    prm = com_call(edge, "GetCurveParams2")
    u0, u1 = prm[6], prm[7]
    pts = []
    for i in range(n + 1):
        e = com_call(cv, "Evaluate", u0 + (u1 - u0) * i / n)
        pts.append((e[0], e[1], e[2]))
    return pts


def _is_same(_ext: Any, a: Any, b: Any) -> bool:
    """Identidade COM: mesmo objeto ⇔ mesmo ponteiro IUnknown."""
    import pythoncom

    ua = a._oleobj_.QueryInterface(pythoncom.IID_IUnknown)
    ub = b._oleobj_.QueryInterface(pythoncom.IID_IUnknown)
    return ua == ub


def _intersection_mm3(c: Any, a: Any, b: Any) -> tuple[float, list[list[float]]]:
    ca = cast_to(com_call(a, "Copy"), "IBody2")
    cb = cast_to(com_call(b, "Copy"), "IBody2")
    r = com_call(ca, "Operations2", c.SWBODYINTERSECT, cb, 0)
    res = r[0] if isinstance(r, tuple) else r
    pieces = [cast_to(bb, "IBody2") for bb in (res or ())]
    vol = sum(com_call(p, "GetMassProperties", 1.0)[3] * 1e9 for p in pieces)
    return round(vol, 3), [[round(v * 1000, 2) for v in com_call(p, "GetBodyBox")] for p in pieces]


def normalize_tube_cut(
    app: Any,
    body: str | None = None,
    check_against: str | None = None,
    step_deg: float = 1.0,
    margin_mm: float = 2.0,
) -> dict[str, Any]:
    """Refaz a boca de lobo de um tubo como corte NORMAL ao tubo (laser).

    Contorno = junção das arestas interna e externa da boca (em cada ângulo,
    a mais recuada), materializado como superfície loft radial e aplicado com
    Substituir face nas faces da boca; a superfície auxiliar é apagada.
    """
    import pythoncom
    from win32com.client import VARIANT

    c = swconst()
    model = _part_model(app)
    part = cast_to(model, "IPartDoc")
    fm = com_get(model, "FeatureManager")
    ext = com_get(model, "Extension")
    skm = com_get(model, "SketchManager")
    selmgr = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    tube = _body_by_name(part, body)
    tube_name = com_call(tube, "Name")
    props0 = com_call(tube, "GetMassProperties", 1.0)
    cls = _classify_tube(tube)
    if not cls["cope"]:
        raise ComCallError("tube", (tube_name,), None, "tubo sem face de corte (boca): nada a normalizar")
    frame: _TubeFrame = cls["frame"]

    # contornos = arestas das faces de corte compartilhadas com a face externa / interna
    outlines: dict[str, list[tuple[float, float]]] = {"outer": [], "inner": []}
    for cf in cls["cope"]:
        for e in com_call(cf, "GetEdges") or ():
            e = cast_to(e, "IEdge")
            side = None
            for f in com_call(e, "GetTwoAdjacentFaces2") or ():
                f = cast_to(f, "IFace2")
                if any(_is_same(ext, f, o) for o in cls["outer"]):
                    side = "outer"
                elif any(_is_same(ext, f, o) for o in cls["inner"]):
                    side = "inner"
            if side is None:
                continue
            for p in _sample_edge(e):
                s, ang, _ = frame.to_local(p)
                outlines[side].append((ang, s))
    for side, pts in outlines.items():
        gap = dom.angular_gap_deg(pts)
        if len(pts) < 8 or gap > 15.0:
            raise ComCallError("outline", (side,), None,
                               f"contorno {side} não dá a volta no tubo (lacuna {gap:.0f}°) — só boca completa é suportada")

    # sentido do corpo em relação à boca: o corte recua para o lado do corpo
    s_body = frame.to_local(tuple(props0[0:3]))[0]
    s_cope = sum(s for pts in outlines.values() for _, s in pts) / sum(len(p) for p in outlines.values())
    toward = 1.0 if s_body > s_cope else -1.0
    comb = dom.combine_outlines([outlines["outer"], outlines["inner"]], toward, step_deg)

    # duas splines 3D (dentro e fora da parede) → loft = superfície radial
    r_in = max(cls["r_in"] - margin_mm / 1000.0, cls["r_in"] * 0.5)
    r_out = cls["r_out"] + margin_mm / 1000.0

    def spline(radius: float) -> str:
        com_call(model, "ClearSelection2", True)
        com_call(skm, "Insert3DSketch", True)
        flat: list[float] = []
        for ang, s in comb:
            flat += list(frame.to_world(s, ang, radius))
        seg = com_call(skm, "CreateSpline2", VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat), False)
        com_call(skm, "Insert3DSketch", True)
        if seg is None:
            raise ComCallError("CreateSpline2", (radius,), None, "spline do contorno não criada")
        return com_call(cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature"), "Name")

    sk_in, sk_out = spline(r_in), spline(r_out)
    com_call(model, "ClearSelection2", True)
    com_call(ext, "SelectByID2", sk_in, "SKETCH", 0.0, 0.0, 0.0, False, 1, None, 0)
    com_call(ext, "SelectByID2", sk_out, "SKETCH", 0.0, 0.0, 0.0, True, 1, None, 0)
    n_sheet0 = len(com_call(part, "GetBodies2", c.swSheetBody, False) or ())
    com_call(model, "InsertLoftRefSurface2", False, False, False, 1.0, 0, 0)
    sheets = com_call(part, "GetBodies2", c.swSheetBody, False) or ()
    if len(sheets) <= n_sheet0:
        raise ComCallError("InsertLoftRefSurface2", (sk_in, sk_out), None, "superfície radial não criada")
    loft_name = com_call(cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature"), "Name")
    surf_face = cast_to(com_call(cast_to(sheets[-1], "IBody2"), "GetFaces")[0], "IFace2")

    # Substituir face: alvos marca 1, face da superfície marca 2 (medido no SW2023)
    com_call(model, "ClearSelection2", True)
    cope_faces = _classify_tube(_body_by_name(part, tube_name))["cope"]  # proxies frescos
    for i, cf in enumerate(cope_faces):
        sd = cast_to(com_call(selmgr, "CreateSelectData"), "ISelectData")
        sd.Mark = 1
        com_call(cast_to(cf, "IEntity"), "Select4", i > 0, sd)
    sd = cast_to(com_call(selmgr, "CreateSelectData"), "ISelectData")
    sd.Mark = 2
    com_call(cast_to(surf_face, "IEntity"), "Select4", True, sd)
    n0 = com_call(model, "GetFeatureCount")
    com_call(model, "InsertFeatureReplaceFace")
    com_call(model, "ForceRebuild3", False)
    if com_call(model, "GetFeatureCount") <= n0:
        raise ComCallError("InsertFeatureReplaceFace", (tube_name,), None, "Substituir face não criado")
    rf = cast_to(com_call(model, "FeatureByPositionReverse", 0), "IFeature")
    replace_name = com_call(rf, "Name")
    err = com_call(rf, "GetErrorCode2", True)
    if err[0] != 0:
        raise ComCallError("InsertFeatureReplaceFace", (tube_name,), None, f"Substituir face com erro {err[0]}")

    # apagar a superfície auxiliar
    sheets = com_call(part, "GetBodies2", c.swSheetBody, False) or ()
    com_call(model, "ClearSelection2", True)
    com_call(cast_to(sheets[-1], "IBody2"), "Select2", False, None)
    dfe = com_call(fm, "InsertDeleteBody2", False)
    com_call(model, "ForceRebuild3", False)

    # o corpo é renomeado pelo SolidWorks com o nome da última feature
    new_tube = None
    for b in _solid_bodies(part):
        if com_call(b, "Name") in (tube_name, replace_name):
            new_tube = b
    if new_tube is None:
        new_tube = _solid_bodies(part)[-1]
    props1 = com_call(new_tube, "GetMassProperties", 1.0)
    result: dict[str, Any] = {
        "body": tube_name,
        "body_after": com_call(new_tube, "Name"),
        "features": [sk_in, sk_out, loft_name, replace_name, dfe and com_call(cast_to(dfe, "IFeature"), "Name")],
        "cope_faces_replaced": len(cope_faces),
        "outline_points": len(comb),
        "toward_axis_sign": toward,
        "volume_before_mm3": round(props0[3] * 1e9, 1),
        "volume_after_mm3": round(props1[3] * 1e9, 1),
        "saved": False,
    }
    if check_against:
        vol, pieces = _intersection_mm3(c, new_tube, _body_by_name(part, check_against))
        result["interference_mm3"] = vol
    log.info("corte normal no tubo %s: %s", tube_name, result["features"])
    return result


def body_interference(app: Any, body_a: str, body_b: str) -> dict[str, Any]:
    """Volume da interseção entre dois corpos sólidos da peça ativa (mm³)."""
    c = swconst()
    part = cast_to(_part_model(app), "IPartDoc")
    vol, pieces = _intersection_mm3(c, _body_by_name(part, body_a), _body_by_name(part, body_b))
    return {"bodies": [body_a, body_b], "interference_mm3": vol, "pieces": pieces}


# ------------------------------------------------------------------ criar perfil (.sldlfp)

PROFILE_SHAPES = ("round_tube", "square_tube", "rect_tube", "round_bar", "flat_bar")


def _profile_geometry(shape: str, od: float, wall: float, width: float, height: float, corner_r: float | None):
    """Devolve (descrição, tamanho padrão, desenhar(skm)) para o perfil; mm."""
    from swmcp.com import units as u

    def circle(skm, r):
        return com_call(skm, "CreateCircleByRadius", 0.0, 0.0, 0.0, u.from_mm(r))

    def rounded_rect(skm, w, h, r):
        """Retângulo centrado na origem com cantos de raio r (0 = cantos vivos)."""
        x, y = w / 2.0, h / 2.0
        if r <= 0:
            return com_call(skm, "CreateCornerRectangle", u.from_mm(-x), u.from_mm(-y), 0.0, u.from_mm(x), u.from_mm(y), 0.0)
        L = lambda x1, y1, x2, y2: com_call(skm, "CreateLine", u.from_mm(x1), u.from_mm(y1), 0.0, u.from_mm(x2), u.from_mm(y2), 0.0)
        A = lambda cx, cy, x1, y1, x2, y2: com_call(skm, "CreateArc", u.from_mm(cx), u.from_mm(cy), 0.0,
                                                    u.from_mm(x1), u.from_mm(y1), 0.0, u.from_mm(x2), u.from_mm(y2), 0.0, 1)
        segs = [
            L(-x + r, y, x - r, y), L(x, y - r, x, -y + r), L(x - r, -y, -x + r, -y), L(-x, -y + r, -x, y - r),
            A(x - r, y - r, x, y - r, x - r, y), A(x - r, -y + r, x - r, -y, x, -y + r),
            A(-x + r, -y + r, -x, -y + r, -x + r, -y), A(-x + r, y - r, -x + r, y, -x, y - r),
        ]
        return all(s is not None for s in segs)

    def fmt(v):
        return f"{v:g}"

    if shape == "round_tube":
        if od <= 0 or wall <= 0 or 2 * wall >= od:
            raise ValueError("round_tube exige od_mm > 2*wall_mm > 0")
        return (f"Tubo Redondo {fmt(od)} x {fmt(wall)}mm", f"{fmt(od)} x {fmt(wall)}mm",
                lambda skm: circle(skm, od / 2) is not None and circle(skm, od / 2 - wall) is not None)
    if shape in ("square_tube", "rect_tube"):
        if shape == "square_tube":
            height = width
        if width <= 0 or height <= 0 or wall <= 0 or 2 * wall >= min(width, height):
            raise ValueError(f"{shape} exige width_mm/height_mm > 2*wall_mm > 0")
        r_out = 2.0 * wall if corner_r is None else corner_r
        r_in = max(r_out - wall, 0.0)
        nome = "Tubo Quadrado" if shape == "square_tube" else "Metalon"
        size = f"{fmt(height)} x {fmt(width)} x {fmt(wall)}mm" if shape == "rect_tube" else f"{fmt(width)} x {fmt(width)} x {fmt(wall)}mm"
        return (f"{nome} {fmt(height)}x{fmt(width)}x{fmt(wall)}mm", size,
                lambda skm: rounded_rect(skm, width, height, r_out) and rounded_rect(skm, width - 2 * wall, height - 2 * wall, r_in))
    if shape == "round_bar":
        if od <= 0:
            raise ValueError("round_bar exige od_mm > 0")
        return (f"Barra Redonda {fmt(od)}mm", f"{fmt(od)}mm", lambda skm: circle(skm, od / 2) is not None)
    if shape == "flat_bar":
        if width <= 0 or height <= 0:
            raise ValueError("flat_bar exige width_mm e height_mm > 0")
        return (f"Barra Chata {fmt(width)} x {fmt(height)}mm", f"{fmt(width)} x {fmt(height)}mm",
                lambda skm: rounded_rect(skm, width, height, 0.0))
    raise ValueError(f"shape deve ser um de {PROFILE_SHAPES}")


def library_profile_folder(app: Any) -> str:
    """Primeira pasta de perfis do usuário (fora da instalação do SolidWorks)."""
    for f in profile_folders(app):
        if not os.path.normcase(f).startswith(os.path.normcase(SW_ROOT)):
            return f
    raise ComCallError("profile_folders", (), None,
                       "nenhuma pasta de perfis do usuário configurada — use set_file_location/apply_kongz_library ou passe folder")


def create_weldment_profile(
    app: Any,
    shape: str,
    standard: str,
    kind: str,
    size: str | None = None,
    od_mm: float = 0.0,
    wall_mm: float = 0.0,
    width_mm: float = 0.0,
    height_mm: float = 0.0,
    corner_radius_mm: float | None = None,
    description: str | None = None,
    folder: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Cria um perfil de weldment .sldlfp em <pasta>/<norma>/<tipo>/<tamanho>.SLDLFP.

    Mesmo layout e conteúdo dos perfis da biblioteca KONGZ: um sketch no
    Plano frontal centrado na origem, ponto no centro, propriedade Description,
    salvo como Lib Feat Part com o sketch selecionado.
    """
    from swmcp.com.wrappers import output as o
    from swmcp.com.wrappers import modeling as m

    c = swconst()
    desc, default_size, draw = _profile_geometry(shape, od_mm, wall_mm, width_mm, height_mm, corner_radius_mm)
    size = (size or default_size).strip()
    description = description or desc
    root = os.path.abspath(folder) if folder else library_profile_folder(app)
    target_dir = os.path.join(root, standard.strip(), kind.strip())
    path = os.path.join(target_dir, f"{size}.SLDLFP")
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"perfil já existe: {path} (overwrite=True para substituir)")
    os.makedirs(target_dir, exist_ok=True)

    o.new_document(app, "part")
    model = _model(_active_doc(app))
    title = com_call(model, "GetTitle")
    try:
        ext = com_get(model, "Extension")
        skm = com_get(model, "SketchManager")
        sketch_name = m.insert_sketch(app, "Plano frontal")
        # sem AddToDB o snap funde a geometria interna na externa quando a parede
        # é fina (tubo 38.1 x 1.2 saía com os dois círculos de mesmo raio)
        _com_set(skm, "AddToDB", True)
        try:
            ok = draw(skm)
            com_call(skm, "CreatePoint", 0.0, 0.0, 0.0)
        finally:
            _com_set(skm, "AddToDB", False)
        sk = cast_to(com_call(model, "GetActiveSketch2"), "ISketch")
        lengths = sorted(round(com_call(cast_to(s, "ISketchSegment"), "GetLength"), 9)
                         for s in (com_call(sk, "GetSketchSegments") or ()))
        if len(set(lengths)) != len(lengths) and shape == "round_tube":
            ok = False
        m.exit_sketch(app)
        if not ok:
            raise ComCallError("sketch", (shape,), None, "geometria do perfil não foi desenhada")
        cpm = com_call(ext, "CustomPropertyManager", "")
        com_call(cpm, "Add3", "Description", c.swCustomInfoText, description, c.swCustomPropertyReplaceValue)
        com_call(model, "ClearSelection2", True)
        if not com_call(ext, "SelectByID2", sketch_name, "SKETCH", 0.0, 0.0, 0.0, False, 0, None, 0):
            raise ComCallError("SelectByID2", (sketch_name,), None, "sketch do perfil não selecionado")
        ok, errors, warnings = com_call(ext, "SaveAs3", path, c.swSaveAsCurrentVersion, c.swSaveAsOptions_Silent, None, None, 0, 0)
        if not ok or not os.path.exists(path):
            raise ComCallError("SaveAs3", (path,), None, f"falha ao salvar o perfil (errors={errors})")
    finally:
        com_call(app, "CloseDoc", title)
    log.info("perfil de weldment criado: %s", path)
    return {
        "path": path, "standard": standard, "type": kind, "size": size,
        "description": description, "shape": shape,
        "usable_as": {"standard": standard, "type": kind, "size": size},
    }
