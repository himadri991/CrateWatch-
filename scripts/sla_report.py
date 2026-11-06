import argparse
import json
import platform
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value, digits=2, unit=""):
    if value is None:
        return "--"
    if isinstance(value, float):
        return f"{value:.{digits}f}{unit}"
    return f"{value}{unit}"


def run_pytest():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    lines = [line.strip() for line in (completed.stdout + completed.stderr).splitlines() if line.strip()]
    summary = lines[-1] if lines else "pytest produced no output"
    return completed.returncode, summary


def fetch_live_sla(url: str):
    if not url:
        return None
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/sla", timeout=3.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return None
    return None


def sla_table(snapshot):
    if not snapshot:
        return "No SLA snapshot was available.\n"
    observed = snapshot.get("observed", {})
    targets = snapshot.get("targets", {})
    checks = snapshot.get("checks", {})
    rows = [
        (
            "Telemetry availability",
            f">= {fmt(targets.get('availability_pct'), 1, ' percent')}",
            fmt(observed.get("availability_pct"), 2, " percent"),
            checks.get("availability", "NO_DATA"),
        ),
        (
            "Alert latency P95",
            f"<= {fmt(targets.get('alert_latency_p95_seconds'), 1, ' s')}",
            fmt(observed.get("alert_latency_p95_seconds"), 2, " s"),
            checks.get("alert_latency", "NO_DATA"),
        ),
        (
            "API latency P95",
            f"<= {fmt(targets.get('api_latency_p95_ms'), 1, ' ms')}",
            fmt(observed.get("api_latency_p95_ms"), 1, " ms"),
            checks.get("api_latency", "NO_DATA"),
        ),
        (
            "TTR P95, S1",
            f"<= {fmt(targets.get('ttr_s1_minutes'), 1, ' min')}",
            fmt((observed.get("ttr_s1_p95_seconds") or 0) / 60.0 if observed.get("ttr_s1_p95_seconds") is not None else None, 2, " min"),
            checks.get("ttr_s1", "NO_DATA"),
        ),
        (
            "Ingestion delay P95",
            f"<= {fmt(targets.get('ingestion_delay_p95_seconds'), 1, ' s')}",
            fmt(observed.get("ingestion_delay_p95_seconds"), 2, " s"),
            checks.get("ingestion_delay", "NO_DATA"),
        ),
    ]
    lines = [
        "| Metric | Target | Observed | Result |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    lines.append("")
    lines.append(f"Overall result: {snapshot.get('overall', 'NO_DATA')}.")
    return "\n".join(lines) + "\n"


def build_report(args):
    ttr = load_json(Path(args.ttr))
    load = load_json(Path(args.load))
    rto = load_json(Path(args.rto))
    gap = load_json(Path(args.gap))
    live_sla = fetch_live_sla(args.url)
    snapshot = live_sla or (ttr or {}).get("sla_snapshot") or (gap or {}).get("sla_snapshot")

    pytest_code, pytest_summary = run_pytest()
    sqlite_version = sqlite3.sqlite_version
    sections = []

    sections.append("# CrateWatch Test Evidence\n")
    sections.append(f"Generated at {iso_now()}.\n")
    sections.append("## Environment\n")
    sections.append(
        "\n".join(
            [
                f"- Host: macOS on Apple silicon, local development machine",
                f"- Python: {platform.python_version()}",
                f"- SQLite: {sqlite_version}",
                f"- Application: FastAPI, Uvicorn, SQLite WAL",
                f"- Runtime mode: local process, same container image definition used for Docker and ECS",
            ]
        )
        + "\n"
    )
    sections.append("## Functional test suite\n")
    sections.append(f"Command: `{sys.executable} -m pytest -q`\n")
    sections.append(f"Result: {pytest_summary}\n")
    sections.append(f"Exit code: {pytest_code}\n")

    sections.append("## TTR scenario\n")
    if ttr:
        timings = ttr["timings_seconds"]
        incident = ttr["incident"]
        sections.append(
            "\n".join(
                [
                    f"- Scenario: {ttr['scenario']}",
                    f"- Crate: {ttr['crate_id']}, breach: {ttr['breach_kind']}",
                    f"- Incident: {incident['id']}, {incident['severity']}, {incident['rule_id']}",
                    f"- Detection: {fmt(timings.get('detection'), 3, ' s')}",
                    f"- Diagnosis and acknowledgement: {fmt(timings.get('diagnosis'), 3, ' s')}",
                    f"- Recovery action: {fmt(timings.get('recovery'), 3, ' s')}",
                    f"- Verification: {fmt(timings.get('verification'), 3, ' s')}",
                    f"- Measured TTR: {fmt(timings.get('ttr'), 3, ' s')} ({fmt((timings.get('ttr') or 0) / 60.0, 3, ' min')})",
                    f"- Verification passed: {ttr['verification']['passed']}",
                ]
            )
            + "\n"
        )
    else:
        sections.append("Not run. Start the app and run `make ttr`.\n")

    sections.append("## Load and latency test\n")
    if load:
        latency = load["latency_ms"]["all"]
        ingest = load["latency_ms"]["ingest"]
        sections.append(
            "\n".join(
                [
                    f"- Requests: {load['configuration']['requests']}, concurrency: {load['configuration']['concurrency']}, batch size: {load['configuration']['batch_size']}",
                    f"- Readings accepted: {load['readings_accepted']}",
                    f"- Duration: {fmt(load['duration_seconds'], 2, ' s')}",
                    f"- Throughput: {fmt(load['throughput_requests_per_second'], 2, ' requests/s')}",
                    f"- Error rate: {fmt(load['error_rate_pct'], 3, ' percent')}",
                    f"- Client latency, all requests: average {fmt(latency['avg'], 2, ' ms')}, P95 {fmt(latency['p95'], 2, ' ms')}, P99 {fmt(latency['p99'], 2, ' ms')}",
                    f"- Client latency, ingestion: average {fmt(ingest['avg'], 2, ' ms')}, P95 {fmt(ingest['p95'], 2, ' ms')}, P99 {fmt(ingest['p99'], 2, ' ms')}",
                ]
            )
            + "\n"
        )
    else:
        sections.append("Not run. Run `make load`.\n")

    sections.append("## Process restart and RTO\n")
    if rto:
        timings = rto["timings_seconds"]
        sections.append(
            "\n".join(
                [
                    f"- Scenario: {rto['scenario']}",
                    f"- Detection after process termination: {fmt(timings.get('detection'), 3, ' s')}",
                    f"- Recovery to healthy state: {fmt(timings.get('recovery'), 3, ' s')}",
                    f"- RTO: {fmt(timings.get('rto'), 3, ' s')} ({fmt((timings.get('rto') or 0) / 60.0, 3, ' min')})",
                    f"- Total downtime: {fmt(timings.get('total_downtime'), 3, ' s')}",
                    f"- Marker reading survived restart: {rto['verification']['marker_reading_present_after_restart']}",
                    f"- Verification passed: {rto['verification']['passed']}",
                ]
            )
            + "\n"
        )
    else:
        sections.append("Not run. Run `make rto` if the script is available, or use the manual restart steps in the runbook.\n")

    sections.append("## Edge buffering and gap detection\n")
    if gap:
        timings = gap["timings_seconds"]
        buffer = gap["buffer"]
        sections.append(
            "\n".join(
                [
                    f"- Scenario: {gap['scenario']}",
                    f"- Gap detected after API restart: {fmt(timings.get('gap_detected_after_app_restart'), 3, ' s')}",
                    f"- Agent stayed down: {fmt(timings.get('agent_down'), 3, ' s')}",
                    f"- Readings buffered during outage: {buffer['readings_buffered_during_outage']}",
                    f"- Buffered readings found after restart: {buffer['buffered_readings_found_after_restart']}",
                    f"- Buffer pending after flush: {buffer['pending_after_flush']}",
                    f"- Data loss: {buffer['data_loss_readings']} readings",
                    f"- Gap incident TTR: {fmt(timings.get('ttr'), 3, ' s')}",
                    f"- Verification passed: {gap['verification']['passed']}",
                ]
            )
            + "\n"
        )
    else:
        sections.append("Not run. Run `make gap`.\n")

    sections.append("## SLA snapshot\n")
    sections.append(sla_table(snapshot))

    sections.append("## Runtime limits and pending evidence\n")
    sections.append(
        "\n".join(
            [
                "- Docker build was not executed on this machine because no Docker, Podman, or Colima runtime is installed. The Dockerfile and Compose file are included and ready for `docker compose -f docker/docker-compose.yml up --build`.",
                "- AWS deployment was not executed because no AWS account credentials were provided. Terraform assets for ECS Fargate, ALB, ECR, S3, EFS, CloudWatch, SNS, IAM, and VPC are included.",
                "- `make terraform-check` parses the Terraform HCL files with python-hcl2. The Terraform CLI, provider schema validation, and a live AWS apply were not run.",
                "- The measured numbers above come from the local application runtime. The same application code is packaged into the container image used by the AWS task definition.",
            ]
        )
        + "\n"
    )

    sections.append("## Reproduction commands\n")
    sections.append(
        "\n".join(
            [
                "```bash",
                "make install",
                "make test",
                "make run",
                "# in a second terminal",
                "make simulate-mixed",
                "# in a third terminal",
                "make ttr",
                "make load",
                "make gap",
                "make report",
                "make style",
                "make terraform-check",
                "```",
            ]
        )
        + "\n"
    )

    return "\n".join(sections)


def parse_args():
    parser = argparse.ArgumentParser(description="Build the CrateWatch test evidence report")
    parser.add_argument("--ttr", default="docs/ttr_results.json")
    parser.add_argument("--load", default="docs/load_test_results.json")
    parser.add_argument("--rto", default="docs/rto_results.json")
    parser.add_argument("--gap", default="docs/gap_results.json")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="docs/TEST_EVIDENCE.md")
    return parser.parse_args()


def main():
    args = parse_args()
    report = build_report(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"report written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
