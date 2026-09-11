"""Sessão com o SolidWorks: conectar, reconectar, status (RF-01, RNF-07).

Toda interação com o objeto ``ISldWorks`` acontece dentro do worker STA.
O objeto COM nunca sai desta camada — quem está acima recebe dicts/DTOs.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from swmcp.com import constants
from swmcp.com.invoke import ComCallError, com_call, com_get
from swmcp.com.worker import ComWorker

log = logging.getLogger(__name__)

PROG_ID = "SldWorks.Application"


class SolidWorksNotAvailableError(RuntimeError):
    """SolidWorks não está aberto e não foi possível iniciar uma instância."""


class SwSession:
    """Mantém a referência ao ISldWorks e reconecta sob demanda.

    Uso: ``session.run(lambda app: ...)`` — o callable recebe o objeto app
    já dentro do thread STA. Se o SolidWorks tiver fechado, uma reconexão é
    tentada uma única vez antes de propagar o erro.
    """

    def __init__(self, worker: ComWorker | None = None) -> None:
        self._worker = worker or ComWorker()
        self._app: Any = None

    # ------------------------------------------------------------------ público

    def run(self, fn) -> Any:
        """Executa ``fn(app)`` no thread STA, reconectando se o SW caiu."""
        try:
            return self._worker.run(lambda: fn(self._ensure_app()))
        except ComCallError as exc:
            if not exc.is_disconnected:
                raise
            log.warning("SolidWorks desconectado (%s); tentando reconectar", exc.target)
            self._worker.run(self._drop_app)
            return self._worker.run(lambda: fn(self._ensure_app()))

    def status(self) -> dict[str, Any]:
        """Versão, documentos abertos e documento ativo (tool ``sw_status``)."""
        return self.run(_read_status)

    def close(self) -> None:
        self._worker.run(self._drop_app)
        self._worker.close()

    # ------------------------------------------------- interno (thread STA)

    def _ensure_app(self) -> Any:
        if self._app is not None:
            try:
                visible = com_get(self._app, "Visible")  # ping barato: detecta app morto
            except ComCallError as exc:
                if not exc.is_disconnected:
                    raise
                self._drop_app()
            else:
                # O usuário fechou o SolidWorks mas o processo ficou vivo (invisível)
                # porque este servidor segura uma referência COM; se ele abriu outro,
                # é nesse que as ações e configurações têm de acontecer.
                if visible or not _visible_instances():
                    return self._app
                log.warning("instância %s ficou invisível; trocando para a instância visível",
                            _pid_of(self._app))
                self._drop_app()
        self._app = _connect()
        return self._app

    def _drop_app(self) -> None:
        self._app = None


def _connect() -> Any:
    """GetActiveObject na instância aberta; senão inicia uma nova, visível."""
    import pythoncom
    import pywintypes
    import win32com.client

    sldworks_module()  # garante o gen_py antes do cast
    visible = _visible_instances()
    if visible:
        log.info("conectado à instância visível do SolidWorks (PID %s)", _pid_of(visible[0]))
        return visible[0]
    try:
        app = win32com.client.GetActiveObject(PROG_ID)
        log.info("conectado à instância aberta do SolidWorks")
        # early binding determinístico: byref volta em tupla, sempre
        return cast_to(app, "ISldWorks")
    except pywintypes.com_error as exc:
        if exc.args and exc.args[0] not in (-2147221021,):  # MK_E_UNAVAILABLE
            raise ComCallError("GetActiveObject", (PROG_ID,), exc.args[0], str(exc)) from exc

    log.info("nenhuma instância ativa; iniciando SolidWorks (pode demorar)")
    try:
        app = win32com.client.DispatchEx(PROG_ID)
    except pywintypes.com_error as exc:
        raise SolidWorksNotAvailableError(
            f"não foi possível iniciar o SolidWorks ({PROG_ID}): {exc}"
        ) from exc
    app.Visible = True  # o SolidWorks fica sempre visível ao usuário (Visão §1)
    return cast_to(app, "ISldWorks")


def _visible_instances() -> list[Any]:
    """Instâncias do SolidWorks registradas na ROT ("SolidWorks_PID_<n>") e visíveis.

    GetActiveObject devolve a primeira registrada — que pode ser um processo
    órfão, sem janela, mantido vivo por uma referência COM deste servidor.
    """
    import pythoncom
    import win32com.client

    out = []
    try:
        rot = pythoncom.GetRunningObjectTable()
        ctx = pythoncom.CreateBindCtx(0)
        for moniker in rot.EnumRunning():
            name = moniker.GetDisplayName(ctx, None)
            if not name.startswith("SolidWorks_PID_"):
                continue
            try:
                obj = rot.GetObject(moniker)
                app = cast_to(win32com.client.Dispatch(obj.QueryInterface(pythoncom.IID_IDispatch)), "ISldWorks")
                if com_get(app, "Visible"):
                    out.append(app)
            except Exception as exc:  # instância morrendo: ignora
                log.debug("instância %s ignorada: %s", name, exc)
    except Exception as exc:
        log.debug("ROT indisponível: %s", exc)
    return out


def _pid_of(app: Any) -> Any:
    try:
        return com_call(app, "GetProcessID")
    except Exception:
        return "?"


SLDWORKS_TLB = r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldworks.tlb"

_sldworks_module: Any = None


def sldworks_module() -> Any:
    """Módulo makepy gerado do sldworks.tlb (cache em gen_py).

    Necessário para cast de interfaces (ex.: IModelDoc2 → IDrawingDoc): o
    dispatch dinâmico não expõe os membros das interfaces derivadas, e o
    ISldWorks não automatiza o makepy (sem GetTypeInfo).
    """
    global _sldworks_module
    if _sldworks_module is None:
        import pythoncom
        import win32com.client.gencache as gencache

        tlb = pythoncom.LoadTypeLib(SLDWORKS_TLB)
        guid, lcid, _syskind, major, minor, _flags = tlb.GetLibAttr()
        _sldworks_module = gencache.EnsureModule(str(guid), lcid, major, minor)
        log.info("typelib sldworks %s.%s carregado (makepy)", major, minor)
    return _sldworks_module


SWCONST_TLB = r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\swconst.tlb"

_swconst: Any = None


def swconst() -> Any:
    """Constantes oficiais do SolidWorks (enum swconst.tlb via makepy).

    Uso: ``swconst().swDocPART``. Fonte de verdade para valores de enum —
    preferir a chutar números em wrappers de escrita.
    """
    global _swconst
    if _swconst is None:
        import pythoncom
        import win32com.client.gencache as gencache

        tlb = pythoncom.LoadTypeLib(SWCONST_TLB)
        guid, lcid, _syskind, major, minor, _flags = tlb.GetLibAttr()
        _swconst = gencache.EnsureModule(str(guid), lcid, major, minor).constants
    return _swconst


def cast_to(obj: Any, interface: str) -> Any:
    """Reveste um proxy COM com a interface gerada — ex.: cast_to(doc, "IDrawingDoc")."""
    cls = getattr(sldworks_module(), interface, None)
    if cls is None:
        raise ComCallError("cast_to", (interface,), None, f"interface {interface!r} não existe no typelib sldworks")
    try:
        return cls(obj._oleobj_)
    except Exception as exc:  # QI recusado etc. — erro rico, nunca silencioso
        raise ComCallError("cast_to", (interface,), getattr(exc, "hresult", None), str(exc)) from exc


def _read_status(app: Any) -> dict[str, Any]:
    revision = com_get(app, "RevisionNumber")
    year = constants.revision_to_year(revision)

    docs = []
    hidden = 0
    raw_docs = com_call(app, "GetDocuments")
    for doc in raw_docs or ():
        summary = _doc_summary(doc)
        # perfis de weldment (.sldlfp) etc. entram na lista do SW sozinhos,
        # em somente-leitura, um por perfil usado — poluem o status sem
        # informar nada: só o total é reportado
        if constants.is_library_document(summary["path"]):
            hidden += 1
            continue
        docs.append(summary)

    active = com_get(app, "ActiveDoc")
    return {
        "connected": True,
        "revision": revision,
        "year": year,
        "open_documents": docs,
        "library_documents_hidden": hidden,
        "active_document": _doc_summary(active) if active is not None else None,
    }


def _doc_summary(doc: Any) -> dict[str, Any]:
    doc_type = com_call(doc, "GetType")
    path = com_call(doc, "GetPathName")
    return {
        "title": com_call(doc, "GetTitle"),
        "path": path or None,
        "type": constants.DOC_TYPE_NAMES.get(doc_type, f"desconhecido({doc_type})"),
        "needs_save": bool(com_call(doc, "GetSaveFlag")),
        "read_only": bool(com_call(doc, "IsOpenedReadOnly")) if path else False,
    }


def doc_type_for_path(path: str) -> int:
    ext = os.path.splitext(path)[1].lower()
    try:
        return constants.DOC_TYPE_BY_EXTENSION[ext]
    except KeyError:
        raise ValueError(
            f"extensão não suportada: {ext!r} (esperado .sldprt/.sldasm/.slddrw)"
        ) from None
