"""Logging setup for the bridge."""

from __future__ import annotations

import logging
import os

_LEVELS = {
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def setup_logging() -> logging.Logger:
    level = _LEVELS.get((os.environ.get("LOG_LEVEL") or "info").lower(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Make libraries a bit quieter
    logging.getLogger("engineio.client").setLevel(logging.WARNING)
    logging.getLogger("socketio.client").setLevel(logging.WARNING)
    return logging.getLogger("uhi-ha-bridge")
