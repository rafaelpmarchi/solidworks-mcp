"""Leitura completa de desenho (RF-03). Executa dentro do thread STA.

Percorre a cadeia de vistas do IDrawingDoc; a vista de formato de folha
(type=1) carrega as notas da legenda. Tudo que não for reconhecido entra em
``unrecognized`` com o tipo bruto (R4).
"""

from __future__ import annotations

import logging
import math
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import cast_to
from swmcp.domain.drawing import (
    Annotation,
    Dimension,
    DrawingDump,
    Note,
    Sheet,
    Table,
    TableCell,
    Tolerance,
    Unrecognized,
    View,
)

log = logging.getLogger(__name__)

# swAnnotationType_e — 1/4/6/13 confirmados empiricamente no SW2023 (desenho
# Gromar); demais conforme documentação da API
ANNOTATION_KINDS = {
    1: "cosmetic_thread",
    2: "datum_tag",
    3: "datum_target",
    4: "display_dimension",  # já coberta pela lista de cotas — não duplicar
    5: "gtol",
    6: "note",
    7: "surface_finish",
    8: "weld_symbol",
    13: "center_mark",  # swCenterMarkSym (swconst)
}

# swDrawingViewTypes_e
VIEW_TYPES = {
    1: "sheet_format",
    2: "section",
    3: "detail",
    4: "projected",
    5: "auxiliary",
    6: "standard",
    7: "named",
    8: "relative",
}

# swTolType_e
TOLERANCE_TYPES = {
    0: "NONE",
    1: "BASIC",
    2: "BILATERAL",
    3: "LIMIT",
    4: "SYMMETRIC",
    5: "MIN",
    6: "MAX",
    7: "METRIC",
    8: "FIT",
    9: "FIT_WITH_TOLERANCE",
    10: "FIT_TOLERANCE_ONLY",
}


def read_drawing(doc: Any, path: str) -> DrawingDump:
    """Monta o DrawingDump de um documento de desenho JÁ aberto."""
    model = cast_to(doc, "IModelDoc2")
    dwg = cast_to(doc, "IDrawingDoc")

    unrecognized: list[Unrecognized] = []
    custom_props = read_custom_properties(model, "")

    sheet_names = list(com_call(dwg, "GetSheetNames") or ())
    sheets_meta = {name: _sheet_meta(dwg, name) for name in sheet_names}

    # A cadeia GetFirstView/GetNextView atravessa todas as folhas; a vista de
    # formato (type=1) abre cada folha e tem o nome dela.
    sheets: dict[str, dict] = {n: {"views": [], "notes": [], "tables": []} for n in sheet_names}
    current_sheet = sheet_names[0] if sheet_names else ""
    referenced_models: set[str] = set()

    raw_view = com_call(dwg, "GetFirstView")
    while raw_view is not None:
        view = cast_to(raw_view, "IView")
        vname = com_call(view, "GetName2")
        vtype = com_call(view, "GetType") if callable(getattr(view, "GetType", None)) else com_get(view, "Type")

        if vtype == 1:  # formato de folha: notas são a legenda da folha
            if vname in sheets:
                current_sheet = vname
            bucket = sheets.get(current_sheet)
            if bucket is not None:
                notes, anns, unrec = _read_annotations(view, vname, unrecognized_where=f"sheet:{current_sheet}")
                bucket["notes"].extend(notes)
                bucket["tables"].extend(_read_tables(view, current_sheet, unrecognized))
                unrecognized.extend(unrec)
        else:
            dims, dim_unrec = _read_dimensions(view, vname)
            notes, anns, ann_unrec = _read_annotations(view, vname, unrecognized_where=f"view:{vname}")
            unrecognized.extend(dim_unrec)
            unrecognized.extend(ann_unrec)
            model_path = com_call(view, "GetReferencedModelName") or None
            if model_path:
                referenced_models.add(model_path)
            bucket = sheets.get(current_sheet)
            if bucket is not None:
                bucket["tables"].extend(_read_tables(view, current_sheet, unrecognized))
                bucket["views"].append(
                    View(
                        name=vname,
                        type=VIEW_TYPES.get(vtype, f"desconhecido({vtype})"),
                        model_path=model_path,
                        configuration=com_get(view, "ReferencedConfiguration") or None,
                        scale=_scale_str(com_get(view, "ScaleRatio")),
                        dimensions=dims,
                        annotations=anns,
                        notes=notes,
                    )
                )

        raw_view = com_call(view, "GetNextView")

    sheet_dtos = []
    for name in sheet_names:
        meta = sheets_meta[name]
        sheet_dtos.append(
            Sheet(
                name=name,
                format_name=meta.get("format_name"),
                scale=meta.get("scale"),
                size=meta.get("size"),
                views=sheets[name]["views"],
                notes=sheets[name]["notes"],
                tables=sheets[name]["tables"],
            )
        )

    return DrawingDump(
        path=path,
        title=com_call(model, "GetTitle"),
        custom_properties=custom_props,
        referenced_models=sorted(referenced_models),
        sheets=sheet_dtos,
        unrecognized=unrecognized,
    )


