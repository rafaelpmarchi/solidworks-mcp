"""Agente de chat: Claude + Tool Runner sobre os serviços do swmcp.

Uma sessão de conversa por processo; o histórico vive em memória. As tools
chamam os mesmos serviços usados pelo servidor MCP — leitura sempre
somente-leitura, unidades em mm/graus.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from typing import Any

import anthropic
from anthropic import beta_tool

from swmcp.com.session import SwSession
from swmcp.review import engine
from swmcp.services import drawing_reader

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"

SYSTEM = """Você é o assistente de desenhos da Gromar, embutido no SolidWorks \
(taskpane). O SolidWorks está aberto na mesma máquina e você o acessa pelas \
ferramentas. Responda sempre em português brasileiro, direto ao ponto — o \
usuário é projetista/engenheiro e está com o desenho na tela.

Regras:
- Unidades: tudo que as ferramentas devolvem já está em mm e graus.
- Leitura nunca altera arquivo nenhum; abrir documento é somente-leitura por padrão.
- Ao revisar, apresente os achados por severidade (erro > aviso > info) e diga \
onde cada um está (folha/vista/cota). Itens 'unrecognized' significam que a \
leitura não interpretou algo — diga isso, nunca finja que estava tudo certo.
- Se o usuário não der o caminho do arquivo, use sw_status para ver o que está \
aberto e trabalhe com o documento ativo quando fizer sentido.
- Nunca invente valor de cota ou material: se não está no dump, você não sabe."""

_session = SwSession()
_lock = threading.Lock()  # uma conversa por vez — o COM é single-threaded


@beta_tool
def sw_status() -> str:
    """Status do SolidWorks: versão, documentos abertos e documento ativo."""
    return json.dumps(_session.status(), ensure_ascii=False)


@beta_tool
def get_drawing_dump(path: str) -> str:
    """Dump completo de um desenho .SLDDRW: folhas, vistas, cotas com tolerância,
    anotações, notas de legenda e propriedades. Somente-leitura.

    Args:
        path: caminho completo do arquivo .SLDDRW.
    """
    return drawing_reader.get_drawing_dump(_session, path).model_dump_json()


@beta_tool
def get_model_properties(path: str) -> str:
    """Propriedades de uma peça/montagem: material, massa (kg), caixa envolvente
    (mm), propriedades customizadas, configurações e features. Somente-leitura.

    Args:
        path: caminho completo do arquivo .SLDPRT ou .SLDASM.
    """
    return drawing_reader.get_model_properties(_session, path).model_dump_json()


@beta_tool
def review_drawing(path: str) -> str:
    """Revisa um desenho .SLDDRW com as regras da Gromar (legenda, material,
    escala, tolerâncias, GD&T, solda) e retorna o relatório de achados.

    Args:
        path: caminho completo do arquivo .SLDDRW.
    """
    dump = drawing_reader.get_drawing_dump(_session, path)
    report = engine.review(dump)
    out = report.model_dump()
    out["summary"] = {"errors": report.errors, "warnings": report.warnings}
    return json.dumps(out, ensure_ascii=False)


TOOLS = [sw_status, get_drawing_dump, get_model_properties, review_drawing]


class ChatAgent:
    """Conversa multi-turno; cada turno roda o tool runner até o fim."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic()
        self._messages: list[dict[str, Any]] = []

    def send(self, user_message: str) -> Iterator[dict[str, Any]]:
        """Processa um turno e emite eventos: text, tool, error, done."""
        with _lock:
            self._messages.append({"role": "user", "content": user_message})
            try:
                yield from self._run_turn()
            except anthropic.AuthenticationError:
                self._messages.pop()
                yield {"type": "need_key", "text": "A chave da API Anthropic é inválida ou foi revogada. Cole uma chave nova abaixo."}
            except anthropic.APIStatusError as exc:
                self._messages.pop()
                yield {"type": "error", "text": f"Erro da API ({exc.status_code}): {exc.message}"}
            except Exception as exc:  # noqa: BLE001 — vira mensagem no chat
                log.exception("falha no turno de chat")
                if "Could not resolve authentication" in str(exc):
                    self._messages.pop()
                    yield {
                        "type": "need_key",
                        "text": "Para ativar o chat, cole sua chave da API Anthropic "
                        "(console.anthropic.com → API Keys). Ela fica salva só nesta "
                        "máquina, no seu perfil do Windows.",
                    }
                else:
                    yield {"type": "error", "text": f"Falha: {exc}"}
            yield {"type": "done"}

    def _run_turn(self) -> Iterator[dict[str, Any]]:
        # reinicia o runner após pause_turn (server-side); espelha o histórico
        for _ in range(5):
            runner = self._client.beta.messages.tool_runner(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                tools=TOOLS,
                messages=self._messages,
            )
            last = None
            for message in runner:
                last = message
                for block in message.content:
                    if block.type == "text" and block.text:
                        yield {"type": "text", "text": block.text}
                    elif block.type == "tool_use":
                        yield {"type": "tool", "name": block.name, "input": dict(block.input)}
                self._messages.append({"role": "assistant", "content": message.content})
                tool_response = runner.generate_tool_call_response()
                if tool_response is not None:
                    self._messages.append(tool_response)
            if last is None or last.stop_reason != "pause_turn":
                return
        yield {"type": "error", "text": "turno pausado repetidamente pelo servidor; tente de novo"}

    def reset(self) -> None:
        with _lock:
            self._messages.clear()

    def set_api_key(self, key: str) -> str | None:
        """Valida a chave, aplica na sessão e persiste no ambiente do usuário.

        Retorna None em caso de sucesso, ou a mensagem de erro.
        """
        key = key.strip()
        if not key:
            return "chave vazia"
        candidate = anthropic.Anthropic(api_key=key)
        try:
            candidate.models.retrieve(MODEL)  # chamada de metadados: valida auth
        except anthropic.AuthenticationError:
            return "chave rejeitada pela API — confira se copiou a chave inteira"
        except anthropic.APIStatusError as exc:
            return f"não deu para validar a chave (HTTP {exc.status_code}): {exc.message}"
        except anthropic.APIConnectionError:
            return "sem conexão com api.anthropic.com — verifique a rede/proxy"

        with _lock:
            self._client = candidate
        _persist_user_env("ANTHROPIC_API_KEY", key)
        return None


def _persist_user_env(name: str, value: str) -> None:
    """Grava em HKCU\\Environment (persiste entre sessões) e no processo atual."""
    import os
    import winreg

    os.environ[name] = value
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    # avisa o shell para novos processos enxergarem a variável
    import ctypes

    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF, 0x1A, 0, "Environment", 0x0002, 5000, ctypes.byref(ctypes.c_ulong())
    )
    log.info("variável %s persistida no ambiente do usuário", name)
