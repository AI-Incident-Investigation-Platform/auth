import json
import logging
import sys
import traceback
from datetime import UTC, datetime

from src.config import cfg
from src.core.context import get_span_id, get_trace_id, log_context


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = log_context.get() or {}
        trace_id = get_trace_id()
        span_id = get_span_id()
        log_data = {
            **context,
            "service_name": cfg.service.name,
            "service_version": cfg.service.version,
            "trace_id": trace_id if trace_id != "-" else context.get("trace_id", "-"),
            "span_id": span_id if span_id != "-" else context.get("span_id", "-"),
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "src": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[1] is not None:
            log_data["exception"] = self.safe_exception(record.exc_info[1])

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
                "service_name",
                "service_version",
                "color_message",
                "span_id",
                "timestamp",
                "level",
                "src",
                "exception",
            ):
                log_data[key] = value

        return json.dumps(log_data, ensure_ascii=False, default=str)

    @staticmethod
    def safe_exception(exc: BaseException) -> str:
        # Текст исключений и строки исходников могут содержать SQL-параметры и секреты.
        lines: list[str] = []
        seen: set[int] = set()
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            lines.append(f"{type(current).__module__}.{type(current).__qualname__}")
            for frame, lineno in traceback.walk_tb(current.__traceback__):
                lines.append(f"  {frame.f_code.co_filename}:{lineno} in {frame.f_code.co_name}")
            if current.__cause__ is not None:
                lines.append("Причина:")
                current = current.__cause__
            elif not current.__suppress_context__ and current.__context__ is not None:
                lines.append("Предыдущее исключение:")
                current = current.__context__
            else:
                current = None
        return "\n".join(lines)


def setup_logging(level: str = "INFO") -> None:
    formatter = StructuredJsonFormatter()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
