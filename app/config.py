import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("CRATEWATCH_DB", "data/cratewatch.db"))
    demo_mode: bool = field(default_factory=lambda: _env_bool("CRATEWATCH_DEMO_MODE", True))
    admin_token: str = field(default_factory=lambda: os.getenv("CRATEWATCH_ADMIN_TOKEN", "local-demo-token"))
    background_rules: bool = field(default_factory=lambda: _env_bool("CRATEWATCH_BACKGROUND_RULES", True))
    rules_interval_seconds: float = field(default_factory=lambda: _env_float("CRATEWATCH_RULES_INTERVAL", 2.0))
    telemetry_interval_seconds: float = field(default_factory=lambda: _env_float("CRATEWATCH_TELEMETRY_INTERVAL", 2.0))
    gap_threshold_seconds: float = field(default_factory=lambda: _env_float("CRATEWATCH_GAP_THRESHOLD", 10.0))
    sla_window_minutes: int = field(default_factory=lambda: _env_int("CRATEWATCH_SLA_WINDOW_MINUTES", 15))
    availability_target: float = field(default_factory=lambda: _env_float("CRATEWATCH_AVAILABILITY_TARGET", 99.5))
    api_p95_target_ms: float = field(default_factory=lambda: _env_float("CRATEWATCH_API_P95_TARGET_MS", 300.0))
    alert_p95_target_seconds: float = field(default_factory=lambda: _env_float("CRATEWATCH_ALERT_P95_TARGET_SECONDS", 5.0))
    ttr_s1_target_minutes: float = field(default_factory=lambda: _env_float("CRATEWATCH_TTR_S1_TARGET_MINUTES", 15.0))
    ttr_s2_target_minutes: float = field(default_factory=lambda: _env_float("CRATEWATCH_TTR_S2_TARGET_MINUTES", 60.0))
    ingestion_delay_target_seconds: float = field(default_factory=lambda: _env_float("CRATEWATCH_INGESTION_DELAY_TARGET", 30.0))
    alert_webhook_url: str = field(default_factory=lambda: os.getenv("CRATEWATCH_ALERT_WEBHOOK_URL", ""))
    alert_sns_topic_arn: str = field(default_factory=lambda: os.getenv("CRATEWATCH_ALERT_SNS_TOPIC_ARN", ""))
    evidence_bucket: str = field(default_factory=lambda: os.getenv("CRATEWATCH_EVIDENCE_BUCKET", ""))
    app_name: str = "CrateWatch"
    shipment_id: str = field(default_factory=lambda: os.getenv("CRATEWATCH_SHIPMENT_ID", "SHP-2026-11-07-01"))

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)

    def ensure_dirs(self) -> None:
        self.db_file.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
