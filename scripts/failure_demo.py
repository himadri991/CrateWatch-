import argparse
import json
import os
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure CrateWatch TTR for one incident")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("CRATEWATCH_ADMIN_TOKEN", "local-demo-token"))
    parser.add_argument("--crate", default="CW-03")
    parser.add_argument("--kind", default="shock", choices=["shock", "heat", "humidity", "door", "battery"])
    parser.add_argument("--ack-delay", type=float, default=2.0)
    parser.add_argument("--resolve-delay", type=float, default=2.0)
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--output", default="docs/ttr_results.json")
    return parser.parse_args()


def find_incident(client: httpx.Client, incident_id: int) -> dict:
    response = client.get(f"/api/incidents?status=all&limit=200")
    response.raise_for_status()
    for item in response.json()["incidents"]:
        if item["id"] == incident_id:
            return item
    raise RuntimeError(f"incident {incident_id} was not found")


def main() -> int:
    args = parse_args()
    base_url = args.url.rstrip("/")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        health = client.get("/healthz")
        health.raise_for_status()

        if not args.no_reset:
            reset = client.post(
                "/api/demo/reset",
                headers={"X-Admin-Token": args.token},
                json={},
            )
            reset.raise_for_status()
            time.sleep(1.0)

        started_at = iso_now()
        breach = client.post(
            "/api/demo/breach",
            headers={"X-Admin-Token": args.token},
            json={"crate_id": args.crate, "kind": args.kind},
        )
        breach.raise_for_status()
        body = breach.json()
        if not body.get("incident_ids"):
            raise RuntimeError("breach did not open an incident")
        incident_id = int(body["incident_ids"][0])
        detected = find_incident(client, incident_id)
        detected_at = detected["detected_at"]
        event_ts = detected.get("event_ts") or started_at

        time.sleep(args.ack_delay)
        ack = client.post(
            f"/api/incidents/{incident_id}/ack",
            json={"notes": "operator acknowledged the alert"},
        )
        ack.raise_for_status()
        acknowledged = ack.json()

        time.sleep(args.resolve_delay)
        resolved = client.post(
            f"/api/incidents/{incident_id}/resolve",
            json={"notes": "crate inspected, packing secured, condition stable"},
        )
        resolved.raise_for_status()
        resolved_body = resolved.json()

        verification_started = iso_now()
        verify_health = client.get("/healthz")
        verify_health.raise_for_status()
        verify_fleet = client.get("/api/fleet")
        verify_fleet.raise_for_status()
        verify_sla = client.get("/api/sla")
        verify_sla.raise_for_status()
        verification_at = iso_now()

        sla_snapshot = verify_sla.json()
        fleet = verify_fleet.json()
        crate = next((item for item in fleet["crates"] if item["id"] == args.crate), None)
        verification_ok = (
            verify_health.status_code == 200
            and resolved_body["status"] == "RESOLVED"
            and crate is not None
        )

        def seconds_between(start: str, end: str) -> float:
            def parse(value: str) -> datetime:
                text = value[:-1] + "+00:00" if value.endswith("Z") else value
                return datetime.fromisoformat(text)

            return (parse(end) - parse(start)).total_seconds()

        result = {
            "generated_at": iso_now(),
            "scenario": "condition breach and operator recovery",
            "api_url": base_url,
            "crate_id": args.crate,
            "breach_kind": args.kind,
            "incident": {
                "id": incident_id,
                "rule_id": detected["rule_id"],
                "severity": detected["severity"],
                "title": detected["title"],
                "status": resolved_body["status"],
                "event_ts": event_ts,
                "detected_at": detected_at,
                "ack_at": acknowledged["ack_at"],
                "resolved_at": resolved_body["resolved_at"],
                "threshold": detected.get("threshold"),
                "breach_value": detected.get("breach_value"),
            },
            "timings_seconds": {
                "detection": round(max(0.0, seconds_between(event_ts, detected_at)), 3),
                "diagnosis": round(seconds_between(detected_at, acknowledged["ack_at"]), 3),
                "recovery": round(seconds_between(acknowledged["ack_at"], resolved_body["resolved_at"]), 3),
                "verification": round(seconds_between(resolved_body["resolved_at"], verification_at), 3),
                "ttr": round(seconds_between(detected_at, resolved_body["resolved_at"]), 3),
                "event_to_verification": round(seconds_between(event_ts, verification_at), 3),
            },
            "verification": {
                "started_at": verification_started,
                "finished_at": verification_at,
                "health_ok": verify_health.status_code == 200,
                "incident_resolved": resolved_body["status"] == "RESOLVED",
                "crate_status": crate["status"] if crate else None,
                "passed": bool(verification_ok),
            },
            "sla_snapshot": sla_snapshot,
        }

        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        Path("docs/sla_snapshot.json").write_text(json.dumps(sla_snapshot, indent=2), encoding="utf-8")

        print(json.dumps(result["timings_seconds"], indent=2))
        print(f"incident {incident_id} resolved, evidence written to {output_path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
