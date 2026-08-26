"""Conversões da fronteira m/rad → mm/graus."""

import math

from swmcp.com import units


def test_ida_e_volta_mm():
    assert units.to_mm(0.0125) == 12.5
    assert units.from_mm(12.5) == 0.0125


def test_ida_e_volta_graus():
    assert units.to_deg(math.pi) == 180.0
    assert math.isclose(units.from_deg(90.0), math.pi / 2)


def test_round_mm_cobre_micron():
    assert units.round_mm(0.0123456789) == 12.3457
