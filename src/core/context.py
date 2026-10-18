from opentelemetry import trace


def get_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return "-"
    return format(span_context.trace_id, "032x")
