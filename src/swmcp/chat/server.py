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

from urllib.parse import parse_qs, urlparse

from swmcp.chat import panel
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
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = (WEB_DIR / "index.html").read_bytes()
            self._respond(200, "text/html; charset=utf-8", body)
        elif parsed.path in ("/scan", "/scan.html"):
            body = (WEB_DIR / "scan.html").read_bytes()
            self._respond(200, "text/html; charset=utf-8", body)
        elif parsed.path == "/viewer.js":
            self._respond(200, "text/javascript",
                          (WEB_DIR / "viewer.js").read_bytes())
        elif parsed.path.startswith("/vendor/"):
            nome = Path(parsed.path[len("/vendor/"):]).name  # sem traversal
            arq = WEB_DIR / "vendor" / nome
            if arq.is_file():
                ctype = ("text/javascript" if nome.endswith(".js")
                         else "application/octet-stream")
                self._respond(200, ctype, arq.read_bytes())
            else:
                self._respond(404, "text/plain", b"not found")
        elif parsed.path == "/health":
            self._respond(200, "application/json", b'{"ok": true}')
        elif parsed.path == "/mesh/status":
            self._json(lambda: panel.handle("status", {}))
        elif parsed.path == "/mesh/file":
            path = (parse_qs(parsed.query).get("path") or [""])[0]
            served = panel.serve_file(path)
            if served is None:
                self._respond(404, "text/plain", b"not found")
            else:
                self._respond(200, served[1], served[0])
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
        elif self.path.startswith("/mesh/"):
            route = self.path[len("/mesh/"):]
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            self._json(lambda: panel.handle(route, body))
        else:
            self._respond(404, "text/plain", b"not found")

    def _json(self, fn) -> None:
        """Executa fn() e responde JSON; exceção vira {"error": ...} com 400."""
        try:
            result = fn()
            code = 200
        except Exception as exc:  # noqa: BLE001 — fronteira HTTP do painel
            log.exception("rota do painel falhou")
            result, code = {"error": str(exc)}, 400
        self._respond(code, "application/json; charset=utf-8",
                      json.dumps(result, ensure_ascii=False).encode())

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
