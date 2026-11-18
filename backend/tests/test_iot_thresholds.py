"""
Unit tests for the IoT demo-threshold rules (pure functions, no database).

Thresholds under test (demonstration values, not certified BESCOM limits):
  Voltage      warning 200-210 V or 250-260 V   critical < 200 V or > 260 V
  Current      warning > 65 A                   critical > 80 A
  Temperature  warning > 65 C                   critical > 70 C
"""
import pytest

from services.iot_alerts import (
    CRITICAL, OVER_TEMPERATURE, OVERLOAD_CURRENT, OVERVOLTAGE, SAFE, UNDERVOLTAGE, WARNING,
    connection_state, evaluate_reading,
)


def _types(faults, severity):
    return {f.fault_type for f in faults if f.severity == severity}


def test_normal_reading_is_safe():
    status, faults = evaluate_reading(230, 40, 40)
    assert status == SAFE
    assert faults == []


@pytest.mark.parametrize("v, expected", [
    (199.9, CRITICAL), (180, CRITICAL), (200, WARNING), (205, WARNING), (210, WARNING),
    (210.1, SAFE), (230, SAFE), (249.9, SAFE),
    (250, WARNING), (255, WARNING), (260, WARNING), (260.1, CRITICAL), (280, CRITICAL),
])
def test_voltage_bands(v, expected):
    status, _ = evaluate_reading(v, 40, 40)
    assert status == expected


@pytest.mark.parametrize("a, expected", [
    (40, SAFE), (65, SAFE), (65.1, WARNING), (80, WARNING), (80.1, CRITICAL), (90, CRITICAL),
])
def test_current_bands(a, expected):
    status, _ = evaluate_reading(230, a, 40)
    assert status == expected


@pytest.mark.parametrize("t, expected", [
    (40, SAFE), (65, SAFE), (65.1, WARNING), (70, WARNING), (70.1, CRITICAL), (75, CRITICAL),
])
def test_temperature_bands(t, expected):
    status, _ = evaluate_reading(230, 40, t)
    assert status == expected


def test_fault_types_and_details():
    _, faults = evaluate_reading(180, 90, 75)
    assert _types(faults, CRITICAL) == {UNDERVOLTAGE, OVERLOAD_CURRENT, OVER_TEMPERATURE}
    by_type = {f.fault_type: f for f in faults}
    assert by_type[OVERLOAD_CURRENT].actual == 90 and by_type[OVERLOAD_CURRENT].threshold == 80
    assert by_type[OVER_TEMPERATURE].unit == "C"
    assert by_type[UNDERVOLTAGE].recommended_action  # never empty


def test_overvoltage_is_critical_above_260():
    status, faults = evaluate_reading(275, 40, 40)
    assert status == CRITICAL
    assert _types(faults, CRITICAL) == {OVERVOLTAGE}


def test_worst_severity_wins():
    status, faults = evaluate_reading(230, 70, 80)  # current warning + temperature critical
    assert status == CRITICAL
    assert _types(faults, WARNING) == {OVERLOAD_CURRENT}
    assert _types(faults, CRITICAL) == {OVER_TEMPERATURE}


def test_connection_state():
    assert connection_state(0) == "ONLINE"
    assert connection_state(10) == "ONLINE"
    assert connection_state(10.1) == "STALE"
    assert connection_state(60) == "STALE"
    assert connection_state(61) == "OFFLINE"
