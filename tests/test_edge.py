import random

import httpx

from edge.agent import CRATE_PROFILES, CrateState, EdgeBuffer, flush_buffer


def sample_payload():
    return {
        "crate_id": "CW-01",
        "shipment_id": "SHP-TEST-01",
        "seq": 1,
        "event_ts": "2026-11-07T10:00:00.000Z",
        "temp_c": 21.0,
        "humidity_pct": 50.0,
        "shock_g": 0.4,
        "door_open": False,
        "battery_pct": 90.0,
    }


def test_buffer_persists_and_sequences_increment(tmp_path):
    path = str(tmp_path / "edge.db")
    buffer = EdgeBuffer(path)
    assert buffer.next_seq("CW-01") == 1
    assert buffer.next_seq("CW-01") == 2
    buffer.add(sample_payload())
    assert buffer.pending() == 1
    buffer.close()

    reopened = EdgeBuffer(path)
    assert reopened.next_seq("CW-01") == 3
    assert reopened.pending() == 1
    reopened.close()


def test_flush_deletes_rows_on_success(tmp_path):
    buffer = EdgeBuffer(str(tmp_path / "edge.db"))
    buffer.add(sample_payload())

    def handler(request):
        assert request.url.path == "/api/telemetry/batch"
        return httpx.Response(200, json={"accepted": 1})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sent, pending = flush_buffer(buffer, client, "http://test")
    assert sent == 1
    assert pending == 0
    assert buffer.pending() == 0


def test_flush_keeps_rows_when_api_is_down(tmp_path):
    buffer = EdgeBuffer(str(tmp_path / "edge.db"))
    buffer.add(sample_payload())

    def handler(request):
        raise httpx.ConnectError("api down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sent, pending = flush_buffer(buffer, client, "http://test")
    assert sent == 0
    assert pending == 1
    assert buffer.pending() == 1


def test_shock_scenario_sets_threshold_breach():
    profile = next(item for item in CRATE_PROFILES if item["id"] == "CW-03")
    state = CrateState(
        crate_id=profile["id"],
        temp=profile["temp"],
        humidity=profile["humidity"],
        battery=profile["battery"],
        rng=random.Random(3),
    )
    reading = state.next_reading(6, "shock")
    assert reading is not None
    assert reading["shock_g"] == 12.4


def test_gap_scenario_skips_crate_five():
    profile = next(item for item in CRATE_PROFILES if item["id"] == "CW-05")
    state = CrateState(
        crate_id=profile["id"],
        temp=profile["temp"],
        humidity=profile["humidity"],
        battery=profile["battery"],
        rng=random.Random(5),
    )
    assert state.next_reading(6, "gap") is None
    assert state.next_reading(13, "gap") is not None
