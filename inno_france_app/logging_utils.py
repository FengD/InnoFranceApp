from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("inno_france")
    if logger.handlers:
        return logger
    level_name = os.getenv("INNOFRANCE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")
    return logger


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event, "ts": datetime.utcnow().isoformat() + "Z", **fields}
    logger.info(json.dumps(payload, ensure_ascii=False))
