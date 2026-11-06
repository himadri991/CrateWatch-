import threading
from collections import deque

from prometheus_client import Counter, Gauge, Histogram

TELEMETRY_RECEIVED = Counter(
    "cratewatch_telemetry_received_total",
    "Telemetry readings accepted by the ingestion API",
    ["crate_id"],
)
TELEMETRY_DUPLICATES = Counter(
    "cratewatch_telemetry_duplicates_total",
    "Telemetry readings rejected as duplicates",
    ["crate_id"],
)
INCIDENTS_OPENED = Counter(
    "cratewatch_incidents_opened_total",
    "Incidents opened by the rules engine",
    ["severity", "rule_id"],
)
INCIDENT_TTR = Histogram(
    "cratewatch_incident_ttr_seconds",
    "Time to resolution for closed incidents",
    ["severity"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
)
HTTP_LATENCY = Histogram(
    "cratewatch_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
FLEET_ONLINE = Gauge(
    "cratewatch_fleet_crates_online",
    "Number of crates that sent telemetry inside the gap threshold",
)

_latency_lock = threading.Lock()
_api_latencies_ms: deque[float] = deque(maxlen=4000)


def observe_api_latency(duration_ms: float) -> None:
    with _latency_lock:
        _api_latencies_ms.append(duration_ms)


def api_latency_snapshot() -> list[float]:
    with _latency_lock:
        return list(_api_latencies_ms)