def read_custom_properties(model: Any, config: str) -> dict[str, str]:
    ext = com_get(model, "Extension")
    cpm = com_call(ext, "CustomPropertyManager", config)
    props: dict[str, str] = {}
    for name in com_call(cpm, "GetNames") or ():
        value = com_call(cpm, "Get", name)
        props[name] = value if isinstance(value, str) else str(value)
    return props


def _sheet_meta(dwg: Any, name: str) -> dict[str, Any]:
    sheet = cast_to(com_call(dwg, "Sheet", name), "ISheet")
    props = com_call(sheet, "GetProperties2") or com_call(sheet, "GetProperties")
    meta: dict[str, Any] = {"format_name": None, "scale": None, "size": None}
    try:
        meta["format_name"] = com_call(sheet, "GetSheetFormatName") or None
    except Exception:  # noqa: BLE001 — nem toda versão expõe; não é fatal
        log.debug("GetSheetFormatName indisponível na folha %s", name)
    if props:
        p = list(props)
        # (paperSize, template, scale1, scale2, firstAngle, width_m, height_m, ...)
        if len(p) >= 7:
            meta["scale"] = _scale_str((p[2], p[3]))
            meta["size"] = f"{units.round_mm(p[5], 0):.0f}×{units.round_mm(p[6], 0):.0f}mm"
    return meta


def _scale_str(ratio: Any) -> str | None:
    try:
        a, b = ratio
        return f"{a:g}:{b:g}"
    except (TypeError, ValueError):
        return None


def _read_dimensions(view: Any, vname: str) -> tuple[list[Dimension], list[Unrecognized]]:
    dims: list[Dimension] = []
    unrec: list[Unrecognized] = []
    raw = com_call(view, "GetFirstDisplayDimension5")
    while raw is not None:
        dd = cast_to(raw, "IDisplayDimension")
        dim = cast_to(com_call(dd, "GetDimension2", 0), "IDimension")
        full_name = com_get(dim, "FullName")
        system_value = com_get(dim, "SystemValue")  # metros ou radianos
        doc_value = com_get(dim, "Value")  # unidade do documento (mm ou graus)

        # angular quando o valor do documento bate com a conversão para graus
        if system_value and math.isclose(doc_value, units.to_deg(system_value), rel_tol=1e-6):
            unit, value = "deg", round(units.to_deg(system_value), 4)
        else:
            unit, value = "mm", units.round_mm(system_value)

        text = " ".join(t for t in (_dim_text(dd, k) for k in (1, 2, 3, 4)) if t)
        dims.append(
            Dimension(
                name=full_name.split("@")[0],
                full_name=full_name,
                value=value,
                unit=unit,
                text=text,
                tolerance=_read_tolerance(dim, unit),
                is_inspection=bool(_maybe(dd, "Inspection", False)),
                view=vname,
            )
        )
        raw = com_call(dd, "GetNext5")
    return dims, unrec


