"""Servidor HTTP local do chat (127.0.0.1:8765) — UI + SSE por turno.

Rodar: python -m swmcp.chat  (o add-in do SolidWorks inicia isso sozinho).
Só escuta em loopback; não expõe nada na rede.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from swmcp.chat.agent import ChatAgent
from swmcp.log import setup_logging

log = logging.getLogger(__name__)

HOST, PORT = "127.0.0.1", 8765
WEB_DIR = Path(__file__).parent / "web"

_agent: ChatAgent | None = None
_agent_init = threading.Lock()


def agent() -> ChatAgent:
    global _agent
    with _agent_init:
        if _agent is None:
            _agent = ChatAgent()
    return _agent


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        log.debug("http %s", fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = (WEB_DIR / "index.html").read_bytes()
            self._respond(200, "text/html; charset=utf-8", body)
        elif self.path == "/health":
            self._respond(200, "application/json", b'{"ok": true}')
        else:
            self._respond(404, "text/plain", b"not found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/chat":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            message = (payload.get("message") or "").strip()
            if not message:
                self._respond(400, "application/json", b'{"error": "mensagem vazia"}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for event in agent().send(message):
                    data = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()
            except (ConnectionAbortedError, BrokenPipeError):
                log.info("cliente desconectou no meio do turno")
        elif self.path == "/reset":
            agent().reset()
            self._respond(200, "application/json", b'{"ok": true}')
        else:
            self._respond(404, "text/plain", b"not found")

    def _respond(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    setup_logging()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("chat do SolidWorks em http://%s:%s", HOST, PORT)
    print(f"chat do SolidWorks em http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
