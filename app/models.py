from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class TelemetryIn(BaseModel):
    crate_id: str = Field(pattern=r"^CW-\d{2}$")
    shipment_id: str = Field(min_length=3, max_length=64)
    seq: int = Field(ge=0)
    event_ts: datetime
    temp_c: float = Field(ge=-40.0, le=80.0)
    humidity_pct: float = Field(ge=0.0, le=100.0)
    shock_g: float = Field(ge=0.0, le=50.0)
    door_open: bool = False
    battery_pct: float = Field(ge=0.0, le=100.0)

    @field_validator("event_ts")
    @classmethod
    def event_ts_must_be_reasonable(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        moment = value.astimezone(timezone.utc)
        if moment > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("event_ts is too far in the future")
        return moment


class TelemetryBatch(BaseModel):
    readings: list[TelemetryIn] = Field(min_length=1, max_length=500)


class IncidentNote(BaseModel):
    notes: str = Field(default="", max_length=500)


class BreachKind(str, Enum):
    shock = "shock"
    heat = "heat"
    humidity = "humidity"
    door = "door"
    battery = "battery"


class DemoBreach(BaseModel):
    crate_id: str = Field(pattern=r"^CW-\d{2}$")
    kind: BreachKind
