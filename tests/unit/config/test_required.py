import pytest
from fastapi import FastAPI

from src.config import cfg
from src.config.exc import ConfigIncompleteError
from src.main import lifespan


@pytest.mark.case(id="CONFIG-001")
async def test_app_does_not_start_without_required_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg.cache, "host", "")
    monkeypatch.setattr(cfg.auth, "private_key_path", "")
    monkeypatch.setattr(cfg.registry, "enabled", True)
    monkeypatch.setattr(cfg.registry, "consul_url", "")

    with pytest.raises(ConfigIncompleteError) as error:
        async with lifespan(FastAPI()):
            pass

    missing = error.value.context["missing_settings"]
    assert isinstance(missing, list)
    assert set(missing) >= {"cache.host", "auth.private_key_path", "registry.consul_url"}
