"""Worker STA: todas as chamadas COM passam por um único thread (RNF-02).

O COM do SolidWorks é single-threaded apartment. Este módulo mantém um thread
dedicado que inicializa o COM (``CoInitialize``) e executa callables vindos de
uma fila; o resultado volta por ``Future``. O servidor MCP pode ser async à
vontade — o COM nunca é concorrente.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

_SHUTDOWN = object()


class WorkerClosedError(RuntimeError):
    """Chamada submetida após o worker ter sido encerrado."""


class ComWorker:
    """Thread único que serializa toda chamada COM.

    ``init`` e ``teardown`` existem para os testes injetarem no-ops; em produção
    o default inicializa/finaliza o COM no thread.
    """

    def __init__(
        self,
        init: Callable[[], None] | None = None,
        teardown: Callable[[], None] | None = None,
        name: str = "sw-com-worker",
    ) -> None:
        self._init = init if init is not None else _com_initialize
        self._teardown = teardown if teardown is not None else _com_uninitialize
        self._queue: queue.Queue[Any] = queue.Queue()
        self._closed = False
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self._thread.start()

    def submit(self, fn: Callable[[], T]) -> Future[T]:
        """Agenda ``fn`` no thread COM e retorna um Future com o resultado."""
        if self._closed:
            raise WorkerClosedError("worker COM já foi encerrado")
        future: Future[T] = Future()
        self._queue.put((fn, future))
        return future

    def run(self, fn: Callable[[], T], timeout: float | None = None) -> T:
        """Executa ``fn`` no thread COM e bloqueia até o resultado.

        Exceções levantadas por ``fn`` propagam intactas para o chamador.
        """
        return self.submit(fn).result(timeout)

    def close(self, timeout: float = 5.0) -> None:
        """Encerra o worker; chamadas pendentes ainda são drenadas."""
        if self._closed:
            return
        self._closed = True
        self._queue.put(_SHUTDOWN)
        self._thread.join(timeout)

    def _loop(self) -> None:
        self._init()
        try:
            while True:
                item = self._queue.get()
                if item is _SHUTDOWN:
                    break
                fn, future = item
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    future.set_result(fn())
                except BaseException as exc:  # noqa: BLE001 — propaga via Future
                    future.set_exception(exc)
        finally:
            self._teardown()


def _com_initialize() -> None:
    import pythoncom

    pythoncom.CoInitialize()
    log.debug("COM inicializado no thread do worker")


def _com_uninitialize() -> None:
    import pythoncom

    pythoncom.CoUninitialize()
    log.debug("COM finalizado no thread do worker")
