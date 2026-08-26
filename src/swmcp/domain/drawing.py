"""DTOs do dump de desenho (RF-03). Unidades: mm e graus, sempre.

O dump é um documento serializável — objetos COM nunca vazam para cá.
Tudo que a leitura não reconhecer entra em ``unrecognized`` com o tipo bruto
(R4): nunca omitir silenciosamente.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Tolerance(_Frozen):
    """Tolerância de uma cota. Valores em mm (ou graus, se a cota for angular)."""

    type: str  # ex.: NONE, BASIC, BILATERAL, SYMMETRIC, LIMIT, FIT, MIN, MAX
    max_variation: float | None = None
    min_variation: float | None = None


class Dimension(_Frozen):
    name: str
    full_name: str  # ex.: "D1@Esboço1@peca.SLDPRT"
    value: float  # mm (linear) ou graus (angular)
    unit: str  # "mm" | "deg"
    text: str  # texto exibido, com prefixo/sufixo (ex.: "⌀12,5 H7")
    tolerance: Tolerance
    is_inspection: bool = False  # cota marcada para inspeção (balão)
    is_reference: bool = False  # cota de referência (entre parênteses)
    view: str | None = None  # nome da vista onde aparece


class Annotation(_Frozen):
    """Anotação genérica: GD&T, acabamento, solda, datum, nota."""

    kind: str  # "gtol" | "surface_finish" | "weld_symbol" | "datum" | "note" | ...
    text: str
    view: str | None = None
    data: dict[str, str | float | bool | None] = {}  # campos específicos do tipo


class Note(_Frozen):
    name: str
    text: str
    view: str | None = None


class TableCell(_Frozen):
    row: int
    column: int
    text: str


class Table(_Frozen):
    kind: str  # "revision" | "hole" | "bom" | "general"
    title: str
    rows: int
    columns: int
    cells: list[TableCell]


class View(_Frozen):
    name: str
    type: str  # "standard" | "projected" | "section" | "detail" | ... | "desconhecido(n)"
    model_path: str | None = None
    configuration: str | None = None
    scale: str | None = None  # "1:2"
    dimensions: list[Dimension] = []
    annotations: list[Annotation] = []
    notes: list[Note] = []


class Sheet(_Frozen):
    name: str
    format_name: str | None = None  # template de folha (formato Gromar)
    scale: str | None = None
    size: str | None = None  # "A3", "A4"… ou dimensão bruta
    views: list[View] = []
    notes: list[Note] = []  # notas soltas na folha (fora de vista)
    tables: list[Table] = []


class Unrecognized(_Frozen):
    """Item que a leitura encontrou mas não soube mapear (R4)."""

    where: str  # ex.: "sheet:Folha1"
    raw_type: int | str
    detail: str | None = None


class DrawingDump(_Frozen):
    """Dump completo de um .SLDDRW — o coração do O1."""

    path: str
    title: str
    custom_properties: dict[str, str] = {}  # propriedades do desenho (legenda)
    referenced_models: list[str] = []
    sheets: list[Sheet] = []
    unrecognized: list[Unrecognized] = []
