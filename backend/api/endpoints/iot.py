"""
IoT live monitoring endpoints (ESP32 / Wokwi)
===============================================
  POST /telemetry                       device -> backend   (X-Device-Key required)
  GET  /telemetry/latest                dashboard: newest reading per transformer
  GET  /telemetry/history               dashboard: recent readings for one transformer
  GET  /iot-alerts                      dashboard: emergency alerts (active / resolved / all)
  POST /iot-alerts/{id}/acknowledge     dashboard: acknowledge an alert

Threshold alerts here are independent of the ML health score.
"""
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from crud import crud_ticket
from models.asset import Transformer
from models.iot import IoTAlert, IoTTelemetry
from schemas.ticket import TicketCreate
from schemas.iot import (
    AlertBrief, InspectionOut, InspectionRequest, InspectionTicketIn, IoTAlertOut, LiveTelemetryOut, TelemetryAck,
    TelemetryIn, TelemetryOut,
)
from services import iot_alerts, iot_inspection

logger = logging.getLogger("iot")
router = APIRouter()

# Only transformers that reported in this window are shown as "live".
LIVE_WINDOW = timedelta(hours=24)


def require_device_key(x_device_key: Optional[str] = Header(default=None, alias="X-Device-Key")) -> None:
    """Authenticate a device by the shared key from the environment (fails closed)."""
    configured = settings.DEVICE_API_KEY
    if not configured:
        raise HTTPException(status_code=503, detail="Device ingestion is not configured on the server.")
    if not x_device_key or not secrets.compare_digest(x_device_key.encode(), configured.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing device key.")


def _find_transformer(db: Session, ref: str):
    """Resolve a transformer by UUID or by transformer_code. Selects id+code only."""
    query = db.query(
        Transformer.id, Transformer.transformer_code, Transformer.rated_kva, Transformer.age_years
    )
    try:
        row = query.filter(Transformer.id == uuid.UUID(ref)).first()
        if row:
            return row
    except ValueError:
        pass
    return query.filter(Transformer.transformer_code == ref).first()


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat a naive device timestamp as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ─── Device -> backend ────────────────────────────────────────────────────────
@router.post("/telemetry", response_model=TelemetryAck, status_code=201, tags=["IoT Live Monitoring"])
def ingest_telemetry(
    payload: TelemetryIn,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_device_key),
):
    transformer = _find_transformer(db, payload.transformer_id)
    if transformer is None:
        raise HTTPException(status_code=404, detail=f"Unknown transformer '{payload.transformer_id}'.")

    now = datetime.now(timezone.utc)  # one clock for received_at and alert times
    status, faults = iot_alerts.evaluate_reading(
        payload.voltage_v, payload.current_a, payload.temperature_c
    )

    row = IoTTelemetry(
        transformer_id=transformer.id,
        voltage_v=payload.voltage_v,
        current_a=payload.current_a,
        temperature_c=payload.temperature_c,
        status=status,
        device_status=payload.status,
        device_timestamp=_aware(payload.timestamp),
        received_at=now,
    )
    db.add(row)
    db.flush()  # assigns row.id

    opened, resolved = iot_alerts.sync_alerts(db, transformer.id, faults, now, row.id)
    db.commit()  # reading + alert changes are saved together or not at all

    for a in opened:
        logger.warning("ALERT OPENED %s %s: %s", transformer.transformer_code, a.fault_type, a.message)
    for a in resolved:
        logger.info("ALERT RESOLVED %s %s", transformer.transformer_code, a.fault_type)

    return TelemetryAck(
        id=row.id,
        transformer_id=transformer.id,
        transformer_code=transformer.transformer_code,
        status=status,
        received_at=row.received_at,
        alerts_opened=[AlertBrief(id=a.id, fault_type=a.fault_type, message=a.message) for a in opened],
        alerts_resolved=[AlertBrief(id=a.id, fault_type=a.fault_type, message=a.message) for a in resolved],
    )


