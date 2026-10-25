from prometheus_client import Gauge

ADMISSION_CAPACITY = Gauge(
    "http_requests_capacity", "Предел одновременных запросов процесса, сверх него — отказ"
)
