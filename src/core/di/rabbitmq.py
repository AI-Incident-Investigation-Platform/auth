from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from src.core.email.service import EmailService
from src.core.events.service import UserEventsService
from src.core.rabbitmq.client import RabbitmqClient


class RabbitmqProvider(Provider):
    email_service = provide(EmailService, scope=Scope.APP)
    user_events_service = provide(UserEventsService, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def get_client(self) -> AsyncIterator[RabbitmqClient]:
        client = RabbitmqClient()
        yield client
        await client.close()
