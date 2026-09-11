"""Estruturas soldadas (weldments): catálogo de perfis e lista de corte.

Python puro — nada aqui toca COM. O wrapper ``com/wrappers/weldment.py``
alimenta estas funções com o que lê do SolidWorks e do disco.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

PROFILE_EXTENSION = ".sldlfp"


@dataclass(frozen=True)
class ProfileFile:
    """Um arquivo de perfil de weldment: <pasta>/<norma>/<tipo>.sldlfp.

    A partir do SolidWorks 2014 cada arquivo carrega os tamanhos como
    configurações ("20 x 20 x 2", "30 x 30 x 2.6"…), lidas via COM; em
    bibliotecas antigas o tamanho é o próprio nome do arquivo
    (<norma>/<tipo>/<tamanho>.sldlfp).
    """

    standard: str
    kind: str
    path: str
    sizes: tuple[str, ...] = field(default=())


def scan_profile_folders(folders: list[str]) -> list[ProfileFile]:
    """Percorre as pastas de perfis e devolve os .sldlfp em ordem estável.

    Aceita os dois layouts: ``<norma>/<tipo>.sldlfp`` (configurado) e
    ``<norma>/<tipo>/<tamanho>.sldlfp`` (legado; ``kind`` vira o nome da pasta
    e o arquivo entra como único ``size``).
    """
    found: list[ProfileFile] = []
    seen: set[str] = set()
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for standard in sorted(os.listdir(folder), key=str.lower):
            std_dir = os.path.join(folder, standard)
            if not os.path.isdir(std_dir):
                continue
            for entry in sorted(os.listdir(std_dir), key=str.lower):
                full = os.path.join(std_dir, entry)
                if os.path.isdir(full):
                    for size_file in sorted(os.listdir(full), key=str.lower):
                        if size_file.startswith("~$"):  # lock do SolidWorks, não é perfil
                            continue
                        if size_file.lower().endswith(PROFILE_EXTENSION):
                            p = os.path.join(full, size_file)
                            if _mark(p, seen):
                                found.append(ProfileFile(standard, entry, p, (size_file[: -len(PROFILE_EXTENSION)],)))
                elif entry.lower().endswith(PROFILE_EXTENSION) and not entry.startswith("~$"):
                    if _mark(full, seen):
                        found.append(ProfileFile(standard, entry[: -len(PROFILE_EXTENSION)], full))
    return found


def _mark(path: str, seen: set[str]) -> bool:
    key = os.path.normcase(os.path.abspath(path))
    if key in seen:
        return False
    seen.add(key)
    return True


def find_profile(catalog: list[ProfileFile], standard: str, kind: str, size: str | None = None) -> ProfileFile | None:
    """Busca sem diferenciar maiúsculas ('ISO'/'iso', 'Square Tube'/'square tube').

    No layout legado há um arquivo por tamanho: ``size`` escolhe o arquivo;
    no layout configurado o tamanho é configuração e ``size`` é ignorado aqui.
    """
    s, k = standard.strip().lower(), kind.strip().lower()
    z = size.strip().lower() if size else None
    fallback = None
    for p in catalog:
        if p.standard.lower() == s and p.kind.lower() == k:
            if not p.sizes or z is None or p.sizes[0].lower() == z:
                return p
            fallback = fallback or p
    return fallback


# ------------------------------------------------------------ lista de corte

# A UI em português renomeia as propriedades da lista de corte (COMPRIMENTO,
# ÂNGULO1, Descrição…), mas a fórmula guarda a chave canônica em inglês:
# '"LENGTH@@@PIPE 21,30 X 2.3<1>@Peça1.SLDPRT"'. É dela que sai a chave.
_FORMULA_KEY = re.compile(r'^"([A-Za-z][A-Za-z0-9 _\-]*)@@@')

# A fórmula de MATERIAL aponta para a propriedade interna SW-Material
_FORMULA_ALIASES = {"SW-MATERIAL": "MATERIAL"}

# Propriedades cuja fórmula não segue o padrão @@@ (nome localizado → chave)
_LOCALIZED_KEYS = {
    "descrição": "DESCRIPTION",
    "description": "DESCRIPTION",
    "comprimento": "LENGTH",
    "ângulo1": "ANGLE1",
    "ângulo2": "ANGLE2",
    "direção do ângulo": "ANGLE DIRECTION",
    "rotação do ângulo": "ANGLE ROTATION",
    "material": "MATERIAL",
    "quantidade": "QUANTITY",
}


def canonical_property_key(name: str, formula: str) -> str:
    """Chave canônica (inglês, maiúsculas) de uma propriedade da lista de corte."""
    m = _FORMULA_KEY.match(formula or "")
    if m:
        key = m.group(1).strip().upper()
        return _FORMULA_ALIASES.get(key, key)
    return _LOCALIZED_KEYS.get(name.strip().lower(), name.strip().upper())


def parse_number(value: str | None) -> float | None:
    """'300' → 300.0; '0°' → 0.0; '12,5' → 12.5; '-' / '' → None."""
    if value is None:
        return None
    txt = value.strip().replace("°", "").replace("mm", "").strip()
    if txt in ("", "-"):
        return None
    txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def normalize_cut_list_item(
    name: str,
    raw_properties: dict[str, tuple[str, str]],
    bodies: int,
    body_names: list[str] | None = None,
) -> dict[str, Any]:
    """Monta o item da lista de corte a partir das propriedades brutas.

    ``raw_properties``: {nome como aparece no SW: (fórmula, valor resolvido)}.
    Números (comprimento, ângulos, quantidade) saem convertidos; o texto
    original fica em ``properties`` sob a chave canônica — nada é descartado.
    """
    props: dict[str, str] = {}
    for raw_name, (formula, resolved) in raw_properties.items():
        props[canonical_property_key(raw_name, formula)] = resolved
    return {
        "name": name,
        "description": props.get("DESCRIPTION"),
        "quantity": _as_int(parse_number(props.get("QUANTITY"))) if "QUANTITY" in props else bodies,
        "length": parse_number(props.get("LENGTH")),
        "total_length": parse_number(props.get("TOTAL LENGTH")),
        "angle1_deg": parse_number(props.get("ANGLE1")),
        "angle2_deg": parse_number(props.get("ANGLE2")),
        "material": props.get("MATERIAL"),
        "bodies": bodies,
        "body_names": list(body_names or []),
        "properties": props,
    }


def _as_int(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


# ------------------------------------------------------------ corte normal ao tubo

def _wrap_deg(a: float) -> float:
    """Normaliza ângulo para (-180, 180]."""
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def _periodic_interp(samples: list[tuple[float, float]], angle: float) -> float:
    """Interpola s(ângulo) numa curva fechada amostrada em (ângulo_deg, s)."""
    pts = sorted((_wrap_deg(a), s) for a, s in samples)
    ext = [(a - 360.0, s) for a, s in pts] + pts + [(a + 360.0, s) for a, s in pts]
    for (a1, s1), (a2, s2) in zip(ext, ext[1:]):
        if a1 <= angle <= a2:
            return s1 if a2 == a1 else s1 + (s2 - s1) * (angle - a1) / (a2 - a1)
    return pts[0][1]


def angular_gap_deg(samples: list[tuple[float, float]]) -> float:
    """Maior lacuna angular entre amostras consecutivas (0 = cobre os 360°)."""
    if len(samples) < 2:
        return 360.0
    angles = sorted(_wrap_deg(a) for a, _ in samples)
    gaps = [b - a for a, b in zip(angles, angles[1:])]
    gaps.append(angles[0] + 360.0 - angles[-1])
    return max(gaps)


def combine_outlines(
    outlines: list[list[tuple[float, float]]],
    toward: float,
    step_deg: float = 1.0,
) -> list[tuple[float, float]]:
    """Contorno radial do corte a laser: em cada ângulo, o mais recuado.

    ``outlines``: contornos da boca (interno e externo) como (ângulo_deg, s),
    s = coordenada ao longo do eixo do tubo. ``toward``: sinal de s em que o
    corpo do tubo está (+1 → o tubo cresce para +s). "Mais recuado" = mais
    para dentro do tubo, para o corte nunca invadir a outra peça.
    Devolve (ângulo, s) numa grade de -180 a 180 (extremos repetidos).
    """
    if not outlines or toward == 0:
        raise ValueError("preciso de ao menos um contorno e do sentido do tubo")
    pick = max if toward > 0 else min
    n = int(round(360.0 / step_deg))
    out = []
    for i in range(n + 1):
        a = -180.0 + i * step_deg
        out.append((a, pick(_periodic_interp(o, a) for o in outlines)))
    return out
