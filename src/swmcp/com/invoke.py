"""Invocação COM fail-fast (RNF-01).

Todo acesso a método/propriedade COM do projeto passa por aqui. Falha vira
``ComCallError`` com método, argumentos e HRESULT — nunca sucesso silencioso,
nunca ``getattr`` defensivo.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# HRESULTs que indicam que o SolidWorks fechou/caiu no meio da sessão (RNF-07)
DISCONNECTED_HRESULTS = frozenset(
    {
        -2147023174,  # 0x800706BA RPC_S_SERVER_UNAVAILABLE — processo encerrou
        -2147023170,  # 0x800706BE RPC_S_CALL_FAILED — processo caiu durante a chamada
        -2147417848,  # 0x80010108 RPC_E_DISCONNECTED — objeto desconectado
        -2147221021,  # 0x800401E3 MK_E_UNAVAILABLE — nenhuma instância ativa
    }
)


class ComCallError(RuntimeError):
    """Falha numa chamada COM, com contexto completo para diagnóstico."""

    def __init__(
        self,
        target: str,
        args: tuple[Any, ...],
        hresult: int | None,
        detail: str,
    ) -> None:
        self.target = target
        self.args_repr = _short_repr(args)
        self.hresult = hresult
        self.detail = detail
        hr = f"HRESULT=0x{hresult & 0xFFFFFFFF:08X}" if hresult is not None else "sem HRESULT"
        super().__init__(f"chamada COM falhou: {target}({self.args_repr}) — {hr} — {detail}")

    @property
    def is_disconnected(self) -> bool:
        """True se o erro indica SolidWorks fechado/travado (dispara reconexão)."""
        return self.hresult in DISCONNECTED_HRESULTS


def com_call(obj: Any, method: str, *args: Any) -> Any:
    """Chama ``obj.method(*args)`` traduzindo qualquer falha em ComCallError."""
    import pywintypes

    bound = getattr(obj, method)  # AttributeError aqui é bug nosso: deixa estourar
    if not callable(bound):
        # dispatch dinâmico expõe métodos sem argumento como propriedade
        if args:
            raise TypeError(f"COM {method} resolveu como propriedade, mas recebeu args {args!r}")
        return bound
    start = time.perf_counter()
    try:
        result = bound(*args)
    except pywintypes.com_error as exc:
        raise _translate(method, args, exc) from exc
    log.debug("COM %s(%s) em %.1fms", method, _short_repr(args), (time.perf_counter() - start) * 1000)
    return result


def com_get(obj: Any, prop: str) -> Any:
    """Lê ``obj.prop`` traduzindo falha COM em ComCallError.

    Com early binding (gen_py), propriedades sem argumento podem resolver como
    método — nesse caso a chamada é feita aqui, para o chamador sempre receber
    o valor (nunca um bound method solto).
    """
    import types

    import pywintypes

    try:
        value = getattr(obj, prop)
        if isinstance(value, types.MethodType):
            value = value()
        return value
    except pywintypes.com_error as exc:
        raise _translate(prop, (), exc) from exc


def _translate(target: str, args: tuple[Any, ...], exc: Any) -> ComCallError:
    hresult = exc.args[0] if exc.args else None
    detail = str(exc.args[1] or "") if len(exc.args) > 1 else str(exc)
    # com_error aninha o HRESULT específico do servidor em excepinfo[5]
    if len(exc.args) > 2 and exc.args[2] and exc.args[2][5]:
        hresult = exc.args[2][5]
        detail = f"{detail}: {exc.args[2][2]}" if exc.args[2][2] else detail
    err = ComCallError(target, args, hresult, detail)
    log.error("%s", err)
    return err


def _short_repr(args: tuple[Any, ...], limit: int = 120) -> str:
    text = ", ".join(repr(a) for a in args)
    return text if len(text) <= limit else text[: limit - 1] + "…"
