from app.rules import rules_for_reading


def base_reading(**overrides):
    reading = {
        "crate_id": "CW-01",
        "temp_c": 21.0,
        "humidity_pct": 50.0,
        "shock_g": 0.4,
        "door_open": False,
        "battery_pct": 90.0,
    }
    reading.update(overrides)
    return reading


def rule_ids(reading):
    return {item["rule_id"] for item in rules_for_reading(reading)}


def test_normal_reading_has_no_rules():
    assert rules_for_reading(base_reading()) == []


def test_shock_rule_is_s1():
    matches = rules_for_reading(base_reading(shock_g=12.4))
    assert len(matches) == 1
    assert matches[0]["rule_id"] == "SHOCK_LIMIT"
    assert matches[0]["severity"] == "S1"


def test_temperature_rule_both_sides():
    assert "TEMP_RANGE" in rule_ids(base_reading(temp_c=14.9))
    assert "TEMP_RANGE" in rule_ids(base_reading(temp_c=25.1))
    assert "TEMP_RANGE" not in rule_ids(base_reading(temp_c=25.0))


def test_humidity_rule_both_sides():
    assert "HUMIDITY_RANGE" in rule_ids(base_reading(humidity_pct=39.9))
    assert "HUMIDITY_RANGE" in rule_ids(base_reading(humidity_pct=60.1))
    assert "HUMIDITY_RANGE" not in rule_ids(base_reading(humidity_pct=60.0))


def test_door_and_battery_rules():
    assert "DOOR_OPEN" in rule_ids(base_reading(door_open=True))
    assert "BATTERY_LOW" in rule_ids(base_reading(battery_pct=14.0))


def test_multiple_rules_can_fire_together():
    ids = rule_ids(base_reading(temp_c=27.8, humidity_pct=68.0, shock_g=12.4, door_open=True))
    assert ids == {"TEMP_RANGE", "HUMIDITY_RANGE", "SHOCK_LIMIT", "DOOR_OPEN"}
