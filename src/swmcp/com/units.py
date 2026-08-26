"""Conversão de unidades na fronteira (RNF-03).

A API do SolidWorks trabalha em metros e radianos; tudo que sai para o agente
é milímetro e grau. Este é o ÚNICO módulo do projeto que faz essa conversão.
"""

from __future__ import annotations

import math

M_TO_MM = 1000.0


def to_mm(meters: float) -> float:
    """Metros (API SolidWorks) → milímetros (agente)."""
    return meters * M_TO_MM


def from_mm(mm: float) -> float:
    """Milímetros (agente) → metros (API SolidWorks)."""
    return mm / M_TO_MM


def to_deg(radians: float) -> float:
    """Radianos (API SolidWorks) → graus (agente)."""
    return math.degrees(radians)


def from_deg(degrees: float) -> float:
    """Graus (agente) → radianos (API SolidWorks)."""
    return math.radians(degrees)


def round_mm(meters: float, digits: int = 4) -> float:
    """Metros → mm arredondado para exibição (4 casas cobre mícron)."""
    return round(to_mm(meters), digits)
