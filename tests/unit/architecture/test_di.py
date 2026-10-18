from typing import Annotated, get_args, get_origin, get_type_hints

import pytest
from dishka import AsyncContainer, DependencyKey, FromComponent
from dishka.entities.component import DEFAULT_COMPONENT
from dishka.registry import Registry
from fastapi.routing import APIRoute, iter_route_contexts

from src.main import app, container


def is_registered(container: AsyncContainer, dependency: object) -> bool:
    key = DependencyKey(dependency, DEFAULT_COMPONENT)
    registry: Registry | None = container.registry
    while registry is not None:
        if registry.get_factory(key) is not None:
            return True
        registry = registry.child_registry
    return False


def requested_dependencies(route: APIRoute) -> list[object]:
    from_dishka_marker = type(FromComponent())
    hints = get_type_hints(route.endpoint, include_extras=True)
    return [
        get_args(hint)[0]
        for hint in hints.values()
        if get_origin(hint) is Annotated
        and any(isinstance(meta, from_dishka_marker) for meta in get_args(hint)[1:])
    ]


@pytest.mark.case(id="ARCH-DI-001")
def test_every_route_dependency_is_registered_in_container() -> None:
    routes = [
        context.original_route
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute)
    ]
    missing = [
        f"{route.path}: {dependency}"
        for route in routes
        for dependency in requested_dependencies(route)
        if not is_registered(container, dependency)
    ]

    assert routes
    assert missing == []
