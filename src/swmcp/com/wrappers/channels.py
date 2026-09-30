"""Pórticos, canais inclinados, esboço em face por coordenadas da peça e furação
em lote (escrita). Executa no thread STA.

Bloco hidráulico é furação: pórtico G com rebaixo, rosca e canal no mesmo
eixo, e canais Ø7 inclinados das interfaces de válvula. O assistente de
furação do SW2023 não faz rebaixo customizado (sai em polegada — ver
holes.py) e não fura inclinado; aqui os dois viram CORTE POR REVOLUÇÃO de um
meio-perfil (domain.ports) num plano paralelo a um plano base que contém o
eixo. O perfil começa fora da peça, então o rebaixo também abre um ressalto
que esteja por cima da face.

Tudo que é posição entra em coordenadas da PEÇA (mm): o esboço de uma face tem
eixos próprios e chutar a orientação é o que põe furo no lugar errado.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to
from swmcp.com.wrappers import holes, modeling
from swmcp.com.wrappers import sketch_define as sd
from swmcp.com.wrappers.modeling import _active_doc, _model
from swmcp.domain import ports
from swmcp.domain.placement import apply_transform

log = logging.getLogger(__name__)

# ponto do perfil que caiu fora do plano do esboço (mm): plano errado
PLANE_TOLERANCE_MM = 0.01


# ------------------------------------------------------------ utilitários

@contextmanager
def suspended_graphics(app: Any) -> Iterator[None]:
    """Desliga redesenho da vista e da árvore durante um lote — é o que faz
    dezenas de features por API levarem segundos e não minutos. Restaura
    sempre."""
    model = _model(_active_doc(app))
    fm = com_get(model, "FeatureManager")
    view = com_get(model, "ActiveView")
    estados: list[tuple[Any, str, Any]] = []
    for alvo, prop, valor in ((fm, "EnableFeatureTree", False), (view, "EnableGraphicsUpdate", False)):
        if alvo is None:
            continue
        try:
            estados.append((alvo, prop, com_get(alvo, prop)))
            setattr(alvo, prop, valor)
        except Exception:  # noqa: BLE001 — acelerar é opcional
            log.debug("não consegui desligar %s", prop)
    try:
        yield
    finally:
        for alvo, prop, valor in reversed(estados):
            try:
                setattr(alvo, prop, valor)
            except Exception:  # noqa: BLE001
                log.exception("não consegui religar %s", prop)
        try:
            com_call(model, "GraphicsRedraw2")
        except ComCallError:
            pass


def base_planes(app: Any) -> dict[str, str]:
    """Nomes dos três planos base pela posição na árvore (independe do idioma):
    o 1º RefPlane é o Frontal (XY), o 2º o Superior (XZ), o 3º o Direito (YZ)."""
    model = _model(_active_doc(app))
    nomes = []
    raw = com_call(model, "FirstFeature")
    while raw is not None and len(nomes) < 3:
        feat = cast_to(raw, "IFeature")
        if com_call(feat, "GetTypeName2") == "RefPlane":
            nomes.append(com_call(feat, "Name"))
        raw = com_call(feat, "GetNextFeature")
    if len(nomes) < 3:
        raise ComCallError("base_planes", (), None, "a peça não tem os três planos base")
    return dict(zip(("front", "top", "right"), nomes))


def model_to_sketch(sketch: Any, point_mm: Sequence[float]) -> tuple[float, float, float]:
    """Ponto da peça (mm) → coordenadas do esboço (mm); z ≠ 0 = fora do plano."""
    xf = cast_to(com_call(sketch, "ModelToSketchTransform"), "IMathTransform")
    return apply_transform(list(com_get(xf, "ArrayData")), point_mm)


def _active_sketch(app: Any) -> Any:
    sk = com_get(com_get(_model(_active_doc(app)), "SketchManager"), "ActiveSketch")
    if sk is None:
        raise ComCallError("ActiveSketch", (), None, "não há esboço aberto")
    return cast_to(sk, "ISketch")


def _to_2d(app: Any, pontos: Sequence[Sequence[float]], contexto: str) -> list[list[float]]:
    sketch = _active_sketch(app)
    saida = []
    for p in pontos:
        x, y, z = model_to_sketch(sketch, p)
        if abs(z) > PLANE_TOLERANCE_MM:
            raise ComCallError(contexto, tuple(p), None,
                               f"o ponto {list(p)} está a {z:.3f}mm do plano do esboço — "
                               "confira as coordenadas da peça")
        saida.append([round(x, 6), round(y, 6)])
    return saida


def _feature(app: Any, nome: str) -> Any:
    return modeling._feature_by_name(_model(_active_doc(app)), nome)


def _last_feature(app: Any) -> Any:
    return cast_to(com_call(_model(_active_doc(app)), "FeatureByPositionReverse", 0), "IFeature")


def _error_code(feat: Any) -> int:
    raw = com_call(feat, "GetErrorCode2", True)
    return int(raw[0] if isinstance(raw, tuple) else raw)


def _hide_plane(app: Any, nome: str) -> None:
    model = _model(_active_doc(app))
    com_call(model, "ClearSelection2", True)
    modeling.select_entity(app, nome, "PLANE")
    com_call(model, "BlankRefGeom")
    com_call(model, "ClearSelection2", True)


def _delete(app: Any, feat: Any) -> None:
    model = _model(_active_doc(app))
    com_call(model, "ClearSelection2", True)
    com_call(feat, "Select2", False, 0)
    com_call(model, "DeleteSelection", False)


# ------------------------------------------------------- corte ao longo de eixo

def _plane_through_axis(app: Any, start: Sequence[float], direction: Sequence[float],
                        prefer: str | None) -> tuple[str, bool, ports.AxisPlane]:
    """Plano (base ou paralelo novo) que contém o eixo; devolve (nome, criado, geometria)."""
    geo = ports.axis_plane(start, direction, prefer)
    base = base_planes(app)[geo.base]
    if abs(geo.offset_mm) < 1e-9:
        return base, False, geo
    nome = modeling.reference_plane_offset(app, base, abs(geo.offset_mm), flip=geo.offset_mm < 0)
    return nome, True, geo


def revolved_axis_cut(app: Any, name: str, start: Sequence[float], direction: Sequence[float],
                      profile: Sequence[tuple[float, float]], prefer_plane: str | None = None) -> dict[str, Any]:
    """Corte por revolução do meio-perfil (s, r) em torno do eixo start + s·direction.

    O esboço fica num plano que contém o eixo, totalmente definido, e o corte
    é conferido: volume removido > 0 e feature sem erro — senão é desfeito e
    nada fica na peça.
    """
    d = ports.normalize(direction)
    volume_antes = holes._volume_mm3(app)
    plano, criado, geo = _plane_through_axis(app, start, d, prefer_plane)
    pontos_modelo = ports.profile_to_model(start, d, geo.radial, profile)
    try:
        modeling.insert_sketch(app, plano)
        if criado and abs(model_to_sketch(_active_sketch(app), start)[2]) > PLANE_TOLERANCE_MM:
            # o sentido do offset do plano paralelo depende do plano base: refaz do outro lado
            modeling.exit_sketch(app)
            _delete(app, _feature(app, plano))
            base = base_planes(app)[geo.base]
            plano = modeling.reference_plane_offset(app, base, abs(geo.offset_mm),
                                                    flip=geo.offset_mm >= 0)
            modeling.insert_sketch(app, plano)
        pts2d = _to_2d(app, pontos_modelo, name)
        modeling.sketch_polyline(app, pts2d, close_with_centerline=True)
        definicao = sd.fully_define_sketch(app)
        try:
            nome_feat = modeling.revolve(app, 360.0, cut=True)
        except ComCallError as exc:
            raise ComCallError(name, tuple(start), exc.hresult,
                               "o SolidWorks recusou o corte, que não removeu material — o eixo "
                               "está fora da peça? nada foi deixado no modelo") from exc
    except Exception:
        skm = com_get(_model(_active_doc(app)), "SketchManager")
        if com_get(skm, "ActiveSketch") is not None:
            modeling.exit_sketch(app)
            esboco = _last_feature(app)
            if com_call(esboco, "GetTypeName2") == "ProfileFeature":
                _delete(app, esboco)
        if criado:
            try:
                _delete(app, _feature(app, plano))
            except ComCallError:
                log.warning("plano auxiliar %s não foi removido", plano)
        raise
    feat = _feature(app, nome_feat)
    removido = volume_antes - holes._volume_mm3(app)
    codigo = _error_code(feat)
    if codigo != 0 or removido <= 1e-6:
        _delete(app, feat)
        if criado:
            _delete(app, _feature(app, plano))
        raise ComCallError(name, tuple(start), None,
                           f"o corte não removeu material (erro {codigo}, {removido:.3f}mm³) — "
                           "o eixo está fora da peça? nada foi deixado no modelo")
    feat.Name = name
    nome_plano = plano
    if criado:
        nome_plano = f"Plano {name}"
        _feature(app, plano).Name = nome_plano
        _hide_plane(app, nome_plano)
    teorico = ports.profile_volume_mm3(profile)
    log.info("corte ao longo do eixo %s: %.0fmm³ removidos (perfil %.0fmm³)", name, removido, teorico)
    return {"feature": name, "plane": nome_plano, "plane_created": criado,
            "removed_mm3": round(removido, 3), "profile_volume_mm3": round(teorico, 3),
            "direction": [round(c, 6) for c in d],
            "sketch_fully_defined": definicao.get("fully_defined"),
            "note": ("removeu menos que o perfil: ele cruza vazio que já existia ou começa fora da peça"
                     if removido < teorico * 0.98 else "")}


# ------------------------------------------------------------- face e normal

def face_normal_at(app: Any, point_mm: Sequence[float]) -> tuple[float, float, float]:
    """Normal PARA FORA da face plana que passa pelo ponto."""
    holes.select_face_at(app, *point_mm)
    model = _model(_active_doc(app))
    sel = cast_to(com_get(model, "SelectionManager"), "ISelectionMgr")
    face = cast_to(com_call(sel, "GetSelectedObject6", 1, -1), "IFace2")
    com_call(model, "ClearSelection2", True)
    surf = cast_to(com_call(face, "GetSurface"), "ISurface")
    if not com_call(surf, "IsPlane"):
        raise ComCallError("face_normal_at", tuple(point_mm), None, "a face no ponto não é plana")
    n = com_get(face, "Normal")
    return ports.normalize((n[0], n[1], n[2]))


def port_hole(app: Any, face_point_mm: Sequence[float], size: str, name: str = "",
              spot_depth_mm: float = 1.0, thread_drill_depth_mm: float | None = None,
              channel_diameter_mm: float = 0.0, channel_length_mm: float = 0.0,
              spot_diameter_mm: float | None = None) -> dict[str, Any]:
    """Pórtico G numa feature: rebaixo d2×a, broca da rosca até t e canal opcional.

    face_point_mm é o CENTRO do pórtico, em cima da face do bloco; o furo entra
    normal a ela. O perfil começa 5 mm fora: rebaixo que invade um ressalto
    corta o ressalto também.
    """
    normal = face_normal_at(app, face_point_mm)
    direcao = tuple(-c for c in normal)
    perfil = ports.port_profile(size, spot_depth_mm, thread_drill_depth_mm,
                                channel_diameter_mm, channel_length_mm,
                                spot_diameter=spot_diameter_mm)
    p = ports.pipe_port(size)
    nome = name or f"{p.size} Ø{spot_diameter_mm or p.d2:g}x{spot_depth_mm:g}"
    r = revolved_axis_cut(app, nome, face_point_mm, direcao, perfil)
    r["port"] = {"size": p.size, "d2": spot_diameter_mm or p.d2, "a": spot_depth_mm,
                 "thread_drill": p.tap_drill, "t": thread_drill_depth_mm or p.t,
                 "channel": [channel_diameter_mm, channel_length_mm] if channel_length_mm else None}
    return r


def angled_channel(app: Any, start_mm: Sequence[float], diameter_mm: float, name: str,
                   length_mm: float = 0.0, direction: Sequence[float] | None = None,
                   target_mm: Sequence[float] | None = None, overshoot_mm: float = 2.0,
                   extend_past_target_mm: float = 1.5) -> dict[str, Any]:
    """Canal furado de start_mm numa direção qualquer (dentro de um plano de vista).

    Diga para onde vai de um jeito: direction + length_mm, ou target_mm (o
    ponto que o canal precisa atingir — ele passa extend_past_target_mm além,
    para não terminar tangente a outro furo, que dá erro de reconstrução).
    """
    if target_mm is not None:
        vet = [target_mm[i] - start_mm[i] for i in range(3)]
        comprimento = sum(c * c for c in vet) ** 0.5 + extend_past_target_mm
        d = ports.normalize(vet)
    else:
        if direction is None or length_mm <= 0:
            raise ComCallError("angled_channel", (), None, "informe target_mm ou direction + length_mm")
        d = ports.normalize(direction)
        comprimento = length_mm
    perfil = ports.drill_profile(diameter_mm, comprimento, overshoot_mm)
    r = revolved_axis_cut(app, name, start_mm, d, perfil)
    r["length_mm"] = round(comprimento, 4)
    return r


# ------------------------------------------------- esboço em face por coordenadas

def sketch_on_face(app: Any, face_point_mm: Sequence[float],
                   polylines_mm: Sequence[Sequence[Sequence[float]]] = (),
                   circles_mm: Sequence[Sequence[float]] = (),
                   rectangles_mm: Sequence[Sequence[Sequence[float]]] = ()) -> dict[str, Any]:
    """Abre um esboço na face do ponto e desenha em COORDENADAS DA PEÇA.

    polylines_mm: contornos fechados [[x,y,z], ...]; circles_mm: [x,y,z,Ø];
    rectangles_mm: [[canto1], [canto2]]. Todo ponto precisa estar no plano da
    face. O esboço fica aberto para extrude (boss ou corte).
    """
    holes.select_face_at(app, *face_point_mm)
    model = _model(_active_doc(app))
    modeling._insert_sketch_retry(com_get(model, "SketchManager"), want_open=True)
    nome = com_call(_last_feature(app), "Name")
    try:
        for contorno in polylines_mm:
            modeling.sketch_polyline(app, _to_2d(app, contorno, "sketch_on_face"), close=True)
        for c in circles_mm:
            (x, y), = _to_2d(app, [c[:3]], "sketch_on_face")
            modeling.sketch_circle(app, x, y, float(c[3]))
        for a, b in rectangles_mm:
            (x1, y1), (x2, y2) = _to_2d(app, [a, b], "sketch_on_face")
            modeling.sketch_rectangle(app, x1, y1, x2, y2)
    except Exception:
        modeling.exit_sketch(app)
        raise
    return {"sketch": nome, "open": True,
            "shapes": len(polylines_mm) + len(circles_mm) + len(rectangles_mm)}


# ---------------------------------------------------------------- lote

def batch_holes(app: Any, items: Sequence[dict[str, Any]], stop_on_error: bool = False) -> dict[str, Any]:
    """Vários furos numa chamada, com o redesenho desligado.

    Cada item tem 'kind':
      'wizard'  → parâmetros de hole_wizard (face_x_mm..., depth_mm, size, ...)
                  + 'name' opcional para renomear a feature;
      'port'    → parâmetros de port_hole;
      'channel' → parâmetros de angled_channel.
    O resultado vem por item (ok/erro); stop_on_error para no primeiro erro.
    """
    resultados: list[dict[str, Any]] = []
    with suspended_graphics(app):
        for i, item in enumerate(items):
            params = dict(item)
            kind = params.pop("kind", "wizard")
            try:
                if kind == "wizard":
                    novo_nome = params.pop("name", "")
                    r = holes.hole_wizard(app, **params)
                    if novo_nome:
                        _feature(app, r["feature"]).Name = novo_nome
                        r["feature"] = novo_nome
                elif kind == "port":
                    r = port_hole(app, **params)
                elif kind == "channel":
                    r = angled_channel(app, **params)
                else:
                    raise ComCallError("batch_holes", (kind,), None, "kind deve ser wizard, port ou channel")
                resultados.append({"index": i, "ok": True, "feature": r.get("feature"),
                                   "warnings": r.get("warnings") or r.get("note") or None})
            except Exception as exc:  # noqa: BLE001 — o relatório por item é o produto
                resultados.append({"index": i, "ok": False, "kind": kind, "error": str(exc)[:300]})
                if stop_on_error:
                    break
    return {"items": resultados, "ok": sum(r["ok"] for r in resultados),
            "failed": sum(not r["ok"] for r in resultados)}


# ------------------------------------------------ filete, profundidade, troca

def fillet_circular_edges(app: Any, edges_mm: Sequence[Sequence[float]], radius_mm: float,
                          name: str = "") -> dict[str, Any]:
    """Filete de raio constante em várias arestas circulares, achadas pela
    geometria: edges_mm = [[cx, cy, cz, Ø], ...] (ex.: o R0,6 no fundo dos
    rebaixos Ø32 do detalhe Z)."""
    for i, e in enumerate(edges_mm):
        holes.select_circular_edge(app, [e[0], e[1], e[2]], float(e[3]), append=i > 0)
    antes = holes._volume_mm3(app)
    nome = modeling.fillet(app, float(radius_mm))
    feat = _feature(app, nome)
    if _error_code(feat) != 0:
        _delete(app, feat)
        raise ComCallError("fillet_circular_edges", (radius_mm,), None,
                           "o filete saiu com erro de reconstrução — nada foi deixado")
    if name:
        feat.Name = name
        nome = name
    return {"feature": nome, "edges": len(edges_mm),
            "volume_change_mm3": round(holes._volume_mm3(app) - antes, 3)}


def set_hole_depth(app: Any, feature_name: str, depth_mm: float) -> dict[str, Any]:
    """Muda a profundidade de um furo do assistente e confere que pegou e que
    o furo reconstrói sem erro (se não, volta a profundidade antiga)."""
    model = _model(_active_doc(app))
    feat = _feature(app, feature_name)
    d = cast_to(com_call(feat, "GetDefinition"), "IWizardHoleFeatureData2")
    antiga = com_get(d, "Depth")
    com_call(d, "AccessSelections", model, None)
    d.Depth = units.from_mm(depth_mm)
    if not com_call(feat, "ModifyDefinition", d, model, None):
        raise ComCallError("set_hole_depth", (feature_name, depth_mm), None, "o SolidWorks recusou a mudança")
    com_call(model, "ForceRebuild3", False)
    feat = _feature(app, feature_name)
    atual = units.to_mm(com_get(cast_to(com_call(feat, "GetDefinition"), "IWizardHoleFeatureData2"), "Depth"))
    codigo = _error_code(feat)
    if codigo != 0 or abs(atual - depth_mm) > 1e-4:
        d = cast_to(com_call(feat, "GetDefinition"), "IWizardHoleFeatureData2")
        com_call(d, "AccessSelections", model, None)
        d.Depth = antiga
        com_call(feat, "ModifyDefinition", d, model, None)
        raise ComCallError("set_hole_depth", (feature_name, depth_mm), None,
                           f"profundidade não aplicada (lida {atual:.3f}, erro {codigo}) — voltei a anterior. "
                           "Furo que termina tangente a outro dá erro 51: passe 1-2 mm")
    return {"feature": feature_name, "depth_mm": round(atual, 4),
            "previous_depth_mm": round(units.to_mm(antiga), 4)}


def replace_hole_with_channel(app: Any, hole_feature: str, start_mm: Sequence[float], diameter_mm: float,
                              name: str, length_mm: float = 0.0, direction: Sequence[float] | None = None,
                              target_mm: Sequence[float] | None = None) -> dict[str, Any]:
    """Troca um furo reto por um canal inclinado (angled_channel) NO MESMO
    LUGAR da árvore — o plano auxiliar e o canal entram onde o furo estava,
    dentro da mesma pasta. Se o canal falhar, o furo original fica."""
    model = _model(_active_doc(app))
    ordem = []
    raw = com_call(model, "FirstFeature")
    while raw is not None:
        f = cast_to(raw, "IFeature")
        ordem.append(com_call(f, "Name"))
        raw = com_call(f, "GetNextFeature")
    if hole_feature not in ordem:
        raise ComCallError("replace_hole_with_channel", (hole_feature,), None, "furo não existe")
    anterior = ordem[ordem.index(hole_feature) - 1]
    com_call(_feature(app, hole_feature), "SetSuppression2", 0, 2, None)   # suprime enquanto testa
    try:
        r = angled_channel(app, start_mm, diameter_mm, name, length_mm, direction, target_mm)
    except Exception:
        com_call(_feature(app, hole_feature), "SetSuppression2", 1, 2, None)
        raise
    _delete(app, _feature(app, hole_feature))
    ext = com_get(model, "Extension")
    if r["plane_created"]:
        com_call(ext, "ReorderFeature", r["plane"], anterior, 3)
        com_call(ext, "ReorderFeature", name, r["plane"], 3)
    else:
        com_call(ext, "ReorderFeature", name, anterior, 3)
    com_call(model, "ForceRebuild3", False)
    r["replaced"] = hole_feature
    return r
