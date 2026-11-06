import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

WRITE_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crate_id TEXT NOT NULL,
    shipment_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_ts TEXT NOT NULL,
    received_ts TEXT NOT NULL,
    temp_c REAL NOT NULL,
    humidity_pct REAL NOT NULL,
    shock_g REAL NOT NULL,
    door_open INTEGER NOT NULL,
    battery_pct REAL NOT NULL,
    UNIQUE(crate_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_telemetry_crate_received
    ON telemetry(crate_id, received_ts);
CREATE INDEX IF NOT EXISTS idx_telemetry_received
    ON telemetry(received_ts);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crate_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    event_ts TEXT,
    detected_at TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    ack_at TEXT,
    recovered_at TEXT,
    resolved_at TEXT,
    last_seen_at TEXT NOT NULL,
    breach_value REAL,
    threshold TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_incidents_status
    ON incidents(status, severity);
CREATE INDEX IF NOT EXISTS idx_incidents_crate
    ON incidents(crate_id, detected_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_one_active
    ON incidents(crate_id, rule_id)
    WHERE status IN ('OPEN', 'ACK');

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    crate_id TEXT,
    incident_id INTEGER,
    message TEXT NOT NULL,
    payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now_iso() -> str:
    return to_iso(utc_now())


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def db_session(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_telemetry(conn: sqlite3.Connection, reading: dict[str, Any], received_ts: str) -> bool:
    with WRITE_LOCK:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO telemetry (
                crate_id, shipment_id, seq, event_ts, received_ts,
                temp_c, humidity_pct, shock_g, door_open, battery_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reading["crate_id"],
                reading["shipment_id"],
                int(reading["seq"]),
                reading["event_ts"],
                received_ts,
                float(reading["temp_c"]),
                float(reading["humidity_pct"]),
                float(reading["shock_g"]),
                1 if reading["door_open"] else 0,
                float(reading["battery_pct"]),
            ),
        )
        conn.commit()
        return cursor.rowcount == 1


def latest_telemetry(conn: sqlite3.Connection, crate_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM telemetry
        WHERE crate_id = ?
        ORDER BY received_ts DESC, id DESC
        LIMIT 1
        """,
        (crate_id,),
    ).fetchone()


def latest_by_crate(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT * FROM (
            SELECT t.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY crate_id
                       ORDER BY received_ts DESC, id DESC
                   ) AS rn
            FROM telemetry t
        )
        WHERE rn = 1
        """
    ).fetchall()
    return {row["crate_id"]: row for row in rows}


def log_event(
    conn: sqlite3.Connection,
    kind: str,
    message: str,
    crate_id: str | None = None,
    incident_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    with WRITE_LOCK:
        conn.execute(
            """
            INSERT INTO events (ts, kind, crate_id, incident_id, message, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                kind,
                crate_id,
                incident_id,
                message,
                json.dumps(payload, separators=(",", ":")) if payload else None,
            ),
        )
        conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}
