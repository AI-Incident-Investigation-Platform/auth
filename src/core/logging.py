import json
import logging
import sys
from datetime import UTC, datetime

from src.config import cfg
from src.core.context import get_trace_id


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "service": cfg.service.name,
            "trace_id": get_trace_id(),
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "src": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "taskName",
                "exc_info",
                "exc_text",
                "stack_info",
                "trace_id",
                "service",
                "color_message",
            ):
                log_data[key] = value

        return json.dumps(log_data, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    formatter = StructuredJsonFormatter()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.WARNING)