def _dim_text(dd: Any, kind: int) -> str:
    try:
        return com_call(dd, "GetText", kind) or ""
    except Exception:  # noqa: BLE001
        return ""


def _maybe(obj: Any, prop: str, default: Any) -> Any:
    """Propriedade que pode não existir na versão — ausência NÃO é falha COM."""
    try:
        return com_get(obj, prop)
    except AttributeError:
        return default


def _read_tolerance(dim: Any, unit: str) -> Tolerance:
    tol = cast_to(com_get(dim, "Tolerance"), "IDimensionTolerance")
    tol_type = com_get(tol, "Type")
    max_v = _tol_value(com_call(tol, "GetMaxValue2"), unit)
    min_v = _tol_value(com_call(tol, "GetMinValue2"), unit)
    return Tolerance(
        type=TOLERANCE_TYPES.get(tol_type, f"desconhecido({tol_type})"),
        max_variation=max_v if tol_type != 0 else None,
        min_variation=min_v if tol_type != 0 else None,
    )


def _tol_value(raw: Any, unit: str) -> float | None:
    # early binding: (status, valor_em_metros_ou_radianos)
    if isinstance(raw, tuple):
        raw = raw[-1]
    if raw is None:
        return None
    return round(units.to_deg(raw), 4) if unit == "deg" else units.round_mm(raw)


def _read_annotations(
    view: Any, vname: str, unrecognized_where: str
) -> tuple[list[Note], list[Annotation], list[Unrecognized]]:
    notes: list[Note] = []
    anns: list[Annotation] = []
    unrec: list[Unrecognized] = []

    raw = com_call(view, "GetFirstAnnotation3")
    while raw is not None:
        ann = cast_to(raw, "IAnnotation")
        atype = com_call(ann, "GetType")
        aname = com_call(ann, "GetName")
        kind = ANNOTATION_KINDS.get(atype)

        if kind == "note":
            note = cast_to(com_call(ann, "GetSpecificAnnotation"), "INote")
            notes.append(Note(name=aname, text=com_call(note, "GetText") or "", view=vname))
        elif kind == "display_dimension":
            pass  # já enumerada em _read_dimensions
        elif kind is not None:
            anns.append(Annotation(kind=kind, text=aname, view=vname, data={"raw_type": atype}))
        else:
            unrec.append(Unrecognized(where=unrecognized_where, raw_type=atype, detail=aname))

        raw = com_call(ann, "GetNext3")
    return notes, anns, unrec


def _read_tables(view: Any, sheet_name: str, unrecognized: list[Unrecognized]) -> list[Table]:
    """Tabelas ancoradas na vista (revisão, furos, BOM) — nunca silencioso."""
    tables: list[Table] = []
    try:
        count = com_call(view, "GetTableAnnotationCount")
        if not count:
            return tables
        for raw in com_call(view, "GetTableAnnotations") or ():
            table = cast_to(raw, "ITableAnnotation")
            rows = com_get(table, "RowCount")
            cols = com_get(table, "ColumnCount")
            cells = [
                TableCell(row=r, column=c, text=com_call(table, "Text2", r, c, False) or "")
                for r in range(rows)
                for c in range(cols)
            ]
            ttype = com_get(table, "Type")
            tables.append(
                Table(
                    kind={2: "bom", 5: "revision", 6: "hole"}.get(ttype, f"general({ttype})"),
                    title=_maybe(table, "Title", "") or "",
                    rows=rows,
                    columns=cols,
                    cells=cells,
                )
            )
    except Exception as exc:  # noqa: BLE001 — reportado no dump, não engolido
        log.warning("leitura de tabelas falhou na folha %s: %s", sheet_name, exc)
        unrecognized.append(Unrecognized(where=f"sheet:{sheet_name}", raw_type="tables", detail=str(exc)))
    return tables