# ─── Dashboard reads ──────────────────────────────────────────────────────────
@router.get("/telemetry/latest", response_model=List[LiveTelemetryOut], tags=["IoT Live Monitoring"])
def latest_telemetry(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Newest reading for each transformer that reported in the last 24 hours."""
    now = datetime.now(timezone.utc)
    ranked = (
        select(
            IoTTelemetry.id.label("id"),
            func.row_number().over(
                partition_by=IoTTelemetry.transformer_id,
                order_by=IoTTelemetry.received_at.desc(),
            ).label("rn"),
        )
        .where(IoTTelemetry.received_at >= now - LIVE_WINDOW)
        .subquery()
    )
    rows = db.execute(
        select(IoTTelemetry, Transformer.transformer_code)
        .join(ranked, ranked.c.id == IoTTelemetry.id)
        .join(Transformer, Transformer.id == IoTTelemetry.transformer_id)
        .where(ranked.c.rn == 1)
        .order_by(IoTTelemetry.received_at.desc())
        .limit(limit)
    ).all()

    out = []
    for t, code in rows:
        age = max((now - t.received_at).total_seconds(), 0.0)
        out.append(LiveTelemetryOut(
            id=t.id, transformer_id=t.transformer_id, transformer_code=code,
            voltage_v=t.voltage_v, current_a=t.current_a, temperature_c=t.temperature_c,
            status=t.status, device_status=t.device_status,
            device_timestamp=t.device_timestamp, received_at=t.received_at,
            age_seconds=round(age, 1), connection=iot_alerts.connection_state(age),
        ))
    return out


@router.get("/telemetry/history", response_model=List[TelemetryOut], tags=["IoT Live Monitoring"])
def telemetry_history(
    transformer_id: str,
    limit: int = Query(60, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Most recent readings for one transformer (UUID or code), newest first."""
    transformer = _find_transformer(db, transformer_id)
    if transformer is None:
        raise HTTPException(status_code=404, detail=f"Unknown transformer '{transformer_id}'.")
    rows = (
        db.query(IoTTelemetry)
        .filter(IoTTelemetry.transformer_id == transformer.id)
        .order_by(IoTTelemetry.received_at.desc())
        .limit(limit)
        .all()
    )
    return [
        TelemetryOut(
            id=t.id, transformer_id=t.transformer_id, transformer_code=transformer.transformer_code,
            voltage_v=t.voltage_v, current_a=t.current_a, temperature_c=t.temperature_c,
            status=t.status, device_status=t.device_status,
            device_timestamp=t.device_timestamp, received_at=t.received_at,
        )
        for t in rows
    ]


def _alert_out(alert: IoTAlert, code: str) -> IoTAlertOut:
    return IoTAlertOut(
        id=alert.id, transformer_id=alert.transformer_id, transformer_code=code,
        fault_type=alert.fault_type, severity=alert.severity,
        actual_value=alert.actual_value, threshold_value=alert.threshold_value, unit=alert.unit,
        message=alert.message, recommended_action=alert.recommended_action, status=alert.status,
        triggered_at=alert.triggered_at, acknowledged_at=alert.acknowledged_at,
        resolved_at=alert.resolved_at,
    )


@router.get("/iot-alerts", response_model=List[IoTAlertOut], tags=["IoT Live Monitoring"])
def list_iot_alerts(
    scope: Literal["active", "resolved", "all"] = "all",
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """active = still open (ACTIVE or ACKNOWLEDGED), resolved = cleared, all = full history."""
    query = select(IoTAlert, Transformer.transformer_code).join(
        Transformer, Transformer.id == IoTAlert.transformer_id
    )
    if scope == "active":
        query = query.where(IoTAlert.resolved_at.is_(None))
    elif scope == "resolved":
        query = query.where(IoTAlert.resolved_at.is_not(None))
    rows = db.execute(query.order_by(IoTAlert.triggered_at.desc()).limit(limit)).all()
    return [_alert_out(a, code) for a, code in rows]


@router.post("/iot-alerts/{alert_id}/acknowledge", response_model=IoTAlertOut, tags=["IoT Live Monitoring"])
def acknowledge_iot_alert(alert_id: uuid.UUID, db: Session = Depends(get_db)):
    """Mark an open alert as seen. It stays listed until the readings return to normal."""
    alert = db.get(IoTAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    if alert.resolved_at is not None:
        raise HTTPException(status_code=409, detail="Alert is already resolved.")
    if alert.status == "ACTIVE":
        alert.status = "ACKNOWLEDGED"
        alert.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(alert)
    code = db.query(Transformer.transformer_code).filter(Transformer.id == alert.transformer_id).scalar()
    return _alert_out(alert, code)


# ─── Run Inspection: existing ML models on the latest live readings ──────────
@router.post("/iot-inspection", response_model=InspectionOut, tags=["IoT Live Monitoring"])
def run_iot_inspection(payload: InspectionRequest, db: Session = Depends(get_db)):
    """
    Runs Isolation Forest, XGBoost, Random Forest and Cox (+ SHAP) on the transformer's
    most recent live readings and returns scores, risk drivers and recommended actions.
    """
    transformer = _find_transformer(db, payload.transformer_id)
    if transformer is None:
        raise HTTPException(status_code=404, detail=f"Unknown transformer '{payload.transformer_id}'.")

    rows = (
        db.query(IoTTelemetry)
        .filter(IoTTelemetry.transformer_id == transformer.id)
        .order_by(IoTTelemetry.received_at.desc())
        .limit(iot_inspection.WINDOW_READINGS)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=409, detail="No live readings for this transformer yet. Start the device first.")

    open_alerts = (
        db.query(func.count(IoTAlert.id))
        .filter(IoTAlert.transformer_id == transformer.id, IoTAlert.resolved_at.is_(None))
        .scalar()
    )
    try:
        return iot_inspection.run_inspection(transformer, rows, int(open_alerts or 0))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/iot-inspection/ticket", tags=["IoT Live Monitoring"])
def raise_iot_inspection_ticket(payload: InspectionTicketIn, db: Session = Depends(get_db)):
    """Raise a maintenance ticket from an IoT inspection (one open ticket per transformer + priority)."""
    transformer = _find_transformer(db, payload.transformer_id)
    if transformer is None:
        raise HTTPException(status_code=404, detail=f"Unknown transformer '{payload.transformer_id}'.")
    ticket = crud_ticket.create_ticket(
        db,
        TicketCreate(
            transformer_id=str(transformer.id),
            priority=payload.priority,
            description=f"[IoT inspection] {payload.summary}"[:2000],
            trigger_type="MANUAL",
            health_score=payload.health_score,
            dedup_key=f"IOT:{payload.priority}:{transformer.id}",
        ),
    )
    if ticket is None:
        raise HTTPException(status_code=409, detail="A matching open ticket already exists for this transformer.")
    return {"id": str(ticket.id), "status": ticket.status, "priority": ticket.priority,
            "transformer_code": transformer.transformer_code}
