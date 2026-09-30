"""Válvula de escape: executa código Python arbitrário contra a API COM.

Cobre o que os wrappers ainda não embrulharam — o agente escreve pywin32
direto. Roda no thread STA com estas variáveis no escopo:

  app        ISldWorks early-bound (documento ativo em app.ActiveDoc)
  doc        IModelDoc2 do documento ativo (None se não houver)
  cast_to    cast_to(obj, "IInterface") — necessário em quase todo retorno COM
  swconst    swconst().swDocPART etc. (enums oficiais)
  com_call/com_get  invocação fail-fast
  units      from_mm/to_mm/from_deg/to_deg
  result     atribua aqui o que quiser retornar (serializável em JSON)

Helpers para as armadilhas medidas no SW2023 (ver cada um):
  feature(nome)            IFeature pelo nome (inclusive dentro de pasta)
  tree_order()             nomes das features na ordem da árvore
  select_face(x, y, z)     seleciona a face pelo ponto (mm) — SelectByID2 com
                           o ponto em cima da face falha
  ray_select(p, dir)       SelectByRay partindo 5 mm antes de p, na direção dir
  to_sketch(sketch, p)     ponto da peça (mm) → esboço (mm, z≠0 = fora do plano)
  to_model(sketch, p)      ponto do esboço (mm) → peça (mm)
  darr([..])               VARIANT de doubles — MathUtility.CreatePoint com lista
                           Python corrompe as coordenadas

Print vai para o retorno também. Sem timeout: cuidado com diálogos modais.
Com scratch=True o código roda numa PEÇA NOVA descartável, fechada sem salvar
no fim, e o documento que estava ativo volta a ser o ativo — é para testar
chamada de API sem criar/apagar feature na peça que o usuário está vendo.
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
from swmcp.domain.placement import apply_transform, to_local

log = logging.getLogger(__name__)


def _helpers(app: Any) -> dict[str, Any]:
    import pythoncom
    from win32com.client import VARIANT

    from swmcp.com.wrappers import holes, modeling

    def doc() -> Any:
        d = com_get(app, "ActiveDoc")
        return cast_to(d, "IModelDoc2") if d is not None else None

    def feature(nome: str) -> Any:
        return modeling._feature_by_name(doc(), nome)

    def tree_order() -> list[str]:
        nomes, raw = [], com_call(doc(), "FirstFeature")
        while raw is not None:
            f = cast_to(raw, "IFeature")
            nomes.append(com_call(f, "Name"))
            raw = com_call(f, "GetNextFeature")
        return nomes

    def ray_select(p: list[float], direction: list[float], append: bool = False) -> bool:
        ext = com_get(doc(), "Extension")
        if not append:
            com_call(doc(), "ClearSelection2", True)
        return bool(com_call(ext, "SelectByRay",
                             *(units.from_mm(p[i] - 5 * direction[i]) for i in range(3)),
                             *direction, 0.001, 2, append, 0, 0))

    def _xf(sketch: Any) -> list[float]:
        return list(com_get(cast_to(com_call(sketch, "ModelToSketchTransform"), "IMathTransform"),
                            "ArrayData"))

    def to_sketch(sketch: Any, p: list[float]) -> tuple[float, float, float]:
        return apply_transform(_xf(sketch), p)

    def to_model(sketch: Any, p: list[float]) -> tuple[float, float, float]:
        return to_local(_xf(sketch), (p[0], p[1], p[2] if len(p) > 2 else 0.0))

    def darr(valores: list[float]) -> Any:
        return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(v) for v in valores])

    return {"doc": doc(), "feature": feature, "tree_order": tree_order,
            "select_face": lambda x, y, z, append=False: holes.select_face_at(app, x, y, z, append),
            "ray_select": ray_select, "to_sketch": to_sketch, "to_model": to_model, "darr": darr}


def run_script(app: Any, code: str, scratch: bool = False) -> dict[str, Any]:
    titulo_original = None
    titulo_rascunho = None
    if scratch:
        from swmcp.com.wrappers import document, output

        ativo = com_get(app, "ActiveDoc")
        titulo_original = com_call(ativo, "GetTitle") if ativo is not None else None
        output.new_document(app, "part")
        titulo_rascunho = com_call(com_get(app, "ActiveDoc"), "GetTitle")
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
    log.info("run_sw_script (%d chars%s)", len(code), ", rascunho" if scratch else "")
    try:
        scope.update(_helpers(app))
        with redirect_stdout(stdout):
            exec(compile(code, "<run_sw_script>", "exec"), scope)  # noqa: S102
    except Exception:
        return {
            "ok": False,
            "stdout": stdout.getvalue()[-4000:],
            "traceback": traceback.format_exc()[-4000:],
            "scratch": scratch,
        }
    finally:
        if scratch:
            try:
                document.close_document(app, titulo_rascunho)
                if titulo_original:
                    document.activate_document(app, titulo_original)
            except Exception:  # noqa: BLE001 — o resultado do script vale mais
                log.exception("não consegui fechar o rascunho %s", titulo_rascunho)
    result = scope.get("result")
    try:
        json.dumps(result)
    except (TypeError, ValueError):
        result = repr(result)[:4000]
    return {"ok": True, "stdout": stdout.getvalue()[-4000:], "result": result, "scratch": scratch}
