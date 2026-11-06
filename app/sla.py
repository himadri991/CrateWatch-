import math
from datetime import timedelta
from typing import Any, Iterable

from app import db, metrics
from app.config import Settings
from app.crates import CRATE_INDEX, CRATES


def percentile(values: Iterable[float], pct: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = math.ceil((pct / 100.0) * len(ordered)) - 1
    rank = min(max(rank, 0), len(ordered) - 1)
    return ordered[rank]


def _seconds_between(start: str, end: str) -> float:
    return (db.parse_iso(end) - db.parse_iso(start)).total_seconds()


def compute_availability(conn, settings: Settings, crate_ids: list[str]) -> dict[str, Any]:
    now = db.utc_now()
    window_start = now - timedelta(minutes=settings.sla_window_minutes)
    interval = max(settings.telemetry_interval_seconds, 0.1)
    actual = 0
    missing = 0

    for crate_id in crate_ids:
        rows = conn.execute(
            """
            SELECT received_ts FROM telemetry
            WHERE crate_id = ? AND received_ts >= ?
            ORDER BY received_ts ASC
            """,
            (crate_id, db.to_iso(window_start)),
        ).fetchall()
        if not rows:
            missing += int((settings.sla_window_minutes * 60) / interval)
            continue

        actual += len(rows)
        stamps = [row["received_ts"] for row in rows]
        for previous, current in zip(stamps, stamps[1:]):
            gap = _seconds_between(previous, current)
            if gap > interval * 1.8:
                missing += max(0, round(gap / interval) - 1)

        last_gap = (now - db.parse_iso(stamps[-1])).total_seconds()
        if last_gap > interval * 1.8:
            tail_missing = max(0, round(last_gap / interval) - 1)
            missing += min(tail_missing, int((settings.sla_window_minutes * 60) / interval))

    expected = actual + missing
    availability = (actual / expected * 100.0) if expected else None
    return {
        "availability_pct": round(availability, 3) if availability is not None else None,
        "samples_received": actual,
        "samples_missing": missing,
        "samples_expected": expected,
    }


def compute_alert_latency(conn, settings: Settings) -> dict[str, Any]:
    window_start = db.utc_now() - timedelta(minutes=settings.sla_window_minutes)
    rows = conn.execute(
        """
        SELECT event_ts, detected_at FROM incidents
        WHERE event_ts IS NOT NULL AND detected_at >= ?
        """,
        (db.to_iso(window_start),),
    ).fetchall()
    latencies = []
    for row in rows:
        value = _seconds_between(row["event_ts"], row["detected_at"])
        latencies.append(max(0.0, value))
    return {
        "alert_latency_p95_seconds": round(percentile(latencies, 95), 3) if latencies else None,
        "alert_samples": len(latencies),
    }


def compute_ttr(conn, severity: str | None = None) -> dict[str, Any]:
    query = """
        SELECT severity, detected_at, ack_at, resolved_at FROM incidents
        WHERE resolved_at IS NOT NULL
    """
    params: list[Any] = []
    if severity:
        query += " AND severity = ?"
        params.append(severity)
    rows = conn.execute(query, params).fetchall()

    ttrs = []
    acks = []
    recovers = []
    for row in rows:
        ttrs.append(_seconds_between(row["detected_at"], row["resolved_at"]))
        if row["ack_at"]:
            acks.append(_seconds_between(row["detected_at"], row["ack_at"]))
        if row["ack_at"] and row["resolved_at"]:
            recovers.append(_seconds_between(row["ack_at"], row["resolved_at"]))

    return {
        "ttr_p95_seconds": round(percentile(ttrs, 95), 3) if ttrs else None,
        "ttr_avg_seconds": round(sum(ttrs) / len(ttrs), 3) if ttrs else None,
        "ack_p95_seconds": round(percentile(acks, 95), 3) if acks else None,
        "recovery_p95_seconds": round(percentile(recovers, 95), 3) if recovers else None,
        "resolved_count": len(ttrs),
    }


def compute_ingestion_delay(conn, settings: Settings) -> dict[str, Any]:
    window_start = db.utc_now() - timedelta(minutes=settings.sla_window_minutes)
    rows = conn.execute(
        """
        SELECT event_ts, received_ts FROM telemetry
        WHERE received_ts >= ?
        """,
        (db.to_iso(window_start),),
    ).fetchall()
    delays = [max(0.0, _seconds_between(row["event_ts"], row["received_ts"])) for row in rows]
    return {
        "ingestion_delay_p95_seconds": round(percentile(delays, 95), 3) if delays else None,
        "ingestion_samples": len(delays),
    }


def fleet_snapshot(conn, settings: Settings) -> list[dict[str, Any]]:
    latest = db.latest_by_crate(conn)
    active_rows = conn.execute(
        """
        SELECT id, crate_id, rule_id, severity, title, detected_at
        FROM incidents
        WHERE status IN ('OPEN', 'ACK')
        ORDER BY detected_at DESC
        """
    ).fetchall()
    by_crate: dict[str, list[dict[str, Any]]] = {}
    for row in active_rows:
        by_crate.setdefault(row["crate_id"], []).append({key: row[key] for key in row.keys()})

    now = db.utc_now()
    result = []
    online = 0

    for item in CRATES:
        crate_id = item["id"]
        row = latest.get(crate_id)
        open_incidents = by_crate.get(crate_id, [])
        severities = {incident["severity"] for incident in open_incidents}
        age_seconds = None
        status = "OFFLINE"

        if row is not None:
            age_seconds = round((now - db.parse_iso(row["received_ts"])).total_seconds(), 1)
            if age_seconds <= settings.gap_threshold_seconds:
                online += 1
                if "S1" in severities:
                    status = "CRITICAL"
                elif severities:
                    status = "WARNING"
                else:
                    status = "OK"
            else:
                status = "OFFLINE"
        elif open_incidents:
            status = "OFFLINE"

        result.append(
            {
                "id": crate_id,
                "artwork": item["artwork"],
                "artist": item["artist"],
                "medium": item["medium"],
                "crate": item["crate"],
                "status": status,
                "age_seconds": age_seconds,
                "open_incidents": len(open_incidents),
                "top_incident": open_incidents[0] if open_incidents else None,
                "reading": {
                    "event_ts": row["event_ts"],
                    "received_ts": row["received_ts"],
                    "temp_c": row["temp_c"],
                    "humidity_pct": row["humidity_pct"],
                    "shock_g": row["shock_g"],
                    "door_open": bool(row["door_open"]),
                    "battery_pct": row["battery_pct"],
                }
                if row
                else None,
            }
        )

    metrics.FLEET_ONLINE.set(online)
    return result


def compute_sla(conn, settings: Settings) -> dict[str, Any]:
    crate_ids = [item["id"] for item in CRATES]
    availability = compute_availability(conn, settings, crate_ids)
    alerts = compute_alert_latency(conn, settings)
    ingestion = compute_ingestion_delay(conn, settings)
    ttr_s1 = compute_ttr(conn, "S1")
    ttr_s2 = compute_ttr(conn, "S2")
    api_values = metrics.api_latency_snapshot()
    api_p95 = percentile(api_values, 95)

    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE status IN ('OPEN', 'ACK')"
    ).fetchone()["n"]
    resolved_count = conn.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE status = 'RESOLVED'"
    ).fetchone()["n"]

    observed = {
        "availability_pct": availability["availability_pct"],
        "alert_latency_p95_seconds": alerts["alert_latency_p95_seconds"],
        "api_latency_p95_ms": round(api_p95, 3) if api_p95 is not None else None,
        "ttr_s1_p95_seconds": ttr_s1["ttr_p95_seconds"],
        "ttr_s2_p95_seconds": ttr_s2["ttr_p95_seconds"],
        "ingestion_delay_p95_seconds": ingestion["ingestion_delay_p95_seconds"],
        "open_incidents": open_count,
        "resolved_incidents": resolved_count,
        "samples_received": availability["samples_received"],
        "samples_missing": availability["samples_missing"],
        "api_samples": len(api_values),
    }

    def status(observed_value, target, higher_is_better=False):
        if observed_value is None:
            return "NO_DATA"
        if higher_is_better:
            return "MET" if observed_value >= target else "NOT_MET"
        return "MET" if observed_value <= target else "NOT_MET"

    checks = {
        "availability": status(
            observed["availability_pct"], settings.availability_target, higher_is_better=True
        ),
        "alert_latency": status(
            observed["alert_latency_p95_seconds"], settings.alert_p95_target_seconds
        ),
        "api_latency": status(observed["api_latency_p95_ms"], settings.api_p95_target_ms),
        "ttr_s1": status(
            (observed["ttr_s1_p95_seconds"] / 60.0)
            if observed["ttr_s1_p95_seconds"] is not None
            else None,
            settings.ttr_s1_target_minutes,
        ),
        "ingestion_delay": status(
            observed["ingestion_delay_p95_seconds"], settings.ingestion_delay_target_seconds
        ),
    }
    overall = "NOT_MET" if "NOT_MET" in checks.values() else "MET"
    if all(value == "NO_DATA" for value in checks.values()):
        overall = "NO_DATA"

    return {
        "generated_at": db.now_iso(),
        "window_minutes": settings.sla_window_minutes,
        "targets": {
            "availability_pct": settings.availability_target,
            "alert_latency_p95_seconds": settings.alert_p95_target_seconds,
            "api_latency_p95_ms": settings.api_p95_target_ms,
            "ttr_s1_minutes": settings.ttr_s1_target_minutes,
            "ttr_s2_minutes": settings.ttr_s2_target_minutes,
            "ingestion_delay_p95_seconds": settings.ingestion_delay_target_seconds,
        },
        "observed": observed,
        "checks": checks,
        "overall": overall,
        "detail": {
            "availability": availability,
            "alerts": alerts,
            "ttr_s1": ttr_s1,
            "ttr_s2": ttr_s2,
            "ingestion": ingestion,
        },
    }


def crate_history(conn, crate_id: str, minutes: int, limit: int) -> list[dict[str, Any]]:
    window_start = db.utc_now() - timedelta(minutes=minutes)
    rows = conn.execute(
        """
        SELECT event_ts, received_ts, temp_c, humidity_pct, shock_g, door_open, battery_pct
        FROM telemetry
        WHERE crate_id = ? AND received_ts >= ?
        ORDER BY received_ts ASC
        LIMIT ?
        """,
        (crate_id, db.to_iso(window_start), limit),
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def known_crate(crate_id: str) -> bool:
    return crate_id in CRATE_INDEX
