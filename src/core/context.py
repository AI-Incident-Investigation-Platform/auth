from contextvars import ContextVar
from uuid import UUID

from opentelemetry import trace

REQUEST_ID_HEADER = "x-request-id"

log_context: ContextVar[dict[str, object] | None] = ContextVar("log_context", default=None)


def get_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return "-"
    return format(span_context.trace_id, "032x")


def get_span_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return "-"
    return format(span_context.span_id, "016x")


def bind_log_identity(user_id: UUID | str, session_id: UUID | str | None = None) -> None:
    context = log_context.get()
    if context is not None:
        context["user_id"] = str(user_id)
        if session_id is not None:
            context["session_id"] = str(session_id)
