from enum import StrEnum


class ErrorLayer(StrEnum):
    HTTP = "http"
    DOMAIN = "domain"
    CORE = "core"
    INTEGRATION = "integration"
    DB = "db"
    APP = "app"
    EXTERNAL = "external"
