from prometheus_client import Gauge, Histogram

PASSWORD_DURATION = Histogram(
    "auth_password_duration_seconds",
    "Ожидание слота, вычисление Argon2 и полная длительность операции с паролем",
    ["operation", "stage"],
    buckets=(0.0001, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10),
)
PASSWORD_OPERATIONS = Gauge(
    "auth_password_operations",
    "Операции с паролем в очереди и внутри Argon2",
    ["operation", "state"],
)
