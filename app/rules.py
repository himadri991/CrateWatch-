import json
from typing import Any

from app import db, metrics
from app.alerts import notify_incident
from app.config import Settings


def rules_for_reading(reading: dict[str, Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    if float(reading["shock_g"]) >= 8.0:
        matches.append(
            {
                "rule_id": "SHOCK_LIMIT",
                "severity": "S1",
                "title": "Shock limit exceeded",
                "threshold": "8.0 g",
                "breach_value": float(reading["shock_g"]),
            }
        )

    if float(reading["temp_c"]) < 15.0 or float(reading["temp_c"]) > 25.0:
        matches.append(
            {
                "rule_id": "TEMP_RANGE",
                "severity": "S1",
                "title": "Temperature outside safe range",
                "threshold": "15.0 to 25.0 C",
                "breach_value": float(reading["temp_c"]),
            }
        )

    if float(reading["humidity_pct"]) < 40.0 or float(reading["humidity_pct"]) > 60.0:
        matches.append(
            {
                "rule_id": "HUMIDITY_RANGE",
                "severity": "S2",
                "title": "Humidity outside safe range",
                "threshold": "40 to 60 percent",
                "breach_value": float(reading["humidity_pct"]),
            }
        )

    if bool(reading["door_open"]):
        matches.append(
            {
                "rule_id": "DOOR_OPEN",
                "severity": "S2",
                "title": "Crate door opened in transit",
                "threshold": "closed",
                "breach_value": 1.0,
            }
        )

    if float(reading["battery_pct"]) < 20.0:
        matches.append(
            {
                "rule_id": "BATTERY_LOW",
                "severity": "S4",
                "title": "Crate battery low",
                "threshold": "20 percent",
                "breach_value": float(reading["battery_pct"]),
            }
        )

    return matches


def _active_incident(conn, crate_id: str, rule_id: str):
    return conn.execute(
        """
        SELECT * FROM incidents
        WHERE crate_id = ? AND rule_id = ? AND status IN ('OPEN', 'ACK')
        ORDER BY id DESC
        LIMIT 1
        """,
        (crate_id, rule_id),
    ).fetchone()


def open_or_touch_incident(
    conn,
    crate_id: str,
    rule_id: str,
    severity: str,
    title: str,
    event_ts: str | None,
    threshold: str,
    breach_value: float,
    settings: Settings,
) -> tuple[int, bool, dict[str, Any] | None]:
    detected_at = db.now_iso()
    with db.WRITE_LOCK:
        existing = _active_incident(conn, crate_id, rule_id)
        if existing is not None:
            conn.execute(
                """
                UPDATE incidents
                SET last_seen_at = ?, breach_value = ?, threshold = ?
                WHERE id = ?
                """,
                (detected_at, breach_value, threshold, existing["id"]),
            )
            conn.commit()
            return int(existing["id"]), False, None

        cursor = conn.execute(
            """
            INSERT INTO incidents (
                crate_id, rule_id, severity, title, status, event_ts,
                detected_at, opened_at, last_seen_at, breach_value, threshold
            ) VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?)
            """,
            (
                crate_id,
                rule_id,
                severity,
                title,
                event_ts,
                detected_at,
                detected_at,
                detected_at,
                breach_value,
                threshold,
            ),
        )
        incident_id = int(cursor.lastrowid)
        incident = {
            "id": incident_id,
            "crate_id": crate_id,
            "rule_id": rule_id,
            "severity": severity,
            "title": title,
            "status": "OPEN",
            "event_ts": event_ts,
            "detected_at": detected_at,
            "opened_at": detected_at,
            "last_seen_at": detected_at,
            "breach_value": breach_value,
            "threshold": threshold,
        }
        conn.execute(
            """
            INSERT INTO events (ts, kind, crate_id, incident_id, message, payload)
            VALUES (?, 'incident_opened', ?, ?, ?, ?)
            """,
            (
                detected_at,
                crate_id,
                incident_id,
                f"{severity} {title}",
                json.dumps(
                    {
                        "severity": severity,
                        "rule_id": rule_id,
                        "threshold": threshold,
                        "breach_value": breach_value,
                    },
                    separators=(",", ":"),
                ),
            ),
        )
        conn.commit()

    metrics.INCIDENTS_OPENED.labels(severity=severity, rule_id=rule_id).inc()
    notify_incident(incident, settings)
    return incident_id, True, incident


def evaluate_reading(conn, reading: dict[str, Any], settings: Settings) -> list[int]:
    incident_ids: list[int] = []
    for match in rules_for_reading(reading):
        incident_id, _created, _incident = open_or_touch_incident(
            conn,
            crate_id=reading["crate_id"],
            rule_id=match["rule_id"],
            severity=match["severity"],
            title=match["title"],
            event_ts=reading["event_ts"],
            threshold=match["threshold"],
            breach_value=match["breach_value"],
            settings=settings,
        )
        incident_ids.append(incident_id)
    return incident_ids


def check_telemetry_gaps(conn, crate_ids: list[str], settings: Settings) -> list[int]:
    now = db.utc_now()
    incident_ids: list[int] = []

    for crate_id in crate_ids:
        latest = db.latest_telemetry(conn, crate_id)
        if latest is None:
            continue
        last_received = db.parse_iso(latest["received_ts"])
        gap_seconds = (now - last_received).total_seconds()
        if gap_seconds < settings.gap_threshold_seconds:
            continue

        incident_id, _created, _incident = open_or_touch_incident(
            conn,
            crate_id=crate_id,
            rule_id="TELEMETRY_GAP",
            severity="S3",
            title="Telemetry gap detected",
            event_ts=latest["received_ts"],
            threshold=f"{settings.gap_threshold_seconds:.0f} seconds",
            breach_value=round(gap_seconds, 1),
            settings=settings,
        )
        incident_ids.append(incident_id)

    return incident_ids
