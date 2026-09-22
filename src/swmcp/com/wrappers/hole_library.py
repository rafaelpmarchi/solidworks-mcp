"""Biblioteca de furos do SolidWorks (a base do assistente de furação).

A base fica em `<pasta do Hole Wizard>/swbrowser.sldedb` — um SQLite com uma
tabela por norma e tipo (AM_DATA_HW_TappedHole, ISO_DATA_HW_TapDrills, ...).
Lida SEMPRE somente-leitura: é arquivo de instalação do SolidWorks.

Serve para resolver um tamanho de norma ("M20x2.5" em Ansi Metric) nos números
que a geometria precisa — Ø da broca e passo. A API HoleWizard5 valida o nome
do tamanho contra esta mesma base, mas não aplica as dimensões dela: por isso o
wrapper de furo confere o resultado e refaz com estes números quando preciso.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from swmcp.com.invoke import ComCallError, com_call
from swmcp.com.session import swconst

log = logging.getLogger(__name__)

DB_FILENAME = "swbrowser.sldedb"

# norma → (prefixo das tabelas, nome do enum swStandards_e)
STANDARDS = {
    "Ansi Metric": ("AM", "swStandardAnsiMetric"),
    "ISO": ("ISO", "swStandardISO"),
    "DIN": ("DIN", "swStandardDIN"),
    "JIS": ("JIS", "swStandardJIS"),
    "Ansi Inch": ("AI", "swStandardAnsiInch"),
}

# tipo de furo → (sufixo da tabela de tamanhos, sufixo do enum do tipo)
HOLE_TABLES = {
    "tap": ("DATA_HW_TappedHole", "TappedHole"),
    "simple": ("DATA_HW_DrillSizes", "DrillSizes"),
}


def database_path(app: Any) -> Path:
    """Caminho da base, lido das opções do SolidWorks (Furo/Toolbox)."""
    pasta = com_call(app, "GetUserPreferenceStringValue", swconst().swHoleWizardToolBoxFolder)
    if not pasta:
        raise ComCallError("swHoleWizardToolBoxFolder", (), None,
                           "o SolidWorks não tem pasta do assistente de furação configurada")
    caminho = Path(pasta) / DB_FILENAME
    if not caminho.exists():
        raise ComCallError("hole_library", (str(caminho),), None,
                           f"base do assistente de furação não encontrada em {caminho}")
    return caminho


def _connect(path: Path) -> sqlite3.Connection:
    # somente-leitura: a base é arquivo de instalação e pode estar aberta pelo SolidWorks
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _table(conn: sqlite3.Connection, prefixo: str, sufixo: str) -> str | None:
    alvo = f"{prefixo}_{sufixo}".lower()
    for (nome,) in conn.execute("select name from sqlite_master where type='table'"):
        if nome.lower() == alvo:
            return nome
    return None


def _rows(conn: sqlite3.Connection, tabela: str) -> list[dict[str, Any]]:
    cur = conn.execute(f'select * from "{tabela}"')  # noqa: S608 — nome vindo do sqlite_master
    colunas = [d[0] for d in cur.description]
    return [dict(zip(colunas, linha)) for linha in cur.fetchall()]


def _float(valor: Any) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def list_sizes(app: Any, standard: str = "Ansi Metric", hole_type: str = "tap") -> list[dict[str, Any]]:
    """Tamanhos da biblioteca para a norma e o tipo (como o diálogo os lista)."""
    if standard not in STANDARDS:
        raise ComCallError("list_sizes", (standard,), None,
                           f"norma deve ser uma de {sorted(STANDARDS)}")
    if hole_type not in HOLE_TABLES:
        raise ComCallError("list_sizes", (hole_type,), None,
                           f"tipo deve ser um de {sorted(HOLE_TABLES)}")
    prefixo = STANDARDS[standard][0]
    sufixo = HOLE_TABLES[hole_type][0]
    with _connect(database_path(app)) as conn:
        tabela = _table(conn, prefixo, sufixo)
        if tabela is None:
            return []
        brocas = {}
        tab_brocas = _table(conn, prefixo, "DATA_HW_TapDrills")
        if tab_brocas:
            for linha in _rows(conn, tab_brocas):
                brocas[str(linha.get("SIZE"))] = _float(linha.get("TAP_DRILL"))
        saida = []
        for linha in _rows(conn, tabela):
            if not linha.get("enabled", 1):
                continue
            tamanho = str(linha.get("SIZE"))
            saida.append({
                "size": tamanho,
                "nominal_diameter_mm": _float(linha.get("DIAMETER")),
                "pitch_mm": _float(linha.get("Pitch")),
                "drill_diameter_mm": brocas.get(tamanho) or _float(linha.get("DIAMETER")),
            })
    return saida


def resolve_size(app: Any, size: str, standard: str = "Ansi Metric",
                 hole_type: str = "tap") -> dict[str, Any]:
    """Dimensões de um tamanho da biblioteca; erro listando alternativas se não existir."""
    tamanhos = list_sizes(app, standard, hole_type)
    for item in tamanhos:
        if item["size"].lower() == size.strip().lower():
            if item["drill_diameter_mm"] is None:
                raise ComCallError("resolve_size", (size, standard), None,
                                   f"{size} existe na biblioteca mas sem diâmetro de broca")
            return {**item, "standard": standard, "hole_type": hole_type,
                    "standard_index": getattr(swconst(), STANDARDS[standard][1])}
    parecidos = [i["size"] for i in tamanhos if size.strip().lower()[:3] in i["size"].lower()]
    raise ComCallError(
        "resolve_size", (size, standard, hole_type), None,
        f"{size} não está na biblioteca de {standard}/{hole_type}"
        + (f" — parecidos: {parecidos[:8]}" if parecidos else "")
        + " (list_hole_sizes mostra todos; dá para acrescentar pelo assistente de furação)",
    )


def fastener_type_index(standard: str, hole_type: str) -> int:
    """Enum swWzdHoleStandardFastenerTypes_e do par norma/tipo."""
    prefixo_enum = {"Ansi Metric": "swStandardAnsiMetric", "ISO": "swStandardISO",
                    "DIN": "swStandardDIN", "JIS": "swStandardJIS",
                    "Ansi Inch": "swStandardAnsiInch"}[standard]
    nome = prefixo_enum + HOLE_TABLES[hole_type][1]
    valor = getattr(swconst(), nome, None)
    if valor is None:
        raise ComCallError("fastener_type_index", (standard, hole_type), None,
                           f"a API não tem o tipo {nome}")
    return valor
