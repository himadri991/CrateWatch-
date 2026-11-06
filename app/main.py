import asyncio
import csv
import io
import json
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.templating import Jinja2Templates

from app import db, metrics, rules, sla
from app.config import Settings
from app.crates import CRATE_INDEX, CRATES, SHIPMENT
from app.models import DemoBreach, IncidentNote, TelemetryBatch, TelemetryIn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cratewatch")

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def reading_to_dict(reading: TelemetryIn) -> dict[str, Any]:
    return {
        "crate_id": reading.crate_id,
        "shipment_id": reading.shipment_id,
        "seq": reading.seq,
        "event_ts": db.to_iso(reading.event_ts),
        "temp_c": reading.temp_c,
        "humidity_pct": reading.humidity_pct,
        "shock_g": reading.shock_g,
        "door_open": reading.door_open,
        "battery_pct": reading.battery_pct,
    }


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Any]:
    cfg = request.app.state.settings
    with db.db_session(cfg.db_path) as conn:
        yield conn


def require_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> Settings:
    cfg = request.app.state.settings
    if not cfg.demo_mode:
        raise HTTPException(status_code=404, detail="demo endpoints are disabled")
    if cfg.admin_token and x_admin_token != cfg.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")
    return cfg


def require_operator(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> Settings:
    cfg = request.app.state.settings
    if cfg.admin_token and x_admin_token != cfg.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")
    return cfg


def incident_row_to_dict(row) -> dict[str, Any]:
    item = {key: row[key] for key in row.keys()}
    crate = CRATE_INDEX.get(item["crate_id"], {})
    item["artwork"] = crate.get("artwork")
    item["detection_latency_seconds"] = None
    item["ack_latency_seconds"] = None
    item["recovery_seconds"] = None
    item["ttr_seconds"] = None

    if item.get("event_ts"):
        item["detection_latency_seconds"] = round(
            max(0.0, (db.parse_iso(item["detected_at"]) - db.parse_iso(item["event_ts"])).total_seconds()),
            3,
        )
    if item.get("ack_at"):
        item["ack_latency_seconds"] = round(
            (db.parse_iso(item["ack_at"]) - db.parse_iso(item["detected_at"])).total_seconds(),
            3,
        )
    if item.get("ack_at") and item.get("resolved_at"):
        item["recovery_seconds"] = round(
            (db.parse_iso(item["resolved_at"]) - db.parse_iso(item["ack_at"])).total_seconds(),
            3,
        )
    if item.get("resolved_at"):
        item["ttr_seconds"] = round(
            (db.parse_iso(item["resolved_at"]) - db.parse_iso(item["detected_at"])).total_seconds(),
            3,
        )
    return item


def ingest_one(conn, reading: TelemetryIn, cfg: Settings) -> dict[str, Any]:
    payload = reading_to_dict(reading)
    received_ts = db.now_iso()
    inserted = db.insert_telemetry(conn, payload, received_ts)
    if not inserted:
        metrics.TELEMETRY_DUPLICATES.labels(reading.crate_id).inc()
        return {"accepted": False, "duplicate": True, "incident_ids": []}

    metrics.TELEMETRY_RECEIVED.labels(reading.crate_id).inc()
    incident_ids = rules.evaluate_reading(conn, payload, cfg)
    return {"accepted": True, "duplicate": False, "incident_ids": incident_ids}


def run_gap_check(cfg: Settings) -> list[int]:
    with db.db_session(cfg.db_path) as conn:
        return rules.check_telemetry_gaps(conn, [item["id"] for item in CRATES], cfg)


async def rules_loop(app: FastAPI) -> None:
    cfg = app.state.settings
    while True:
        await asyncio.sleep(cfg.rules_interval_seconds)
        try:
            await asyncio.to_thread(run_gap_check, cfg)
        except Exception:
            logger.exception("telemetry gap check failed")


def telemetry_csv(conn, limit: int = 5000) -> str:
    rows = conn.execute(
        """
        SELECT crate_id, shipment_id, seq, event_ts, received_ts,
               temp_c, humidity_pct, shock_g, door_open, battery_pct
        FROM telemetry ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "crate_id",
            "shipment_id",
            "seq",
            "event_ts",
            "received_ts",
            "temp_c",
            "humidity_pct",
            "shock_g",
            "door_open",
            "battery_pct",
        ]
    )
    for row in rows:
        writer.writerow([row[key] for key in row.keys()])
    return output.getvalue()


def incidents_csv(conn) -> str:
    rows = conn.execute("SELECT * FROM incidents ORDER BY id DESC").fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "crate_id",
            "rule_id",
            "severity",
            "title",
            "status",
            "event_ts",
            "detected_at",
            "ack_at",
            "recovered_at",
            "resolved_at",
            "breach_value",
            "threshold",
            "notes",
        ]
    )
    for row in rows:
        writer.writerow([row[key] for key in row.keys()])
    return output.getvalue()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = app.state.settings
    cfg.ensure_dirs()
    db.init_db(cfg.db_path)
    logger.info("database ready at %s", cfg.db_path)
    task = None
    if cfg.background_rules:
        task = asyncio.create_task(rules_loop(app))
    yield
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app(cfg: Settings | None = None) -> FastAPI:
    cfg = cfg or Settings()
    app = FastAPI(title="CrateWatch", version="1.0.0", lifespan=lifespan)
    app.state.settings = cfg
    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    @app.middleware("http")
    async def request_timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000.0
        metrics.observe_api_latency(duration_ms)
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        metrics.HTTP_LATENCY.labels(request.method, route_path, str(response.status_code)).observe(
            duration_ms / 1000.0
        )
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        return response

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "settings": cfg,
                "shipment": SHIPMENT,
                "crates": CRATES,
                "demo_mode": cfg.demo_mode,
                "admin_token": cfg.admin_token if cfg.demo_mode else "",
            },
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "cratewatch", "time": db.now_iso()}

    @app.get("/readyz")
    def readyz(conn=Depends(get_db)):
        conn.execute("SELECT 1").fetchone()
        return {"status": "ready", "time": db.now_iso()}

    @app.post("/api/telemetry")
    def ingest(reading: TelemetryIn, conn=Depends(get_db), cfg: Settings = Depends(get_settings)):
        return ingest_one(conn, reading, cfg)

    @app.post("/api/telemetry/batch")
    def ingest_batch(batch: TelemetryBatch, conn=Depends(get_db), cfg: Settings = Depends(get_settings)):
        accepted = 0
        duplicates = 0
        incident_ids: list[int] = []
        for reading in batch.readings:
            result = ingest_one(conn, reading, cfg)
            if result["accepted"]:
                accepted += 1
            else:
                duplicates += 1
            incident_ids.extend(result["incident_ids"])
        return {
            "accepted": accepted,
            "duplicates": duplicates,
            "incident_ids": sorted(set(incident_ids)),
        }

    @app.get("/api/fleet")
    def fleet(conn=Depends(get_db), cfg: Settings = Depends(get_settings)):
        return {
            "generated_at": db.now_iso(),
            "shipment": SHIPMENT,
            "crates": sla.fleet_snapshot(conn, cfg),
        }

    @app.get("/api/crates/{crate_id}/history")
    def history(
        crate_id: str,
        minutes: int = Query(default=15, ge=1, le=240),
        limit: int = Query(default=180, ge=10, le=2000),
        conn=Depends(get_db),
    ):
        if crate_id not in CRATE_INDEX:
            raise HTTPException(status_code=404, detail="unknown crate")
        return {
            "crate_id": crate_id,
            "readings": sla.crate_history(conn, crate_id, minutes, limit),
        }

    @app.get("/api/incidents")
    def incidents(
        status: str = Query(default="active", pattern="^(active|open|resolved|all)$"),
        limit: int = Query(default=100, ge=1, le=500),
        conn=Depends(get_db),
    ):
        if status == "active":
            where = "WHERE status IN ('OPEN', 'ACK')"
            params: list[Any] = []
        elif status == "open":
            where = "WHERE status = 'OPEN'"
            params = []
        elif status == "resolved":
            where = "WHERE status = 'RESOLVED'"
            params = []
        else:
            where = ""
            params = []

        rows = conn.execute(
            f"""
            SELECT * FROM incidents
            {where}
            ORDER BY detected_at DESC, id DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
        return {
            "generated_at": db.now_iso(),
            "incidents": [incident_row_to_dict(row) for row in rows],
        }

    @app.post("/api/incidents/{incident_id}/ack")
    def acknowledge(incident_id: int, payload: IncidentNote | None = None, conn=Depends(get_db)):
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if row["status"] == "RESOLVED":
            raise HTTPException(status_code=409, detail="incident is already resolved")

        if row["status"] == "OPEN":
            moment = db.now_iso()
            with db.WRITE_LOCK:
                conn.execute(
                    "UPDATE incidents SET status = 'ACK', ack_at = ? WHERE id = ? AND status = 'OPEN'",
                    (moment, incident_id),
                )
                conn.commit()
            db.log_event(
                conn,
                "incident_acknowledged",
                "incident acknowledged by operator",
                crate_id=row["crate_id"],
                incident_id=incident_id,
            )

        updated = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return incident_row_to_dict(updated)

    @app.post("/api/incidents/{incident_id}/resolve")
    def resolve(incident_id: int, payload: IncidentNote | None = None, conn=Depends(get_db)):
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if row["status"] == "RESOLVED":
            return incident_row_to_dict(row)

        moment = db.now_iso()
        notes = payload.notes if payload and payload.notes else row["notes"]
        with db.WRITE_LOCK:
            conn.execute(
                """
                UPDATE incidents
                SET status = 'RESOLVED',
                    ack_at = COALESCE(ack_at, ?),
                    recovered_at = ?,
                    resolved_at = ?,
                    notes = ?,
                    last_seen_at = ?
                WHERE id = ?
                """,
                (moment, moment, moment, notes, moment, incident_id),
            )
            conn.commit()

        ttr_seconds = (
            db.parse_iso(moment) - db.parse_iso(row["detected_at"])
        ).total_seconds()
        metrics.INCIDENT_TTR.labels(row["severity"]).observe(max(0.0, ttr_seconds))
        db.log_event(
            conn,
            "incident_resolved",
            "incident marked resolved after verification",
            crate_id=row["crate_id"],
            incident_id=incident_id,
            payload={"ttr_seconds": round(ttr_seconds, 3), "notes": notes},
        )
        updated = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return incident_row_to_dict(updated)

    @app.get("/api/sla")
    def sla_summary(conn=Depends(get_db), cfg: Settings = Depends(get_settings)):
        return sla.compute_sla(conn, cfg)

    @app.get("/api/events")
    def events(limit: int = Query(default=80, ge=1, le=500), conn=Depends(get_db)):
        rows = conn.execute(
            "SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"events": [{key: row[key] for key in row.keys()} for row in rows]}

    @app.get("/metrics")
    def prometheus_metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/export/telemetry.csv")
    def export_telemetry(limit: int = Query(default=5000, ge=1, le=100000), conn=Depends(get_db)):
        return Response(
            telemetry_csv(conn, limit),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cratewatch_telemetry.csv"},
        )

    @app.get("/api/export/incidents.csv")
    def export_incidents(conn=Depends(get_db)):
        return Response(
            incidents_csv(conn),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cratewatch_incidents.csv"},
        )

    @app.post("/api/evidence/export")
    def export_evidence(cfg: Settings = Depends(require_operator), conn=Depends(get_db)):
        if not cfg.evidence_bucket:
            raise HTTPException(status_code=503, detail="evidence bucket is not configured")
        try:
            import boto3
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="boto3 is not installed") from exc

        stamp = db.now_iso().replace(":", "-")
        objects = {
            f"exports/telemetry-{stamp}.csv": telemetry_csv(conn, 100000),
            f"exports/incidents-{stamp}.csv": incidents_csv(conn),
        }
        client = boto3.client("s3", region_name=os.getenv("AWS_REGION", "ap-south-1"))
        uploaded = []
        try:
            for key, content in objects.items():
                client.put_object(
                    Bucket=cfg.evidence_bucket,
                    Key=key,
                    Body=content.encode("utf-8"),
                    ContentType="text/csv",
                    ServerSideEncryption="AES256",
                )
                uploaded.append(key)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"S3 export failed: {exc}") from exc

        return {
            "bucket": cfg.evidence_bucket,
            "keys": uploaded,
            "exported_at": db.now_iso(),
        }

    @app.post("/api/demo/breach")
    def demo_breach(
        payload: DemoBreach,
        conn=Depends(get_db),
        cfg: Settings = Depends(require_admin),
    ):
        latest = db.latest_telemetry(conn, payload.crate_id)
        base = {
            "crate_id": payload.crate_id,
            "shipment_id": cfg.shipment_id,
            "seq": 900_000_000 + int(time.time() * 1000) % 100_000_000,
            "event_ts": db.now_iso(),
            "temp_c": latest["temp_c"] if latest else 21.0,
            "humidity_pct": latest["humidity_pct"] if latest else 50.0,
            "shock_g": latest["shock_g"] if latest else 0.4,
            "door_open": bool(latest["door_open"]) if latest else False,
            "battery_pct": latest["battery_pct"] if latest else 90.0,
        }
        if payload.kind == "shock":
            base["shock_g"] = 12.4
        elif payload.kind == "heat":
            base["temp_c"] = 27.8
        elif payload.kind == "humidity":
            base["humidity_pct"] = 68.0
        elif payload.kind == "door":
            base["door_open"] = True
        elif payload.kind == "battery":
            base["battery_pct"] = 14.0

        received_ts = db.now_iso()
        inserted = db.insert_telemetry(conn, base, received_ts)
        if not inserted:
            return {"accepted": False, "duplicate": True, "incident_ids": []}
        metrics.TELEMETRY_RECEIVED.labels(payload.crate_id).inc()
        incident_ids = rules.evaluate_reading(conn, base, cfg)
        return {"accepted": True, "duplicate": False, "incident_ids": incident_ids}

    @app.post("/api/demo/reset")
    def demo_reset(cfg: Settings = Depends(require_admin), conn=Depends(get_db)):
        with db.WRITE_LOCK:
            conn.executescript(
                """
                DELETE FROM telemetry;
                DELETE FROM incidents;
                DELETE FROM events;
                DELETE FROM sqlite_sequence
                WHERE name IN ('telemetry', 'incidents', 'events');
                """
            )
            conn.commit()
        return {"status": "reset", "time": db.now_iso()}

    return app


app = create_app()
