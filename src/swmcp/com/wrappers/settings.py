"""Opções do sistema do SolidWorks: File Locations (escrita persistente).

File Locations respondem por Get/SetUserPreferenceStringValue (a variante
StringListValue devolve "" e o Set não grava — medido no SW2023). O valor é
uma lista separada por ';'. O SolidWorks só descarrega no registro ao fechar,
por isso a leitura de conferência é feita pela própria API.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from swmcp.com.invoke import ComCallError, com_call
from swmcp.com.session import swconst

log = logging.getLogger(__name__)

# nome amigável → constante swUserPreferenceStringValue_e
FILE_LOCATIONS = {
    "document_templates": "swFileLocationsDocumentTemplates",
    "sheet_formats": "swFileLocationsSheetFormat",
    "weldment_profiles": "swFileLocationsWeldmentProfiles",
    "weldment_property_file": "swFileLocationsWeldmentPropertyFile",
    "weldment_cut_list_templates": "swFileLocationsWeldmentCutListTemplates",
    "bom_templates": "swFileLocationsBOMTemplates",
    "material_databases": "swFileLocationsMaterialDatabases",
    "design_library": "swFileLocationsDesignLibrary",
    "macros": "swFileLocationsMacros",
}

# Biblioteca KONGZ (Gromar): subpastas relativas à raiz da biblioteca
KONGZ_LIBRARY = {
    "document_templates": r"CAD\KONGZ_SolidWorks_Library\KONGZ_templates",
    "sheet_formats": r"CAD\KONGZ_SolidWorks_Library\sheetformat",
    "weldment_profiles": r"CAD\KONGZ_SolidWorks_Library\data\weldment profiles",
}


def _key(name: str) -> int:
    try:
        return getattr(swconst(), FILE_LOCATIONS[name])
    except KeyError:
        raise ValueError(f"local desconhecido {name!r}; opções: {sorted(FILE_LOCATIONS)}") from None


def get_file_locations(app: Any) -> dict[str, list[str]]:
    out = {}
    for name in FILE_LOCATIONS:
        raw = com_call(app, "GetUserPreferenceStringValue", _key(name)) or ""
        out[name] = [p for p in raw.split(";") if p.strip()]
    return out


def set_file_location(app: Any, name: str, folders: list[str], append: bool = True) -> dict[str, Any]:
    """Grava a lista de pastas de um File Location (append=True mantém as atuais)."""
    key = _key(name)
    missing = [f for f in folders if not os.path.isdir(f)]
    if missing:
        raise FileNotFoundError(f"pasta(s) inexistente(s) para {name}: {missing}")
    current = [p for p in (com_call(app, "GetUserPreferenceStringValue", key) or "").split(";") if p.strip()]
    new = list(current) if append else []
    for f in folders:
        if os.path.normcase(os.path.abspath(f)) not in {os.path.normcase(os.path.abspath(x)) for x in new}:
            new.append(f)
    value = ";".join(new)
    if not com_call(app, "SetUserPreferenceStringValue", key, value):
        raise ComCallError("SetUserPreferenceStringValue", (name, value), None, "SolidWorks recusou o valor")
    readback = com_call(app, "GetUserPreferenceStringValue", key) or ""
    if readback != value:
        raise ComCallError("SetUserPreferenceStringValue", (name,), None, f"gravou {value!r} mas leu {readback!r}")
    log.info("File Location %s = %s", name, value)
    return {"location": name, "before": current, "after": new}


def apply_kongz_library(app: Any, root: str, append: bool = True) -> dict[str, Any]:
    """Aponta templates, formatos de folha e perfis de weldment para a biblioteca KONGZ."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise FileNotFoundError(f"raiz da biblioteca KONGZ não existe: {root}")
    results = {}
    for name, rel in KONGZ_LIBRARY.items():
        results[name] = set_file_location(app, name, [os.path.join(root, rel)], append)
    return {"root": root, "locations": results}
