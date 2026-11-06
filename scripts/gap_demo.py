import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def wait_for_health(url: str, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/healthz", timeout=1.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("server did not become healthy")


def start_app(port: int, db_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["CRATEWATCH_DB"] = str(db_path)
    env["CRATEWATCH_BACKGROUND_RULES"] = "true"
    env["CRATEWATCH_DEMO_MODE"] = "false"
    env["CRATEWATCH_GAP_THRESHOLD"] = "4"
    env["CRATEWATCH_RULES_INTERVAL"] = "1"
    env["CRATEWATCH_TELEMETRY_INTERVAL"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_for_health(f"http://127.0.0.1:{port}")
    return process


def start_agent(port: int, buffer_path: Path, duration: float) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "edge.agent",
            "--api-url",
            f"http://127.0.0.1:{port}",
            "--buffer",
            str(buffer_path),
            "--scenario",
            "normal",
            "--interval",
            "1",
            "--duration",
            str(duration),
            "--shipment-id",
            "SHP-GAP-01",
        ],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def wait_for_fleet(client: httpx.Client, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/fleet")
        if response.status_code == 200:
            crates = response.json()["crates"]
            if all(item["reading"] is not None for item in crates):
                return
        time.sleep(0.25)
    raise RuntimeError("fleet did not report all crates in time")


def buffered_keys(buffer_path: Path) -> list[tuple[str, int]]:
    conn = sqlite3.connect(buffer_path, timeout=10.0)
    try:
        rows = conn.execute("SELECT payload FROM buffer WHERE sent = 0 ORDER BY id").fetchall()
    finally:
        conn.close()
    keys = []
    for (payload,) in rows:
        item = json.loads(payload)
        keys.append((item["crate_id"], int(item["seq"])))
    return keys


def pending_count(buffer_path: Path) -> int:
    conn = sqlite3.connect(buffer_path, timeout=10.0)
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM buffer WHERE sent = 0").fetchone()[0])
    finally:
        conn.close()


def app_row_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM telemetry").fetchone()[0])
    finally:
        conn.close()


def keys_present(db_path: Path, keys: list[tuple[str, int]]) -> int:
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        found = 0
        for crate_id, seq in keys:
            row = conn.execute(
                "SELECT 1 FROM telemetry WHERE crate_id = ? AND seq = ? LIMIT 1",
                (crate_id, seq),
            ).fetchone()
            if row:
                found += 1
        return found
    finally:
        conn.close()


def find_gap_incident(client: httpx.Client, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/incidents?status=active&limit=100")
        if response.status_code == 200:
            for item in response.json()["incidents"]:
                if item["rule_id"] == "TELEMETRY_GAP":
                    return item
        time.sleep(0.5)
    raise RuntimeError("gap incident was not detected after API restart")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demonstrate edge buffering and gap detection")
    parser.add_argument("--port", type=int, default=8013)
    parser.add_argument("--output", default="docs/gap_results.json")
    parser.add_argument("--keep-db", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app_db = PROJECT_ROOT / "data" / "gap_app.db"
    edge_db = PROJECT_ROOT / "data" / "gap_edge.db"
    for path in (app_db, edge_db):
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)

    app_process = start_app(args.port, app_db)
    agent_process = None
    base_url = f"http://127.0.0.1:{args.port}"

    try:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            agent_process = start_agent(args.port, edge_db, duration=120)
            wait_for_fleet(client)
            rows_before = app_row_count(app_db)

            app_stopped_at = iso_now()
            stop_process(app_process)

            buffer_deadline = time.monotonic() + 12.0
            buffered: list[tuple[str, int]] = []
            while time.monotonic() < buffer_deadline:
                buffered = buffered_keys(edge_db)
                if len(buffered) >= 6:
                    break
                time.sleep(0.5)
            if not buffered:
                raise RuntimeError("edge agent did not buffer readings while the API was down")

            stop_process(agent_process)
            agent_stopped_at = iso_now()

            app_process = start_app(args.port, app_db)
            app_healthy_at = iso_now()

            gap_incident = find_gap_incident(client)
            detected_at = gap_incident["detected_at"]

            agent_process = start_agent(args.port, edge_db, duration=30)
            agent_started_at = iso_now()

            flush_deadline = time.monotonic() + 20.0
            pending = pending_count(edge_db)
            while time.monotonic() < flush_deadline:
                pending = pending_count(edge_db)
                if pending == 0:
                    break
                time.sleep(0.5)

            found = keys_present(app_db, buffered)
            rows_after = app_row_count(app_db)

            ack = client.post(
                f"/api/incidents/{gap_incident['id']}/ack",
                json={"notes": "edge link restored, checking buffered readings"},
            )
            ack.raise_for_status()
            resolve = client.post(
                f"/api/incidents/{gap_incident['id']}/resolve",
                json={"notes": "gateway reconnected, buffered readings flushed, link stable"},
            )
            resolve.raise_for_status()
            resolved = resolve.json()
            sla = client.get("/api/sla").json()

            result = {
                "generated_at": iso_now(),
                "scenario": "API outage with edge store-and-forward, then gap detection after recovery",
                "app_stopped_at": app_stopped_at,
                "agent_stopped_at": agent_stopped_at,
                "app_healthy_at": app_healthy_at,
                "agent_started_at": agent_started_at,
                "detected_at": detected_at,
                "timings_seconds": {
                    "app_down": round(
                        (parse_time(app_healthy_at) - parse_time(app_stopped_at)).total_seconds(), 3
                    ),
                    "agent_down": round(
                        (parse_time(agent_started_at) - parse_time(agent_stopped_at)).total_seconds(), 3
                    ),
                    "gap_detected_after_app_restart": round(
                        (parse_time(detected_at) - parse_time(app_healthy_at)).total_seconds(), 3
                    ),
                    "ttr": resolved["ttr_seconds"],
                },
                "buffer": {
                    "readings_buffered_during_outage": len(buffered),
                    "buffered_readings_found_after_restart": found,
                    "pending_after_flush": pending,
                    "data_loss_readings": max(0, len(buffered) - found),
                },
                "telemetry": {
                    "rows_before_outage": rows_before,
                    "rows_after_resume": rows_after,
                    "rows_added": rows_after - rows_before,
                },
                "incident": {
                    "id": gap_incident["id"],
                    "severity": gap_incident["severity"],
                    "rule_id": gap_incident["rule_id"],
                    "detected_at": detected_at,
                    "resolved_at": resolved["resolved_at"],
                    "ttr_seconds": resolved["ttr_seconds"],
                },
                "sla_snapshot": sla,
                "verification": {
                    "gap_detected": True,
                    "buffer_flushed": pending == 0,
                    "no_buffered_data_lost": found == len(buffered),
                    "passed": bool(pending == 0 and found == len(buffered)),
                },
            }

            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result["timings_seconds"], indent=2))
            print(json.dumps(result["buffer"], indent=2))
            print(f"gap evidence written to {output_path}")
            return 0
    finally:
        if agent_process is not None:
            stop_process(agent_process)
        stop_process(app_process)
        if not args.keep_db:
            for path in (app_db, edge_db):
                for suffix in ("", "-wal", "-shm"):
                    Path(str(path) + suffix).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
