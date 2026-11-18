"""
IoT threshold rules and emergency-alert lifecycle
===================================================
Two parts, kept apart on purpose:

  evaluate_reading()  — PURE function: readings in, status + faults out.
                        No database, easy to unit test.
  sync_alerts()       — applies the faults to the iot_alerts table:
                        opens new alerts, leaves ongoing ones alone,
                        resolves alerts whose fault has cleared.

These are DEMONSTRATION thresholds for the hackathon simulation. They are not
certified BESCOM protection limits, and they are independent of the ML health
prediction pipeline (nothing here reads or writes the ML score).

Thresholds
----------
  Voltage      warning 200-210 V or 250-260 V     critical < 200 V or > 260 V
  Current      warning > 65 A                     critical > 80 A
  Temperature  warning > 65 C                     critical > 70 C
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.iot import IoTAlert

SAFE, WARNING, CRITICAL = "SAFE", "WARNING", "CRITICAL"

# fault types
UNDERVOLTAGE = "UNDERVOLTAGE"
OVERVOLTAGE = "OVERVOLTAGE"
OVERLOAD_CURRENT = "OVERLOAD_CURRENT"
OVER_TEMPERATURE = "OVER_TEMPERATURE"

# Demo thresholds (single place to tune them)
VOLTAGE_CRITICAL_LOW = 200.0
VOLTAGE_WARNING_LOW = 210.0
VOLTAGE_WARNING_HIGH = 250.0
VOLTAGE_CRITICAL_HIGH = 260.0
CURRENT_WARNING = 65.0
CURRENT_CRITICAL = 80.0
TEMP_WARNING = 65.0
TEMP_CRITICAL = 70.0

# Device connection freshness (device posts every ~2 s)
ONLINE_WITHIN_SECONDS = 10
STALE_WITHIN_SECONDS = 60


@dataclass(frozen=True)
class Fault:
    fault_type: str
    severity: str  # WARNING | CRITICAL
    actual: float
    threshold: float
    unit: str
    message: str
    recommended_action: str


def _fault(fault_type, severity, actual, threshold, unit, message, action) -> Fault:
    return Fault(fault_type, severity, float(actual), float(threshold), unit, message, action)


def evaluate_reading(
    voltage_v: float, current_a: float, temperature_c: float
) -> Tuple[str, List[Fault]]:
    """Return (overall_status, faults). Faults include WARNING and CRITICAL ones."""
    faults: List[Fault] = []

    # ── Voltage ──────────────────────────────────────────────────────────────
    if voltage_v < VOLTAGE_CRITICAL_LOW:
        faults.append(_fault(
            UNDERVOLTAGE, CRITICAL, voltage_v, VOLTAGE_CRITICAL_LOW, "V",
            f"Critical under-voltage: {voltage_v:.1f} V is below the {VOLTAGE_CRITICAL_LOW:.0f} V limit.",
            "Check the incoming supply and tap changer; look for a loose or failing HV/LV connection and reduce sensitive loads.",
        ))
    elif voltage_v > VOLTAGE_CRITICAL_HIGH:
        faults.append(_fault(
            OVERVOLTAGE, CRITICAL, voltage_v, VOLTAGE_CRITICAL_HIGH, "V",
            f"Critical over-voltage: {voltage_v:.1f} V is above the {VOLTAGE_CRITICAL_HIGH:.0f} V limit.",
            "Check the tap changer setting and the upstream supply; inspect surge arresters and isolate if the voltage persists.",
        ))
    elif voltage_v <= VOLTAGE_WARNING_LOW:
        faults.append(_fault(
            UNDERVOLTAGE, WARNING, voltage_v, VOLTAGE_WARNING_LOW, "V",
            f"Low voltage warning: {voltage_v:.1f} V is within the {VOLTAGE_CRITICAL_LOW:.0f}-{VOLTAGE_WARNING_LOW:.0f} V warning band.",
            "Monitor closely and check the supply and tap changer.",
        ))
    elif voltage_v >= VOLTAGE_WARNING_HIGH:
        faults.append(_fault(
            OVERVOLTAGE, WARNING, voltage_v, VOLTAGE_WARNING_HIGH, "V",
            f"High voltage warning: {voltage_v:.1f} V is within the {VOLTAGE_WARNING_HIGH:.0f}-{VOLTAGE_CRITICAL_HIGH:.0f} V warning band.",
            "Monitor closely and check the tap changer setting.",
        ))

    # ── Current ──────────────────────────────────────────────────────────────
    if current_a > CURRENT_CRITICAL:
        faults.append(_fault(
            OVERLOAD_CURRENT, CRITICAL, current_a, CURRENT_CRITICAL, "A",
            f"Critical overload: {current_a:.1f} A exceeds the {CURRENT_CRITICAL:.0f} A limit.",
            "Shed or rebalance load immediately, check for a short circuit, and dispatch a crew if the overload continues.",
        ))
    elif current_a > CURRENT_WARNING:
        faults.append(_fault(
            OVERLOAD_CURRENT, WARNING, current_a, CURRENT_WARNING, "A",
            f"High load warning: {current_a:.1f} A exceeds {CURRENT_WARNING:.0f} A.",
            "Monitor the load trend and plan load balancing.",
        ))

    # ── Temperature ──────────────────────────────────────────────────────────
    if temperature_c > TEMP_CRITICAL:
        faults.append(_fault(
            OVER_TEMPERATURE, CRITICAL, temperature_c, TEMP_CRITICAL, "C",
            f"Critical over-temperature: {temperature_c:.1f} C exceeds the {TEMP_CRITICAL:.0f} C limit.",
            "Reduce load, check oil level and cooling fins, and inspect for overheating; de-energise if it keeps rising.",
        ))
    elif temperature_c > TEMP_WARNING:
        faults.append(_fault(
            OVER_TEMPERATURE, WARNING, temperature_c, TEMP_WARNING, "C",
            f"High temperature warning: {temperature_c:.1f} C exceeds {TEMP_WARNING:.0f} C.",
            "Monitor the temperature trend and check cooling.",
        ))

    if any(f.severity == CRITICAL for f in faults):
        status = CRITICAL
    elif faults:
        status = WARNING
    else:
        status = SAFE
    return status, faults


def connection_state(age_seconds: float) -> str:
    """ONLINE / STALE / OFFLINE from the age of the latest reading."""
    if age_seconds <= ONLINE_WITHIN_SECONDS:
        return "ONLINE"
    if age_seconds <= STALE_WITHIN_SECONDS:
        return "STALE"
    return "OFFLINE"


def sync_alerts(
    db: Session,
    transformer_id,
    faults: List[Fault],
    now: datetime,
    telemetry_id: int,
) -> Tuple[List[IoTAlert], List[IoTAlert]]:
    """
    Reconcile the open alerts for one transformer with the current faults.

    - CRITICAL fault with no open alert of that type  -> open a new alert.
    - CRITICAL fault that already has an open alert    -> do nothing (no duplicates).
    - open alert whose fault is no longer CRITICAL     -> resolve it.
    - WARNING-level faults never create alerts (they only colour the status amber).

    Runs inside the caller's transaction; the caller commits.
    Returns (opened, resolved).
    """
    critical: Dict[str, Fault] = {f.fault_type: f for f in faults if f.severity == CRITICAL}

    open_alerts = (
        db.query(IoTAlert)
        .filter(IoTAlert.transformer_id == transformer_id, IoTAlert.resolved_at.is_(None))
        .all()
    )
    open_by_type = {a.fault_type: a for a in open_alerts}

    resolved: List[IoTAlert] = []
    for fault_type, alert in open_by_type.items():
        if fault_type not in critical:
            alert.status = "RESOLVED"
            alert.resolved_at = now
            resolved.append(alert)

    opened: List[IoTAlert] = []
    for fault_type, fault in critical.items():
        if fault_type in open_by_type:
            continue  # ongoing fault: already alerted
        alert = IoTAlert(
            transformer_id=transformer_id,
            trigger_telemetry_id=telemetry_id,
            fault_type=fault.fault_type,
            severity=CRITICAL,
            actual_value=fault.actual,
            threshold_value=fault.threshold,
            unit=fault.unit,
            message=fault.message,
            recommended_action=fault.recommended_action,
            status="ACTIVE",
            triggered_at=now,
        )
        # SAVEPOINT: if a concurrent request opened the same alert first, the partial
        # unique index rejects ours; we simply treat it as "already alerted".
        try:
            with db.begin_nested():
                db.add(alert)
                db.flush()
            opened.append(alert)
        except IntegrityError:
            pass

    return opened, resolved
