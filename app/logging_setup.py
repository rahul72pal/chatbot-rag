"""Configure JSON logging for the app and its dependencies."""

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line."""

    context_fields = ("session_id", "user_id", "turn_id", "latency_ms")

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        for key in self.context_fields:
            if hasattr(record, key):
                data[key] = getattr(record, key)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def setup_logging() -> None:
    """Set JSON formatting on the root and app loggers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

    # The app's legacy logger owns its handler and disables propagation.
    app_logger = logging.getLogger("chatbot")
    for app_handler in app_logger.handlers:
        app_handler.setFormatter(JsonFormatter())
