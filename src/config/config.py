from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

BASE_DIR = Path(__file__).parent.parent.parent
TOML_SETTINGS_PATH = BASE_DIR / "config.toml"

PathsSources: list[tuple[Path, type[PydanticBaseSettingsSource]]] = [
    (TOML_SETTINGS_PATH, TomlConfigSettingsSource),
]


class Service(BaseModel):
    name: str = "auth"
    port: int = 8001
    public_host: str = "host.docker.internal"
    route_prefix: str = "/api/auth"


class Database(BaseModel):
    postgres_username: str = ""
    postgres_db: str = ""
    postgres_port: int = 5432
    postgres_host: str = ""
    postgres_password: str = ""

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


class Registry(BaseModel):
    enabled: bool = True
    consul_url: str = ""
    check_interval_seconds: int = 5
    deregister_after_minutes: int = 1
    timeout_seconds: float = 5


class Gateway(BaseModel):
    rate_limit_average: int = 10
    rate_limit_burst: int = 10
    rate_limit_period: str = "1s"


class Tracing(BaseModel):
    enabled: bool = True
    otlp_endpoint: str = ""


class Auth(BaseModel):
    private_key_path: str = ""
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    cookie_secure: bool = True
    password_min_length: int = 8
    password_max_length: int = 128


class Logging(BaseModel):
    level: str = "INFO"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        toml_file=TOML_SETTINGS_PATH,
        env_nested_delimiter="__",
    )

    service: Service = Service()
    database: Database = Database()
    cache: Cache = Cache()
    registry: Registry = Registry()
    gateway: Gateway = Gateway()
    tracing: Tracing = Tracing()
    auth: Auth = Auth()
    logging: Logging = Logging()

    def missing_required(self) -> list[str]:
        required = {
            "database.postgres_host": self.database.postgres_host,
            "database.postgres_db": self.database.postgres_db,
            "database.postgres_username": self.database.postgres_username,
            "cache.host": self.cache.host,
            "auth.private_key_path": self.auth.private_key_path,
        }
        if self.registry.enabled:
            required["registry.consul_url"] = self.registry.consul_url
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
        active_sources = [method(settings_cls) for path, method in PathsSources if path.exists()]
        return EnvSettingsSource(settings_cls), *active_sources


cfg = Config()
