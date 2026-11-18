"""
IoT live-monitoring models
===========================
Two tables for the ESP32 / Wokwi live-monitoring pipeline:

  iot_telemetry  — every reading posted by a device (voltage, current, temperature)
  iot_alerts     — emergency alerts raised by the *threshold* rules

These are deliberately separate from the ML health predictions
(transformers.current_health_score etc.). Threshold alerts are simple,
explainable rules; the ML score is a predictive model. They never write to
each other.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDMixin

# BigInteger autoincrement primary key; SQLite (local fallback) needs plain Integer.
_BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class IoTTelemetry(Base):
    __tablename__ = "iot_telemetry"

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    transformer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transformers.id", ondelete="CASCADE"), nullable=False
    )

    voltage_v: Mapped[float] = mapped_column(Float, nullable=False)
    current_a: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)

    # Status computed by the BACKEND from the demo thresholds (source of truth).
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # SAFE | WARNING | CRITICAL
    # Status the device itself reported (kept for comparison/debugging only).
    device_status: Mapped[Optional[str]] = mapped_column(String(16))

    # Time according to the device clock (optional) vs. when the server received it.
    device_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("idx_iot_telemetry_transformer_received", "transformer_id", text("received_at DESC")),
    )


class IoTAlert(Base, UUIDMixin):
    __tablename__ = "iot_alerts"

    transformer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transformers.id", ondelete="CASCADE"), nullable=False
    )
    # The reading that first triggered this alert.
    trigger_telemetry_id: Mapped[Optional[int]] = mapped_column(
        _BigIntPK, ForeignKey("iot_telemetry.id", ondelete="SET NULL")
    )

    fault_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # UNDERVOLTAGE | OVERVOLTAGE | OVERLOAD_CURRENT | OVER_TEMPERATURE
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="CRITICAL")

    actual_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(8), nullable=False)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", index=True)
    # ACTIVE -> ACKNOWLEDGED (optional) -> RESOLVED (readings back to normal)

    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # At most ONE open (unresolved) alert per transformer + fault type.
        # This is what stops a new alert every 2 seconds for an ongoing fault,
        # even if two requests race each other.
        Index(
            "uq_iot_alerts_open_fault",
            "transformer_id",
            "fault_type",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
            sqlite_where=text("resolved_at IS NULL"),
        ),
        Index("idx_iot_alerts_triggered", text("triggered_at DESC")),
    )
