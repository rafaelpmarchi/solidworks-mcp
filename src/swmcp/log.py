"""Logging em arquivo rotativo (RNF-08). Nível via SWMCP_LOG_LEVEL."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logging() -> None:
    level = os.environ.get("SWMCP_LOG_LEVEL", "INFO").upper()
    log_dir = Path(os.environ.get("SWMCP_LOG_DIR", Path(__file__).parents[2] / "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_dir / "swmcp.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    # stdout é o transporte MCP (stdio) — nunca logar nele; stderr é seguro
    stderr = logging.StreamHandler()
    stderr.setLevel("WARNING")
    stderr.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(stderr)
