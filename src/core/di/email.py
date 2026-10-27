from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from src.core.email.client import EmailClient
from src.core.email.service import EmailService


class EmailProvider(Provider):
    email_service = provide(EmailService, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def get_client(self) -> AsyncIterator[EmailClient]:
        client = EmailClient()
        yield client
        await client.close()
