"""Unit tests for the IoT inspection mapping and recommendation rules (no database, no models)."""
from types import SimpleNamespace as NS

from services.iot_alerts import evaluate_reading
from services.iot_inspection import SQRT3, build_model_readings, build_recommendations

LOAD_DRIVER = {"feature": "load_percentage", "label": "Load (% of rating)", "impact": 0.9, "value": 100}


def test_voltage_is_converted_from_phase_to_line_and_load_from_rating():
    rows = [NS(voltage_v=230.0, current_a=34.8, temperature_c=50.0)]
    r = build_model_readings(rows, rated_kva=25.0)[0]
    assert abs(r.voltage_lv - 230.0 * SQRT3) < 1e-6      # ~398 V, near the models' 415 V scale
    assert 99 < r.load_percentage < 101                  # 34.8 A is ~100% of a 25 kVA transformer
    assert r.temperature_c == 50.0 and r.current_a == 34.8


def test_healthy_without_alarms_gets_no_action_needed():
    recs = build_recommendations("HEALTHY", 85.0, [LOAD_DRIVER], [], 3000)
    assert [r["priority"] for r in recs] == ["ROUTINE"]
    assert "No action needed" in recs[0]["action"]


def test_protection_fault_is_urgent_even_when_models_say_healthy():
    _, faults = evaluate_reading(230, 90, 40)
    recs = build_recommendations("HEALTHY", 85.0, [LOAD_DRIVER], faults, 3000)
    assert recs[0]["priority"] == "URGENT"
    assert any("photo" in r["action"].lower() for r in recs)


def test_critical_model_verdict_asks_for_ticket_and_orders_by_priority():
    recs = build_recommendations("CRITICAL", 20.0, [LOAD_DRIVER], [], 12)
    priorities = [r["priority"] for r in recs]
    assert priorities == sorted(priorities, key=["URGENT", "SOON", "ROUTINE"].index)
    assert any("ticket" in r["action"].lower() for r in recs)
    assert any("replacement" in r["action"].lower() for r in recs)  # life < 365 days
    assert len({r["action"] for r in recs}) == len(recs)            # no duplicates
