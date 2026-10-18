from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceInstance:
    id: str
    name: str
    address: str
    port: int
    tags: tuple[str, ...]
    check_url: str
    check_interval_seconds: int
    deregister_after_minutes: int
