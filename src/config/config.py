from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

BASE_DIR = Path(__file__).parent.parent.parent
TOML_SETTINGS_PATH = BASE_DIR / "config.toml"

PATHS_SOURCES: list[tuple[Path, type[PydanticBaseSettingsSource]]] = [
    (TOML_SETTINGS_PATH, TomlConfigSettingsSource),
]


class Service(BaseModel):
    name: str = "auth"
    # тег образа, его подставляет сборка; на хосте — dev
    version: str = "dev"
    port: int = 8001
    bind_host: str = "127.0.0.1"
    route_prefix: str = "/api/v1/auth"
    # пропускная способность процесса × допустимое время ответа (закон Литтла): ~220/с × ~0,3 с
    max_concurrent_requests: int = Field(default=64, ge=1)
    overload_retry_after_seconds: int = Field(default=2, ge=1)


class Database(BaseModel):
    postgres_username: str = ""
    postgres_db: str = ""
    postgres_port: int = 5432
    postgres_host: str = ""
    postgres_password: str = ""
    # постоянный пул без overflow: соединения сверх пула открывались и закрывались на каждом пике
    pool_size: int = Field(default=10, ge=1)
    pool_max_overflow: int = Field(default=0, ge=0)
    pool_timeout_seconds: float = Field(default=2, gt=0)
    pool_recycle_seconds: int = Field(default=1800, ge=1)
    statement_timeout_ms: int = Field(default=5000, ge=1)
    lock_timeout_ms: int = Field(default=2000, ge=1)

    @property
    def async_database_url(self) -> str:
        user = quote(self.postgres_username, safe="")
        password = quote(self.postgres_password, safe="")
        return f"postgresql+asyncpg://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


class Cache(BaseModel):
    host: str = ""
    port: int = 6379
    password: str = ""
    db: int = 0
    key_prefix: str = "auth:"
    timeout_seconds: float = 2

    @property
    def url(self) -> str:
        credentials = f"default:{quote(self.password, safe='')}@" if self.password else ""
        return f"redis://{credentials}{self.host}:{self.port}/{self.db}"


class Tracing(BaseModel):
    enabled: bool = True
    otlp_endpoint: str = ""


class Auth(BaseModel):
    private_key_path: str = ""
    audience: str = "aiip"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_reuse_grace_seconds: int = 10
    access_cookie_path: str = "/"
    cookie_secure: bool = True
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost", "https://localhost"]
    )
    otp_code_ttl_seconds: int = Field(default=300, ge=1)
    otp_challenge_ttl_seconds: int = Field(default=900, ge=1)
    otp_max_attempts: int = Field(default=5, ge=1)
    otp_resend_interval_seconds: int = Field(default=60, ge=0)
    otp_max_resends: int = Field(default=3, ge=0)
    # каждое письмо стоит квоты почтового провайдера
    # письмо старой почте о смене: ждать его отправки дольше суток незачем
    email_changed_letter_ttl_seconds: int = Field(default=86400, ge=1)
    otp_sends_per_email_per_hour: int = Field(default=10, ge=1)


class Rabbitmq(BaseModel):
    url: str = ""
    connect_timeout_seconds: float = Field(default=2, gt=0)
    publish_timeout_seconds: float = Field(default=2, gt=0)


class Email(BaseModel):
    exchange: str = "email"
    transactional_routing_key: str = "send.transactional"
    locale: str = "ru"


class Events(BaseModel):
    # topic exchange событий о пользователях; очереди объявляют потребители
    exchange: str = "auth.events"


class Logging(BaseModel):
    level: str = "INFO"
    slow_request_ms: int = 1000


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        toml_file=TOML_SETTINGS_PATH,
        env_nested_delimiter="__",
    )

    service: Service = Service()
    database: Database = Database()
    cache: Cache = Cache()
    tracing: Tracing = Tracing()
    auth: Auth = Auth()
    rabbitmq: Rabbitmq = Rabbitmq()
    email: Email = Email()
    events: Events = Events()
    logging: Logging = Logging()

    def missing_required(self) -> list[str]:
        required = {
            "database.postgres_host": self.database.postgres_host,
            "database.postgres_db": self.database.postgres_db,
            "database.postgres_username": self.database.postgres_username,
            "cache.host": self.cache.host,
            "rabbitmq.url": self.rabbitmq.url,
            "auth.private_key_path": self.auth.private_key_path,
        }
        if self.tracing.enabled:
            required["tracing.otlp_endpoint"] = self.tracing.otlp_endpoint
        return [name for name, value in required.items() if not value]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        active_sources = [method(settings_cls) for path, method in PATHS_SOURCES if path.exists()]
        return EnvSettingsSource(settings_cls), *active_sources


cfg = Config()
