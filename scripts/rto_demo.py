import argparse
import json
import os
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


def start_server(port: int, db_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["CRATEWATCH_DB"] = str(db_path)
    env["CRATEWATCH_BACKGROUND_RULES"] = "false"
    env["CRATEWATCH_DEMO_MODE"] = "false"
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


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def seed_readings(client: httpx.Client) -> None:
    now = iso_now()
    readings = []
    for index in range(1, 7):
        readings.append(
            {
                "crate_id": f"CW-{index:02d}",
                "shipment_id": "SHP-RTO-01",
                "seq": 990000 + index,
                "event_ts": now,
                "temp_c": 21.0 + index / 10.0,
                "humidity_pct": 49.0,
                "shock_g": 0.4,
                "door_open": False,
                "battery_pct": 88.0,
            }
        )
    response = client.post("/api/telemetry/batch", json={"readings": readings})
    response.raise_for_status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure CrateWatch RTO after a process crash")
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--output", default="docs/rto_results.json")
    parser.add_argument("--keep-db", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = PROJECT_ROOT / "data" / "rtotest.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    base_url = f"http://127.0.0.1:{args.port}"

    process = start_server(args.port, db_path)
    sla_before = None
    try:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            seed_readings(client)
            sla_before = client.get("/api/sla").json()

            failed_at = iso_now()
            failure_clock = time.monotonic()
            stop_process(process)

            detected_at = None
            for _ in range(50):
                try:
                    httpx.get(f"{base_url}/healthz", timeout=0.5).raise_for_status()
                except Exception:
                    detected_at = iso_now()
                    break
                time.sleep(0.1)
            if detected_at is None:
                raise RuntimeError("server did not go down after termination")

            time.sleep(2.0)
            process = start_server(args.port, db_path)
            healthy_at = iso_now()
            total_downtime = time.monotonic() - failure_clock

            health = client.get("/healthz")
            health.raise_for_status()
            fleet = client.get("/api/fleet").json()
            sla_after = client.get("/api/sla").json()
            marker = next((item for item in fleet["crates"] if item["id"] == "CW-06"), None)
            marker_ok = (
                marker is not None
                and marker["reading"] is not None
                and abs(marker["reading"]["temp_c"] - 21.6) < 0.001
            )

            def seconds_between(start: str, end: str) -> float:
                def parse(value: str) -> datetime:
                    text = value[:-1] + "+00:00" if value.endswith("Z") else value
                    return datetime.fromisoformat(text)

                return (parse(end) - parse(start)).total_seconds()

            result = {
                "generated_at": iso_now(),
                "scenario": "application process terminated and restarted",
                "failed_at": failed_at,
                "detected_at": detected_at,
                "healthy_at": healthy_at,
                "timings_seconds": {
                    "detection": round(seconds_between(failed_at, detected_at), 3),
                    "recovery": round(seconds_between(detected_at, healthy_at), 3),
                    "rto": round(seconds_between(detected_at, healthy_at), 3),
                    "total_downtime": round(total_downtime, 3),
                },
                "verification": {
                    "health_ok": health.status_code == 200,
                    "marker_reading_present_after_restart": marker_ok,
                    "crate_status": marker["status"] if marker else None,
                    "passed": bool(health.status_code == 200 and marker_ok),
                },
                "sla_before": sla_before,
                "sla_after": sla_after,
            }

            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result["timings_seconds"], indent=2))
            print(f"RTO evidence written to {output_path}")
            return 0
    finally:
        stop_process(process)
        if not args.keep_db:
            for suffix in ("", "-wal", "-shm"):
                Path(str(db_path) + suffix).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
