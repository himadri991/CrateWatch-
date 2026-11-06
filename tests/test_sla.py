from datetime import timedelta

from app import db, sla
from app.crates import CRATES
from app.rules import evaluate_reading

from tests.helpers import make_reading


def test_percentile_nearest_rank():
    values = list(range(1, 101))
    assert sla.percentile(values, 50) == 50
    assert sla.percentile(values, 95) == 95
    assert sla.percentile(values, 99) == 99
    assert sla.percentile([], 95) is None


def test_availability_drops_when_readings_are_missing(test_settings):
    db.init_db(test_settings.db_path)
    crate_ids = [item["id"] for item in CRATES]
    now = db.utc_now()

    with db.db_session(test_settings.db_path) as conn:
        for index, crate_id in enumerate(crate_ids):
            for step in range(5):
                moment = now - timedelta(seconds=40) + timedelta(seconds=step * 2)
                reading = make_reading(crate_id=crate_id, seq=index * 100 + step)
                reading["event_ts"] = db.to_iso(moment)
                db.insert_telemetry(conn, reading, db.to_iso(moment))
            last = now - timedelta(seconds=12)
            reading = make_reading(crate_id=crate_id, seq=index * 100 + 99)
            reading["event_ts"] = db.to_iso(last)
            db.insert_telemetry(conn, reading, db.to_iso(last))

        result = sla.compute_availability(conn, test_settings, crate_ids)

    assert result["samples_received"] == 36
    assert result["samples_missing"] > 0
    assert result["availability_pct"] < 100


def test_ttr_is_computed_from_detected_to_resolved(test_settings):
    db.init_db(test_settings.db_path)
    with db.db_session(test_settings.db_path) as conn:
        reading = make_reading(seq=1, shock_g=12.4)
        reading["event_ts"] = db.now_iso()
        db.insert_telemetry(conn, reading, db.now_iso())
        evaluate_reading(conn, reading, test_settings)
        incident = conn.execute("SELECT * FROM incidents").fetchone()
        detected = db.parse_iso(incident["detected_at"])
        resolved = db.to_iso(detected + timedelta(seconds=42))
        conn.execute(
            "UPDATE incidents SET status = 'RESOLVED', resolved_at = ? WHERE id = ?",
            (resolved, incident["id"]),
        )
        conn.commit()
        result = sla.compute_ttr(conn, "S1")

    assert result["resolved_count"] == 1
    assert result["ttr_p95_seconds"] == 42.0
