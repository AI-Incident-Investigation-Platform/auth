from dishka import Provider, Scope, provide

from src.api.health.service import HealthService


class HealthProvider(Provider):
    health_service = provide(HealthService, scope=Scope.REQUEST)
