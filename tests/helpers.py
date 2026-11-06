from datetime import datetime, timezone


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_reading(crate_id="CW-01", seq=1, **overrides):
    payload = {
        "crate_id": crate_id,
        "shipment_id": "SHP-TEST-01",
        "seq": seq,
        "event_ts": iso_now(),
        "temp_c": 21.0,
        "humidity_pct": 50.0,
        "shock_g": 0.4,
        "door_open": False,
        "battery_pct": 90.0,
    }
    payload.update(overrides)
    return payload
