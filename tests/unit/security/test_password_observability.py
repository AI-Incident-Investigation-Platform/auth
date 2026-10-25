import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY

from src.core.security import service
from src.core.security.service import SecurityService


@pytest.mark.case(id="AUTH-PASSWORD-005")
async def test_password_spans_split_wait_and_execution_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(service.trace, "get_tracer", provider.get_tracer)
    security = SecurityService()
    password = "private-password-for-test"
    encoded = await security.hash_password(password)
    assert await security.verify_password(encoded, password)
    assert not await security.verify_password(None, password)

    spans = exporter.get_finished_spans()
    parents = [span for span in spans if span.name == "auth.password.verify"]
    assert len(parents) == 2
    for parent in parents:
        children = [
            span for span in spans if span.parent and span.parent.span_id == parent.context.span_id
        ]
        assert {span.name for span in children} == {"auth.password.wait", "auth.password.execute"}
        assert all(span.context.trace_id == parent.context.trace_id for span in children)
    serialized = json.dumps([span.to_json() for span in spans])
    assert password not in serialized
    assert encoded not in serialized
    assert "unknown_user" not in serialized
    provider.shutdown()


@pytest.mark.case(id="AUTH-PASSWORD-006")
async def test_password_metrics_include_unknown_and_rejected_passwords() -> None:
    labels = {"operation": "verify", "stage": "execute"}
    before = REGISTRY.get_sample_value("auth_password_duration_seconds_count", labels) or 0
    security = SecurityService()
    encoded = await security.hash_password("password-1")

    assert not await security.verify_password(encoded, "wrong-password")
    assert not await security.verify_password(None, "wrong-password")

    assert REGISTRY.get_sample_value("auth_password_duration_seconds_count", labels) == before + 2
    for state in ("running", "waiting"):
        assert (
            REGISTRY.get_sample_value(
                "auth_password_operations", {"operation": "verify", "state": state}
            )
            == 0
        )
