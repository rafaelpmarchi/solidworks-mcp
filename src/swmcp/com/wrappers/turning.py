"""Recursos de peça torneada: canal de alívio e rebaixo plano (escrita).

São dois recursos que aparecem em quase toda haste/eixo e que, feitos à mão,
saem errados de um jeito que não salta aos olhos na tela:

- o canal de saída de rosca é um trapézio com rampas em ângulo e RAIO no fundo,
  não um rasgo de cantos vivos;
- o rebaixo plano (o "flatting" para chave) precisa varrer TODO o trecho com
  diâmetro maior que o entre-faces. Parar na face do colar deixa um dente no
  cone vizinho, que continua com diâmetro maior que a medida entre faces.

Por isso groove_relief já põe os raios do fundo e flats_across mede o corpo para
achar sozinho até onde cortar, conferindo no fim que não sobrou material.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.session import cast_to, swconst
from swmcp.com.wrappers import holes, modeling

log = logging.getLogger(__name__)

# Eixo de revolução destas tools: X do modelo (é onde nasce um perfil desenhado
# no plano frontal com a linha de centro em y=0).
AXIS = 0
RADIAL = (1, 2)  # Y e Z

# Folga radial para o perfil do corte sair do material com sobra.
OVERSHOOT_MM = 10.0
# Até onde a extensão automática do rebaixo pode ir além do pedido.
MAX_EXTEND_FACTOR = 4.0


def _model(app: Any) -> Any:
    doc = com_get(app, "ActiveDoc")
    if doc is None:
        raise ComCallError("ActiveDoc", (), None, "nenhum documento ativo no SolidWorks")
    return cast_to(doc, "IModelDoc2")


def _faces(app: Any) -> list[Any]:
    saida = []
    for raw_body in holes._bodies(app):  # noqa: SLF001 — mesmo pacote, evita duplicar
        body = cast_to(raw_body, "IBody2")
        saida.extend(com_call(body, "GetFaces") or [])
    return saida


def _face_box_mm(face: Any) -> list[float]:
    return [units.to_mm(v) for v in com_call(cast_to(face, "IFace2"), "GetBox")]


def _face_axial_span(box: list[float]) -> tuple[float, float]:
    return box[AXIS], box[AXIS + 3]


def _face_max_radius(box: list[float]) -> float:
    """Maior distância ao eixo dentro da caixa da face (aproximação segura)."""
    return max(abs(box[i]) for i in (*RADIAL, RADIAL[0] + 3, RADIAL[1] + 3))


def _face_max_across(box: list[float]) -> float:
    """Maior afastamento na DIREÇÃO DO REBAIXO (Y), que é o que o entre-faces mede.

    Não confundir com o raio: depois do rebaixo o cilindro do colar continua
    existindo nas laterais, com o raio inteiro — o que tem de caber na medida é
    só o afastamento em Y.
    """
    return max(abs(box[RADIAL[0]]), abs(box[RADIAL[0] + 3]))


def radius_at(app: Any, z_mm: float) -> float:
    """Raio externo do corpo na seção z (mm), medido pela face mais próxima."""
    alvo = [0.0, 0.0, 0.0]
    alvo[AXIS] = units.from_mm(z_mm)
    alvo[RADIAL[0]] = units.from_mm(1e4)  # bem fora da peça, na direção radial
    melhor = None
    for raw_face in _faces(app):
        perto = com_call(cast_to(raw_face, "IFace2"), "GetClosestPointOn", *alvo)
        if not perto:
            continue
        # só interessa quem responde na seção pedida
        if abs(units.to_mm(perto[AXIS]) - z_mm) > 1e-3:
            continue
        raio = math.hypot(units.to_mm(perto[RADIAL[0]]), units.to_mm(perto[RADIAL[1]]))
        if melhor is None or raio > melhor:
            melhor = raio
    if melhor is None:
        raise ComCallError("radius_at", (z_mm,), None,
                           f"não achei material do corpo na seção x={z_mm}mm")
    return melhor


# ------------------------------------------------------------ canal de alívio

def groove_relief(
    app: Any,
    z_start_mm: float,
    z_end_mm: float,
    groove_diameter_mm: float,
    ramp_angle_deg: float = 60.0,
    corner_radius_mm: float = 0.0,
    outer_diameter_start_mm: float = 0.0,
    outer_diameter_end_mm: float = 0.0,
) -> dict[str, Any]:
    """Canal de alívio/saída de rosca por corte de revolução.

    z_start/z_end são onde o canal encontra a superfície externa (é assim que o
    desenho cota a largura); ramp_angle é o ângulo das rampas COM O EIXO;
    corner_radius arredonda os dois cantos do fundo depois do corte.
    Os diâmetros externos de cada lado são medidos do corpo se não vierem.
    """
    if z_end_mm <= z_start_mm:
        raise ComCallError("groove_relief", (z_start_mm, z_end_mm), None,
                           "z_end_mm tem que ser maior que z_start_mm")
    if not 1.0 < ramp_angle_deg < 179.0:
        raise ComCallError("groove_relief", (ramp_angle_deg,), None,
                           "ramp_angle_deg fora de 1..179")
    r_fundo = groove_diameter_mm / 2.0
    r1 = (outer_diameter_start_mm / 2.0) if outer_diameter_start_mm else radius_at(app, z_start_mm)
    r2 = (outer_diameter_end_mm / 2.0) if outer_diameter_end_mm else radius_at(app, z_end_mm)
    if r_fundo >= min(r1, r2):
        raise ComCallError("groove_relief", (groove_diameter_mm, r1 * 2, r2 * 2), None,
                           f"o canal Ø{groove_diameter_mm} não é menor que o material "
                           f"(Ø{r1 * 2:.2f} e Ø{r2 * 2:.2f} nas bordas)")
    tan = math.tan(math.radians(ramp_angle_deg))
    z_fundo_ini = z_start_mm + (r1 - r_fundo) / tan
    z_fundo_fim = z_end_mm - (r2 - r_fundo) / tan
    if z_fundo_fim <= z_fundo_ini:
        raise ComCallError(
            "groove_relief", (z_start_mm, z_end_mm, ramp_angle_deg), None,
            f"as rampas de {ramp_angle_deg}° se cruzam antes do fundo — o canal precisa "
            f"de pelo menos {(r1 - r_fundo) / tan + (r2 - r_fundo) / tan:.2f}mm de largura",
        )
    # As rampas seguem além da superfície até r_fora: um vértice do perfil em
    # cima da própria superfície do sólido faz o corte de revolução ser
    # rejeitado sem explicação (medido no SW2023). Prolongadas, elas cruzam a
    # superfície exatamente em z_start/z_end, que é a largura que o desenho cota.
    r_fora = max(r1, r2) + OVERSHOOT_MM
    perfil = [
        [z_start_mm - (r_fora - r1) / tan, r_fora],
        [z_fundo_ini, r_fundo],
        [z_fundo_fim, r_fundo],
        [z_end_mm + (r_fora - r2) / tan, r_fora],
    ]
    modeling.insert_sketch(app, "Plano frontal")
    modeling.sketch_polyline(app, perfil, close=True)
    modeling.sketch_line(app, perfil[-1][0], 0.0, perfil[0][0], 0.0, centerline=True)
    corte = modeling.revolve(app, 360.0, cut=True)

    filete = None
    if corner_radius_mm > 0:
        for i, z in enumerate((z_fundo_ini, z_fundo_fim)):
            holes.select_circular_edge(app, [z, 0.0, 0.0], groove_diameter_mm, append=i > 0)
        filete = modeling.fillet(app, corner_radius_mm)
    log.info("canal de alívio %s: Ø%.2f de x=%.2f a %.2f, rampas %.1f°",
             corte, groove_diameter_mm, z_start_mm, z_end_mm, ramp_angle_deg)
    return {"feature": corte, "fillet": filete,
            "outer_diameter_start_mm": round(r1 * 2, 4),
            "outer_diameter_end_mm": round(r2 * 2, 4),
            "flat_bottom_mm": [round(z_fundo_ini, 4), round(z_fundo_fim, 4)]}


# ------------------------------------------------------------- rebaixo plano

def _span_with_material(app: Any, meia_altura: float, z_start: float, z_end: float,
                        limite: float) -> tuple[float, float, list[str]]:
    """Estende [z_start, z_end] enquanto houver face com raio acima do plano.

    O corte só tira o que passa do plano, então esticar demais não faz mal —
    parar cedo é que deixa dente. Cresce por faces que encostam no trecho.
    """
    avisos: list[str] = []
    ini, fim = z_start, z_end
    for _ in range(20):  # propaga até estabilizar
        cresceu = False
        for raw_face in _faces(app):
            box = _face_box_mm(raw_face)
            a, b = _face_axial_span(box)
            if b < ini - 1e-6 or a > fim + 1e-6:      # não encosta no trecho
                continue
            if _face_max_across(box) <= meia_altura + 1e-6:  # não passa do plano
                continue
            if a < ini - 1e-6:
                ini, cresceu = a, True
            if b > fim + 1e-6:
                fim, cresceu = b, True
        if not cresceu:
            break
        if fim - ini > limite:
            avisos.append(
                f"o material acima do plano passa de {limite:.1f}mm a partir do trecho pedido; "
                f"cortei de x={ini:.2f} a {fim:.2f} — confira se é isso mesmo")
            break
    return ini, fim, avisos


def flats_across(
    app: Any,
    across_flats_mm: float,
    z_start_mm: float,
    z_end_mm: float,
    auto_extend: bool = True,
) -> dict[str, Any]:
    """Rebaixo plano dos dois lados (entre-faces) num trecho do eixo.

    across_flats_mm é a medida ENTRE AS FACES (o "110-0,35" do desenho), z_start
    e z_end o trecho axial. Com auto_extend, o trecho cresce sozinho enquanto
    houver material acima do plano — é o que evita deixar um dente no cone ou no
    raio vizinho ao colar. No fim confere que nada sobrou acima do plano.
    """
    if across_flats_mm <= 0:
        raise ComCallError("flats_across", (across_flats_mm,), None, "entre-faces tem que ser > 0")
    if z_end_mm <= z_start_mm:
        raise ComCallError("flats_across", (z_start_mm, z_end_mm), None,
                           "z_end_mm tem que ser maior que z_start_mm")
    meia = across_flats_mm / 2.0
    limite = (z_end_mm - z_start_mm) * MAX_EXTEND_FACTOR
    avisos: list[str] = []
    ini, fim = z_start_mm, z_end_mm
    if auto_extend:
        ini, fim, avisos = _span_with_material(app, meia, z_start_mm, z_end_mm, limite)

    maior_raio = max((_face_max_across(_face_box_mm(f)) for f in _faces(app)), default=0.0)
    if maior_raio <= meia:
        raise ComCallError("flats_across", (across_flats_mm,), None,
                           f"nada a cortar: o corpo não passa de Ø{maior_raio * 2:.2f} "
                           f"e o entre-faces pedido é {across_flats_mm}")
    fora = maior_raio + OVERSHOOT_MM

    features = []
    for reverse in (False, True):   # os dois lados do plano do sketch
        modeling.insert_sketch(app, "Plano frontal")
        for sinal in (1.0, -1.0):
            modeling.sketch_rectangle(app, ini, sinal * meia, fim, sinal * fora)
        features.append(modeling.extrude(app, fora, cut=True, through_all=True,
                                         reverse_direction=reverse))

    sobra = [round(_face_max_across(_face_box_mm(f)) * 2, 3) for f in _faces(app)
             if _face_axial_span(_face_box_mm(f))[0] >= ini - 1e-6
             and _face_axial_span(_face_box_mm(f))[1] <= fim + 1e-6
             and _face_max_across(_face_box_mm(f)) > meia + 0.01]
    if sobra:
        avisos.append(f"ainda há face passando do entre-faces no trecho (Ø{max(sobra)}) — "
                      "veja se o corte precisa de outro trecho")
    log.info("rebaixo %.2f entre faces de x=%.2f a %.2f (pedido %.2f..%.2f)",
             across_flats_mm, ini, fim, z_start_mm, z_end_mm)
    return {"features": features, "across_flats_mm": across_flats_mm,
            "span_mm": [round(ini, 4), round(fim, 4)],
            "extended": [round(ini, 4), round(fim, 4)] != [round(z_start_mm, 4), round(z_end_mm, 4)],
            "warnings": avisos}
