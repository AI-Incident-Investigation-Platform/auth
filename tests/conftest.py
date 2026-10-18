import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import redis
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

from tests.support.scenarios import Layer, ScenarioStatus, Suite, load_scenarios

ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = ROOT / "tests"
TEST_DATABASE_PREFIX = "auth_test_"
_POSTGRES_KEY = pytest.StashKey[PostgresContainer]()
_DRAGONFLY_KEY = pytest.StashKey[DockerContainer]()

TEST_KEY_PATH = Path(tempfile.mkdtemp(prefix="auth-test-keys-")) / "private.pem"
TEST_KEY_PATH.write_bytes(
    rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
)

os.environ.update(
    {
        "DATABASE__POSTGRES_USERNAME": "test_only",
        "DATABASE__POSTGRES_PASSWORD": "test_only",
        "DATABASE__POSTGRES_DB": f"{TEST_DATABASE_PREFIX}forbidden",
        "DATABASE__POSTGRES_HOST": "127.0.0.1",
        "DATABASE__POSTGRES_PORT": "1",
        "CACHE__HOST": "127.0.0.1",
        "CACHE__PORT": "1",
        "CACHE__KEY_PREFIX": "auth:",
        "AUTH__PRIVATE_KEY_PATH": str(TEST_KEY_PATH),
        "AUTH__COOKIE_SECURE": "false",
        "SERVICE__PUBLIC_HOST": "host.docker.internal",
        "REGISTRY__ENABLED": "false",
        "TRACING__ENABLED": "false",
    }
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--suite",
        choices=[suite.value for suite in Suite],
        default=Suite.FULL.value,
        help="Слой тестов: unit (без Docker), integration (Postgres и Dragonfly), full.",
    )


def _suite(config: pytest.Config) -> Suite:
    return Suite(config.getoption("--suite"))


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    try:
        relative = collection_path.relative_to(TESTS_ROOT)
    except ValueError:
        return False
    if not relative.parts or relative.parts[0] not in set(Layer):
        return False
    return Layer(relative.parts[0]) not in _suite(config).layers


def pytest_sessionstart(session: pytest.Session) -> None:
    if Layer.INTEGRATION not in _suite(session.config).layers:
        return
    postgres = PostgresContainer(
        "postgres:18.6-alpine",
        username="test_only",
        password="test_only",
        dbname=f"{TEST_DATABASE_PREFIX}suite",
    )
    try:
        postgres.start()
        os.environ.update(
            {
                "DATABASE__POSTGRES_HOST": postgres.get_container_host_ip(),
                "DATABASE__POSTGRES_PORT": str(postgres.get_exposed_port(5432)),
                "DATABASE__POSTGRES_DB": postgres.dbname,
            }
        )
        if not os.environ["DATABASE__POSTGRES_DB"].startswith(TEST_DATABASE_PREFIX):
            raise RuntimeError("unsafe test database name")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=os.environ.copy(),
            check=True,
        )
    except BaseException as exc:
        postgres.stop()
        pytest.exit(f"Integration-тестам нужен Docker, Postgres не поднялся: {exc}", returncode=2)
    session.config.stash[_POSTGRES_KEY] = postgres

    dragonfly = DockerContainer(
        "docker.dragonflydb.io/dragonflydb/dragonfly:v2.0.2"
    ).with_exposed_ports(6379)
    try:
        dragonfly.start()
        host = dragonfly.get_container_host_ip()
        port = str(dragonfly.get_exposed_port(6379))
        probe = redis.Redis(host=host, port=int(port))
        deadline = time.monotonic() + 30
        while True:
            try:
                probe.ping()
                break
            except redis.RedisError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        os.environ.update({"CACHE__HOST": host, "CACHE__PORT": port})
    except BaseException as exc:
        dragonfly.stop()
        pytest.exit(f"Integration-тестам нужен Dragonfly, он не поднялся: {exc}", returncode=2)
    session.config.stash[_DRAGONFLY_KEY] = dragonfly


def pytest_sessionfinish(session: pytest.Session) -> None:
    postgres = session.config.stash.get(_POSTGRES_KEY, None)
    if postgres is not None:
        postgres.stop()
    dragonfly = session.config.stash.get(_DRAGONFLY_KEY, None)
    if dragonfly is not None:
        dragonfly.stop()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    layers = _suite(config).layers
    manifest = load_scenarios(TESTS_ROOT / "scenarios.toml")
    selected: list[pytest.Item] = []
    seen: dict[str, str] = {}
    for item in items:
        marker = item.get_closest_marker("case")
        if marker is None:
            raise pytest.UsageError(f"missing @pytest.mark.case: {item.nodeid}")
        case_id = marker.kwargs.get("id")
        if not isinstance(case_id, str) or (scenario := manifest.get(case_id)) is None:
            raise pytest.UsageError(f"case absent from scenarios.toml: {case_id} ({item.nodeid})")
        test_id = item.nodeid.split("[", 1)[0]
        if seen.setdefault(case_id, test_id) != test_id:
            raise pytest.UsageError(f"duplicate case id {case_id}: {seen[case_id]}, {test_id}")
        expected_dir = TESTS_ROOT / scenario.layer / scenario.domain
        if expected_dir not in Path(str(item.path)).parents:
            raise pytest.UsageError(
                f"{case_id}: file must live under {expected_dir.relative_to(ROOT)}"
            )
        if scenario.layer not in layers:
            continue
        if scenario.status == ScenarioStatus.KNOWN_BUG:
            item.add_marker(pytest.mark.xfail(strict=True, reason=scenario.reason))
        selected.append(item)

    full_tree_requested = any(
        Path(argument).resolve() == TESTS_ROOT
        for argument in config.args
        if not argument.startswith("-")
    )
    if full_tree_requested:
        missing = {s.id for s in manifest.values() if s.layer in layers} - seen.keys()
        if missing:
            raise pytest.UsageError(
                "manifest scenarios were not collected: " + ", ".join(sorted(missing))
            )
    deselected = [item for item in items if item not in selected]
    items[:] = selected
    if deselected:
        config.hook.pytest_deselected(items=deselected)


@pytest.fixture(autouse=True)
def block_external_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    layer = Layer(Path(str(request.node.path)).relative_to(TESTS_ROOT).parts[0])
    real_connect = socket.socket.connect

    def guarded_connect(sock: socket.socket, address: tuple[object, ...] | str) -> None:
        host = address[0] if isinstance(address, tuple) else None
        if layer == Layer.INTEGRATION and host in {"127.0.0.1", "::1", "localhost"}:
            real_connect(sock, address)
            return
        raise RuntimeError(f"network is forbidden in {layer} tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield
