import argparse
import json
import logging
import random
import signal
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cratewatch.edge")

CRATE_PROFILES = [
    {"id": "CW-01", "temp": 20.6, "humidity": 48.0, "battery": 94.0},
    {"id": "CW-02", "temp": 21.0, "humidity": 47.0, "battery": 91.0},
    {"id": "CW-03", "temp": 20.2, "humidity": 50.0, "battery": 88.0},
    {"id": "CW-04", "temp": 21.4, "humidity": 46.0, "battery": 85.0},
    {"id": "CW-05", "temp": 20.8, "humidity": 49.0, "battery": 79.0},
    {"id": "CW-06", "temp": 21.1, "humidity": 51.0, "battery": 96.0},
]

SCENARIO_CHOICES = ["normal", "shock", "heat", "humidity", "door", "battery", "gap", "mixed"]


def utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class EdgeBuffer:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_buffer_sent ON buffer(sent, id);
            """
        )
        self.conn.commit()

    def next_seq(self, crate_id: str) -> int:
        key = f"seq:{crate_id}"
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        value = int(row["value"]) + 1 if row else 1
        self.conn.execute(
            """
            INSERT INTO meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        self.conn.commit()
        return value

    def add(self, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO buffer (payload, created_at, sent) VALUES (?, ?, 0)",
            (json.dumps(payload, separators=(",", ":")), utc_iso()),
        )
        self.conn.commit()

    def unsent(self, limit: int = 500) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, payload FROM buffer WHERE sent = 0 ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()

    def delete(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM buffer WHERE id IN ({placeholders})", ids)
        self.conn.commit()

    def pending(self) -> int:
        return int(
            self.conn.execute("SELECT COUNT(*) AS n FROM buffer WHERE sent = 0").fetchone()["n"]
        )

    def close(self) -> None:
        self.conn.close()


@dataclass
class CrateState:
    crate_id: str
    temp: float
    humidity: float
    battery: float
    rng: random.Random
    shock_g: float = 0.3
    door_open: bool = False
    scenario_applied: set[str] = field(default_factory=set)

    def next_reading(self, tick: int, scenario: str) -> dict[str, Any] | None:
        if scenario == "gap" and self.crate_id == "CW-05" and 6 <= tick <= 12:
            return None
        if scenario == "mixed" and self.crate_id == "CW-05" and 20 <= tick <= 26:
            return None

        self.temp = min(23.5, max(18.5, self.temp + self.rng.uniform(-0.18, 0.18)))
        self.humidity = min(58.0, max(42.0, self.humidity + self.rng.uniform(-0.8, 0.8)))
        self.battery = max(20.0, self.battery - 0.015)
        self.shock_g = (
            self.rng.uniform(2.0, 3.2) if self.rng.random() < 0.02 else self.rng.uniform(0.1, 0.8)
        )
        self.door_open = False

        if scenario == "shock" and self.crate_id == "CW-03" and tick == 6:
            self.shock_g = 12.4
        if scenario == "heat" and self.crate_id == "CW-02" and 6 <= tick <= 9:
            self.temp = 27.8
        if scenario == "humidity" and self.crate_id == "CW-04" and 7 <= tick <= 10:
            self.humidity = 68.0
        if scenario == "door" and self.crate_id == "CW-01" and tick == 8:
            self.door_open = True
        if scenario == "battery" and self.crate_id == "CW-05" and tick >= 5:
            self.battery = 14.0

        if scenario == "mixed":
            if self.crate_id == "CW-03" and tick == 6:
                self.shock_g = 12.4
            if self.crate_id == "CW-02" and 8 <= tick <= 11:
                self.temp = 27.8
            if self.crate_id == "CW-04" and 12 <= tick <= 15:
                self.humidity = 68.0
            if self.crate_id == "CW-01" and tick == 16:
                self.door_open = True
            if self.crate_id == "CW-05" and tick >= 18:
                self.battery = 14.0

        return {
            "crate_id": self.crate_id,
            "temp_c": round(self.temp, 2),
            "humidity_pct": round(self.humidity, 2),
            "shock_g": round(self.shock_g, 2),
            "door_open": self.door_open,
            "battery_pct": round(self.battery, 2),
        }


def flush_buffer(buffer: EdgeBuffer, client: httpx.Client, api_url: str) -> tuple[int, int]:
    rows = buffer.unsent()
    if not rows:
        return 0, 0

    readings = [json.loads(row["payload"]) for row in rows]
    try:
        response = client.post(f"{api_url.rstrip('/')}/api/telemetry/batch", json={"readings": readings})
    except Exception as exc:
        logger.warning("API unavailable, keeping %s readings buffered: %s", len(rows), exc)
        return 0, buffer.pending()

    if 200 <= response.status_code < 300:
        buffer.delete([int(row["id"]) for row in rows])
        return len(rows), buffer.pending()

    if 400 <= response.status_code < 500:
        logger.error("API rejected batch with %s: %s", response.status_code, response.text[:300])
        buffer.delete([int(row["id"]) for row in rows])
        return len(rows), buffer.pending()

    logger.warning("API returned %s, keeping readings buffered", response.status_code)
    return 0, buffer.pending()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CrateWatch edge telemetry simulator")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--duration", type=float, default=0.0, help="0 means run until stopped")
    parser.add_argument("--scenario", choices=SCENARIO_CHOICES, default="normal")
    parser.add_argument("--buffer", default="data/edge_buffer.db")
    parser.add_argument("--shipment-id", default="SHP-2026-11-07-01")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--crates", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    buffer = EdgeBuffer(args.buffer)
    rng = random.Random(args.seed)
    selected = [item.strip() for item in args.crates.split(",") if item.strip()]
    profiles = [item for item in CRATE_PROFILES if not selected or item["id"] in selected]
    if not profiles:
        logger.error("no crates selected")
        return 2

    states = [
        CrateState(
            crate_id=item["id"],
            temp=item["temp"],
            humidity=item["humidity"],
            battery=item["battery"],
            rng=random.Random(rng.randint(1, 1_000_000)),
        )
        for item in profiles
    ]

    stop = False

    def handle_signal(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    started = time.monotonic()
    tick = 0
    logger.info(
        "edge agent started, crates=%s scenario=%s interval=%ss api=%s",
        len(states),
        args.scenario,
        args.interval,
        args.api_url,
    )

    with httpx.Client(timeout=5.0) as client:
        while not stop:
            tick += 1
            for state in states:
                reading = state.next_reading(tick, args.scenario)
                if reading is None:
                    continue
                payload = {
                    **reading,
                    "shipment_id": args.shipment_id,
                    "seq": buffer.next_seq(state.crate_id),
                    "event_ts": utc_iso(),
                }
                buffer.add(payload)

            sent, pending = flush_buffer(buffer, client, args.api_url)
            logger.info(
                "tick=%s sent=%s pending=%s scenario=%s", tick, sent, pending, args.scenario
            )

            if args.duration and (time.monotonic() - started) >= args.duration:
                break
            time.sleep(args.interval)

    pending = buffer.pending()
    logger.info("edge agent stopped, pending in local buffer=%s", pending)
    buffer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
