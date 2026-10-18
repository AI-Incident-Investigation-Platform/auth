import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Layer(StrEnum):
    UNIT = "unit"
    INTEGRATION = "integration"


class Suite(StrEnum):
    UNIT = "unit"
    INTEGRATION = "integration"
    FULL = "full"

    @property
    def layers(self) -> frozenset[Layer]:
        match self:
            case Suite.UNIT:
                return frozenset({Layer.UNIT})
            case Suite.INTEGRATION:
                return frozenset({Layer.INTEGRATION})
            case Suite.FULL:
                return frozenset(Layer)


class ScenarioStatus(StrEnum):
    ACTIVE = "active"
    KNOWN_BUG = "known_bug"


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    layer: Layer
    domain: str
    status: ScenarioStatus
    reason: str = ""


def load_scenarios(path: Path) -> dict[str, Scenario]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    scenarios: dict[str, Scenario] = {}
    for raw in data.get("scenario", []):
        scenario = Scenario(
            id=raw["id"],
            title=raw["title"],
            layer=Layer(raw["layer"]),
            domain=raw["domain"],
            status=ScenarioStatus(raw.get("status", ScenarioStatus.ACTIVE)),
            reason=raw.get("reason", ""),
        )
        if scenario.id in scenarios:
            raise ValueError(f"duplicate scenario id in manifest: {scenario.id}")
        scenarios[scenario.id] = scenario
    return scenarios
