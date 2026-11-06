from tests.helpers import make_reading


def test_health_and_readiness(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_dashboard_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "CrateWatch" in response.text
    assert "Shipment fleet" in response.text


def test_ingest_telemetry_and_duplicate_handling(client):
    payload = make_reading(seq=1)
    first = client.post("/api/telemetry", json=payload)
    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert first.json()["duplicate"] is False

    second = client.post("/api/telemetry", json=payload)
    assert second.status_code == 200
    assert second.json()["accepted"] is False
    assert second.json()["duplicate"] is True


def test_invalid_crate_is_rejected(client):
    response = client.post("/api/telemetry", json=make_reading(crate_id="BAD-01"))
    assert response.status_code == 422


def test_batch_ingestion(client):
    readings = [make_reading(crate_id="CW-01", seq=10), make_reading(crate_id="CW-02", seq=11)]
    response = client.post("/api/telemetry/batch", json={"readings": readings})
    assert response.status_code == 200
    assert response.json()["accepted"] == 2


def test_fleet_reports_latest_reading(client):
    client.post("/api/telemetry", json=make_reading(crate_id="CW-01", seq=1, temp_c=22.4))
    response = client.get("/api/fleet")
    assert response.status_code == 200
    crates = {item["id"]: item for item in response.json()["crates"]}
    assert crates["CW-01"]["reading"]["temp_c"] == 22.4
    assert crates["CW-01"]["status"] == "OK"
    assert crates["CW-02"]["status"] == "OFFLINE"


def test_incident_lifecycle_and_sla(client):
    client.post("/api/telemetry", json=make_reading(seq=1))
    client.post("/api/telemetry", json=make_reading(seq=2, shock_g=12.4))

    active = client.get("/api/incidents?status=active").json()["incidents"]
    assert len(active) == 1
    incident = active[0]
    assert incident["severity"] == "S1"
    assert incident["rule_id"] == "SHOCK_LIMIT"
    assert incident["status"] == "OPEN"

    ack = client.post(f"/api/incidents/{incident['id']}/ack", json={"notes": "operator checked"})
    assert ack.status_code == 200
    assert ack.json()["status"] == "ACK"
    assert ack.json()["ack_at"] is not None

    resolved = client.post(f"/api/incidents/{incident['id']}/resolve", json={"notes": "crate secured"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["resolved_at"] is not None
    assert resolved.json()["ttr_seconds"] >= 0

    sla = client.get("/api/sla").json()
    assert sla["observed"]["ttr_s1_p95_seconds"] is not None
    assert sla["observed"]["open_incidents"] == 0
    assert sla["observed"]["resolved_incidents"] == 1


def test_demo_breach_requires_admin_token(client):
    denied = client.post("/api/demo/breach", json={"crate_id": "CW-03", "kind": "shock"})
    assert denied.status_code == 401

    allowed = client.post(
        "/api/demo/breach",
        json={"crate_id": "CW-03", "kind": "shock"},
        headers={"X-Admin-Token": "test-token"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["accepted"] is True
    assert len(allowed.json()["incident_ids"]) == 1


def test_demo_reset_requires_admin_token(client):
    denied = client.post("/api/demo/reset")
    assert denied.status_code == 401

    client.post("/api/telemetry", json=make_reading(seq=1))
    allowed = client.post("/api/demo/reset", headers={"X-Admin-Token": "test-token"})
    assert allowed.status_code == 200

    fleet = client.get("/api/fleet").json()
    assert all(item["reading"] is None for item in fleet["crates"])
    assert client.get("/api/incidents?status=all").json()["incidents"] == []


def test_csv_exports(client):
    client.post("/api/telemetry", json=make_reading(seq=1))
    telemetry = client.get("/api/export/telemetry.csv")
    assert telemetry.status_code == 200
    assert "crate_id" in telemetry.text
    assert "CW-01" in telemetry.text

    incidents = client.get("/api/export/incidents.csv")
    assert incidents.status_code == 200
    assert "severity" in incidents.text


def test_evidence_export_requires_operator_token_and_bucket(client):
    denied = client.post("/api/evidence/export")
    assert denied.status_code == 401

    allowed = client.post(
        "/api/evidence/export",
        headers={"X-Admin-Token": "test-token"},
    )
    assert allowed.status_code == 503
