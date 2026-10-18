import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC_ROOT.parent).with_suffix("").parts)


def imports(path: Path) -> list[tuple[int, str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.append((node.lineno, node.module or "", node.level))
        elif isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name, 0) for alias in node.names)
    return found


def violations(paths: list[Path], forbidden: tuple[str, ...]) -> list[str]:
    return [
        f"{path.relative_to(SRC_ROOT.parent)}:{lineno}: {module}"
        for path in paths
        for lineno, module, _ in imports(path)
        if module == forbidden or module.startswith(forbidden)
    ]


@pytest.mark.case(id="ARCH-IMPORTS-001")
def test_core_never_imports_api() -> None:
    di_root = SRC_ROOT / "core" / "di"
    paths = sorted(p for p in (SRC_ROOT / "core").rglob("*.py") if di_root not in p.parents)
    assert paths

    assert violations(paths, ("src.api",)) == []


@pytest.mark.case(id="ARCH-IMPORTS-002")
def test_api_domains_do_not_import_each_other() -> None:
    found: list[str] = []
    domains = [p for p in (SRC_ROOT / "api").iterdir() if p.is_dir() and p.name != "exc"]
    assert domains
    for domain in domains:
        others = tuple(f"src.api.{d.name}" for d in domains if d != domain)
        found += violations(sorted(domain.rglob("*.py")), others)

    assert found == []


@pytest.mark.case(id="ARCH-IMPORTS-003")
def test_routers_do_not_touch_database_layer() -> None:
    routers = sorted((SRC_ROOT / "api").rglob("router.py"))
    assert routers
    forbidden = (
        "sqlalchemy",
        "src.core.db.models",
        "src.core.db.repositories",
        "src.core.db.uow",
        "src.core.db.db",
    )

    assert violations(routers, forbidden) == []


@pytest.mark.case(id="ARCH-IMPORTS-004")
def test_src_uses_only_absolute_imports() -> None:
    relative = [
        f"{path.relative_to(SRC_ROOT.parent)}:{lineno}"
        for path in sorted(SRC_ROOT.rglob("*.py"))
        for lineno, _, level in imports(path)
        if level > 0
    ]

    assert relative == []
