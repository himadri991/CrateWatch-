import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil((pct / 100.0) * len(ordered)) - 1
    return ordered[min(max(rank, 0), len(ordered) - 1)]


def summarize(values):
    if not values:
        return None
    return {
        "avg": round(sum(values) / len(values), 3),
        "p50": round(percentile(values, 50), 3),
        "p95": round(percentile(values, 95), 3),
        "p99": round(percentile(values, 99), 3),
        "max": round(max(values), 3),
    }


def wait_for_health(url: str, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/healthz", timeout=1.0)
            if response.status_code == 200:
                return
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"server did not become healthy: {last_error}")


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


def build_batch(index: int, batch_size: int) -> list[dict]:
    rng = random.Random(index)
    crate_id = f"CW-{1 + (index % 6):02d}"
    batch = []
    for item in range(batch_size):
        batch.append(
            {
                "crate_id": crate_id,
                "shipment_id": "SHP-LOAD-01",
                "seq": index * batch_size + item + 1,
                "event_ts": iso_now(),
                "temp_c": round(20.5 + rng.uniform(-0.8, 0.8), 2),
                "humidity_pct": round(49.0 + rng.uniform(-3.0, 3.0), 2),
                "shock_g": round(rng.uniform(0.1, 0.8), 2),
                "door_open": False,
                "battery_pct": round(90.0 - (index % 20), 2),
            }
        )
    return batch


def run_request(client: httpx.Client, index: int, batch_size: int):
    if index % 11 == 0:
        endpoint = "fleet"
        started = time.perf_counter()
        response = client.get("/api/fleet")
    elif index % 13 == 0:
        endpoint = "sla"
        started = time.perf_counter()
        response = client.get("/api/sla")
    else:
        endpoint = "ingest"
        started = time.perf_counter()
        response = client.post("/api/telemetry/batch", json={"readings": build_batch(index, batch_size)})
    latency_ms = (time.perf_counter() - started) * 1000.0
    accepted = response.json().get("accepted", 0) if response.status_code == 200 else 0
    return endpoint, latency_ms, response.status_code, accepted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CrateWatch load and SLA test")
    parser.add_argument("--url", default="")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--requests", type=int, default=1200)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--output", default="docs/load_test_results.json")
    parser.add_argument("--keep-db", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    own_server = not bool(args.url)
    process = None
    db_path = PROJECT_ROOT / "data" / "loadtest.db"
    base_url = args.url.rstrip("/") if args.url else f"http://127.0.0.1:{args.port}"

    if own_server:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        process = start_server(args.port, db_path)

    latencies = defaultdict(list)
    status_codes = Counter()
    accepted_total = 0
    started_at = iso_now()
    wall_start = time.perf_counter()

    try:
        limits = httpx.Limits(max_connections=args.concurrency + 10, max_keepalive_connections=args.concurrency)
        with httpx.Client(base_url=base_url, timeout=30.0, limits=limits) as client:
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [
                    pool.submit(run_request, client, index, args.batch_size)
                    for index in range(args.requests)
                ]
                for future in as_completed(futures):
                    endpoint, latency_ms, status_code, accepted = future.result()
                    latencies["all"].append(latency_ms)
                    latencies[endpoint].append(latency_ms)
                    status_codes[str(status_code)] += 1
                    accepted_total += accepted

            sla_response = client.get("/api/sla")
            sla_snapshot = sla_response.json() if sla_response.status_code == 200 else None
    finally:
        wall_seconds = time.perf_counter() - wall_start
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if not args.keep_db:
                for suffix in ("", "-wal", "-shm"):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)

    errors = sum(count for code, count in status_codes.items() if not code.startswith("2"))
    result = {
        "generated_at": iso_now(),
        "started_at": started_at,
        "target": base_url,
        "configuration": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "batch_size": args.batch_size,
        },
        "duration_seconds": round(wall_seconds, 3),
        "throughput_requests_per_second": round(args.requests / wall_seconds, 2),
        "throughput_readings_per_second": round(accepted_total / wall_seconds, 2),
        "readings_accepted": accepted_total,
        "error_rate_pct": round((errors / args.requests) * 100.0, 3),
        "status_codes": dict(status_codes),
        "latency_ms": {
            "all": summarize(latencies["all"]),
            "ingest": summarize(latencies["ingest"]),
            "fleet": summarize(latencies["fleet"]),
            "sla": summarize(latencies["sla"]),
        },
        "sla_snapshot": sla_snapshot,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"requests={args.requests} concurrency={args.concurrency} batch={args.batch_size}")
    print(f"duration={wall_seconds:.2f}s throughput={result['throughput_requests_per_second']} req/s")
    print(f"readings accepted={accepted_total} error rate={result['error_rate_pct']} percent")
    for key in ("all", "ingest", "fleet", "sla"):
        stats = result["latency_ms"][key]
        if stats:
            print(
                f"{key:7s} avg={stats['avg']:.2f}ms p95={stats['p95']:.2f}ms p99={stats['p99']:.2f}ms"
            )
    print(f"evidence written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
