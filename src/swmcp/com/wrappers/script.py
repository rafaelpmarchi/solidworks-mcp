"""Válvula de escape: executa código Python arbitrário contra a API COM.

Cobre o que os wrappers ainda não embrulharam — o agente escreve pywin32
direto. Roda no thread STA com estas variáveis no escopo:

  app        ISldWorks early-bound (documento ativo em app.ActiveDoc)
  cast_to    cast_to(obj, "IInterface") — necessário em quase todo retorno COM
  swconst    swconst().swDocPART etc. (enums oficiais)
  com_call/com_get  invocação fail-fast
  units      from_mm/to_mm/from_deg/to_deg
  result     atribua aqui o que quiser retornar (serializável em JSON)

Print vai para o retorno também. Sem timeout: cuidado com diálogos modais.
"""

from __future__ import annotations

import io
import json
import logging
import traceback
from contextlib import redirect_stdout
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import cast_to, swconst

log = logging.getLogger(__name__)


def run_script(app: Any, code: str) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "app": app,
        "cast_to": cast_to,
        "swconst": swconst,
        "com_call": com_call,
        "com_get": com_get,
        "units": units,
        "result": None,
    }
    stdout = io.StringIO()
    log.info("run_sw_script (%d chars)", len(code))
    try:
        with redirect_stdout(stdout):
            exec(compile(code, "<run_sw_script>", "exec"), scope)  # noqa: S102
    except Exception:
        return {
            "ok": False,
            "stdout": stdout.getvalue()[-4000:],
            "traceback": traceback.format_exc()[-4000:],
        }
    result = scope.get("result")
    try:
        json.dumps(result)
    except (TypeError, ValueError):
        result = repr(result)[:4000]
    return {"ok": True, "stdout": stdout.getvalue()[-4000:], "result": result}
