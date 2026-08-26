"""Agente de chat: dirige o Claude Code headless (`claude -p`).

Usa o login já feito na máquina (plano Max) — nenhuma chave de API.
Cada turno roda `claude -p` com saída stream-json; a conversa continua entre
turnos via `--resume <session_id>`. As ferramentas do SolidWorks entram pelo
servidor MCP do próprio projeto (swmcp.server), que o Claude Code inicia.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SYSTEM = """Você é o assistente de desenhos da Gromar, embutido no SolidWorks \
(taskpane). O SolidWorks está aberto na mesma máquina e você o acessa pelas \
ferramentas MCP do servidor 'solidworks'. Responda sempre em português \
brasileiro, direto ao ponto — o usuário é projetista/engenheiro com o desenho \
na tela.

Regras:
- Unidades: as ferramentas usam mm e graus, sempre.
- Você pode LER (dump, propriedades, revisão) e também MODELAR: new_document,
create_sketch + sketch_*, extrude/revolve/fillet, set_dimension, set_material,
montagens (insert_component/add_mate), criar desenho 2D e exportar.
- Depois de modelar, use take_screenshot e LEIA o PNG para conferir o que fez.
- Nada é salvo sem save_document[_as]; salvar, sobrescrever ou apagar feature \
só com pedido explícito do usuário. Em arquivo de produção, pergunte antes.
- Ao revisar, apresente os achados por severidade (erro > aviso > info) e onde \
cada um está. Itens 'unrecognized' = a leitura não interpretou algo; diga isso.
- Sem caminho de arquivo? Use sw_status e trabalhe com o documento ativo.
- Nunca invente valor de cota ou material.
- Você está num painel estreito: respostas curtas, sem tabelas largas."""

_lock = threading.Lock()  # um turno por vez


def _claude_exe() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise FileNotFoundError(
            "Claude Code não encontrado no PATH. Instale/abra o Claude Code "
            "uma vez no PowerShell e tente de novo."
        )
    return exe


def _mcp_config_path() -> Path:
    """Gera o mcp-config apontando para o servidor MCP deste venv."""
    cfg_dir = Path(os.environ["LOCALAPPDATA"]) / "SwClaudeAddin"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / "mcp-solidworks.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "solidworks": {
                        "command": sys.executable,
                        "args": ["-m", "swmcp.server"],
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return cfg


class ChatAgent:
    """Conversa multi-turno sobre o Claude Code headless."""

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._mcp_config = _mcp_config_path()

    def send(self, user_message: str) -> Iterator[dict[str, Any]]:
        with _lock:
            try:
                yield from self._run_turn(user_message)
            except FileNotFoundError as exc:
                yield {"type": "error", "text": str(exc)}
            except Exception as exc:  # noqa: BLE001 — vira mensagem no chat
                log.exception("falha no turno de chat")
                yield {"type": "error", "text": f"Falha: {exc}"}
            yield {"type": "done"}

    def _run_turn(self, user_message: str) -> Iterator[dict[str, Any]]:
        cmd = [
            _claude_exe(),
            "-p", user_message,
            "--output-format", "stream-json",
            "--verbose",
            "--mcp-config", str(self._mcp_config),
            "--strict-mcp-config",
            "--allowedTools", "mcp__solidworks",
            "--append-system-prompt", SYSTEM,
        ]
        if self._session_id:
            cmd += ["--resume", self._session_id]

        log.info("claude -p (resume=%s)", self._session_id or "novo")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            assert proc.stdout is not None
            got_result = False
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("linha não-JSON do claude: %s", line[:200])
                    continue
                yield from self._map_event(event)
                if event.get("type") == "result":
                    got_result = True
            stderr = (proc.stderr.read() if proc.stderr else "").strip()
            proc.wait()
            if proc.returncode != 0 and not got_result:
                yield {"type": "error", "text": self._explain_failure(stderr, proc.returncode)}
        finally:
            if proc.poll() is None:
                proc.kill()

    def _map_event(self, event: dict[str, Any]) -> Iterator[dict[str, Any]]:
        etype = event.get("type")
        if etype == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    yield {"type": "text", "text": block["text"]}
                elif block.get("type") == "tool_use":
                    name = block.get("name", "")
                    name = name.removeprefix("mcp__solidworks__")
                    yield {"type": "tool", "name": name, "input": block.get("input") or {}}
        elif etype == "result":
            self._session_id = event.get("session_id") or self._session_id
            if event.get("is_error"):
                yield {"type": "error", "text": str(event.get("result") or "erro no turno")}

    @staticmethod
    def _explain_failure(stderr: str, code: int) -> str:
        low = stderr.lower()
        if "log in" in low or "login" in low or "authent" in low or "api key" in low:
            return (
                "Sua sessão do Claude Code expirou. Abra o PowerShell, rode "
                "`claude`, faça `/login` e tente de novo aqui."
            )
        return f"Claude Code terminou com erro ({code}): {stderr[:400] or 'sem detalhe'}"

    def reset(self) -> None:
        with _lock:
            self._session_id = None
