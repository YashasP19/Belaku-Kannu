"""Pydantic schemas for the IoT live-monitoring endpoints."""
from datetime import datetime
from typing import List, Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TelemetryIn(BaseModel):
    """One reading posted by a device."""
    transformer_id: str = Field(min_length=1, max_length=64,
                                description="Transformer UUID or transformer_code (e.g. TRF_GHY_001)")
    voltage_v: float = Field(ge=0, le=1000, allow_inf_nan=False)
    current_a: float = Field(ge=0, le=2000, allow_inf_nan=False)
    temperature_c: float = Field(ge=-50, le=200, allow_inf_nan=False)
    status: Optional[Literal["SAFE", "WARNING", "CRITICAL"]] = Field(
        default=None, description="Status computed on the device (informational only)")
    timestamp: Optional[datetime] = Field(default=None, description="Device clock, ISO 8601")

    @field_validator("transformer_id")
    @classmethod
    def _strip_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("transformer_id must not be blank")
        return v

    @field_validator("status", mode="before")
    @classmethod
    def _upper_status(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class AlertBrief(BaseModel):
    id: uuid.UUID
    fault_type: str
    message: str


class TelemetryAck(BaseModel):
    id: int
    transformer_id: uuid.UUID
    transformer_code: str
    status: str
    received_at: datetime
    alerts_opened: List[AlertBrief] = []
    alerts_resolved: List[AlertBrief] = []


class TelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transformer_id: uuid.UUID
    transformer_code: str
    voltage_v: float
    current_a: float
    temperature_c: float
    status: str
    device_status: Optional[str] = None
    device_timestamp: Optional[datetime] = None
    received_at: datetime


class LiveTelemetryOut(TelemetryOut):
    age_seconds: float
    connection: Literal["ONLINE", "STALE", "OFFLINE"]


class IoTAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transformer_id: uuid.UUID
    transformer_code: str
    fault_type: str
    severity: str
    actual_value: float
    threshold_value: float
    unit: str
    message: str
    recommended_action: str
    status: str
    triggered_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


# ─── "Run Inspection": existing ML models on live readings ────────────────────
class InspectionRequest(BaseModel):
    transformer_id: str = Field(min_length=1, max_length=64,
                                description="Transformer UUID or transformer_code")


class InspectionModel(BaseModel):
    key: str
    name: str
    role: str
    verdict: str            # HEALTHY | WARNING | CRITICAL
    risk_score: float       # 0-100, higher = riskier
    weight: float           # share of the blended health score
    in_blend: bool          # False for the classifier that lost the XGBoost/RF comparison
    expected_lifetime_days: Optional[int] = None


class InspectionDriver(BaseModel):
    feature: str
    label: str
    value: float
    impact: float
    direction: str


class InspectionProtection(BaseModel):
    status: str
    open_alerts: int
    faults: List[dict]


class InspectionRecommendation(BaseModel):
    priority: Literal["URGENT", "SOON", "ROUTINE"]
    action: str
    reason: str


class InspectionInputs(BaseModel):
    readings_used: int
    window_seconds: float
    data_age_seconds: float
    rated_kva: float
    age_years: int
    avg_voltage_v: float
    avg_current_a: float
    avg_temperature_c: float
    avg_voltage_lv_mapped: float
    avg_load_pct_mapped: float
    notes: List[str]


class InspectionOut(BaseModel):
    transformer_id: uuid.UUID
    transformer_code: str
    run_at: datetime
    health_score: float
    risk_category: str
    failure_probability: Optional[float] = None
    expected_lifetime_days: Optional[int] = None
    models: List[InspectionModel]
    drivers: List[InspectionDriver]
    protection: InspectionProtection
    summary: str
    recommendations: List[InspectionRecommendation]
    inputs: InspectionInputs


class InspectionTicketIn(BaseModel):
    transformer_id: str = Field(min_length=1, max_length=64)
    priority: Literal["CRITICAL", "HIGH"]
    summary: str = Field(min_length=1, max_length=1800)
    health_score: Optional[float] = Field(default=None, ge=0, le=100)
