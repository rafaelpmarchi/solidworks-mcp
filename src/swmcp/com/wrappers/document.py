"""Abrir/ativar/fechar documentos (RF-02). Executa dentro do thread STA."""

from __future__ import annotations

import logging
import os
from typing import Any

from swmcp.com import constants
from swmcp.com.invoke import ComCallError, com_call
from swmcp.com.session import doc_type_for_path

log = logging.getLogger(__name__)


def open_document(app: Any, path: str, read_only: bool = True) -> dict[str, Any]:
    """OpenDoc6 com errors/warnings por VARIANT byref — falha vira exceção.

    Leitura abre somente-leitura por padrão (RNF-04): o agente não deve
    segurar lock de escrita num desenho de produção só para ler.
    """
    import pythoncom
    from win32com.client import VARIANT

    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"arquivo não existe: {path}")

    doc_type = doc_type_for_path(path)
    options = constants.swOpenDocOptions_Silent
    if read_only:
        options |= constants.swOpenDocOptions_ReadOnly

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    doc = com_call(app, "OpenDoc6", path, doc_type, options, "", errors, warnings)

    if doc is None or errors.value:
        names = constants.decode_bits(errors.value, constants.FILE_LOAD_ERRORS)
        raise ComCallError(
            "OpenDoc6",
            (path,),
            None,
            f"falha ao abrir (errors=0x{errors.value:X}: {'; '.join(names) or 'sem detalhe'})",
        )

    result = {
        "title": com_call(doc, "GetTitle"),
        "path": com_call(doc, "GetPathName"),
        "type": constants.DOC_TYPE_NAMES[doc_type],
        "read_only": read_only,
        "warnings": constants.decode_bits(warnings.value, constants.FILE_LOAD_WARNINGS),
    }
    log.info("aberto %s (warnings=%s)", path, result["warnings"] or "nenhum")
    return result


def activate_document(app: Any, title: str) -> None:
    """Torna ativo o documento já aberto com esse título."""
    import pythoncom
    from win32com.client import VARIANT

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    doc = com_call(app, "ActivateDoc3", title, False, 0, errors)
    if doc is None:
        raise ComCallError("ActivateDoc3", (title,), None, f"documento não ativado (errors={errors.value})")


def close_document(app: Any, title: str) -> None:
    """Fecha SEM salvar — salvar é decisão explícita, nunca efeito colateral (RNF-05)."""
    com_call(app, "CloseDoc", title)
    log.info("fechado %s (sem salvar)", title)


def find_open_document(app: Any, path: str) -> Any | None:
    """Retorna o ModelDoc2 já aberto para esse caminho, ou None."""
    path_norm = os.path.normcase(os.path.abspath(path))
    for doc in com_call(app, "GetDocuments") or ():
        if os.path.normcase(com_call(doc, "GetPathName") or "") == path_norm:
            return doc
    return None
