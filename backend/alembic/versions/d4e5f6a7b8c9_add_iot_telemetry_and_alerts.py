"""add iot_telemetry and iot_alerts tables

Revision ID: d4e5f6a7b8c9
Revises: 3e6dbe60df0d
Create Date: 2026-11-18 10:00:00.000000

Live-monitoring tables for the ESP32 / Wokwi pipeline.

  iot_telemetry — raw device readings (voltage, current, temperature)
  iot_alerts    — threshold-based emergency alerts

The partial unique index uq_iot_alerts_open_fault guarantees at most one OPEN
(unresolved) alert per transformer + fault type, which is what de-duplicates
alerts while a fault is ongoing. Once an alert is resolved the row is kept for
history and the same fault can raise a fresh alert later.

Purely additive: no existing table is touched. Downgrade drops both tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = '3e6dbe60df0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'iot_telemetry',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('transformer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('voltage_v', sa.Float(), nullable=False),
        sa.Column('current_a', sa.Float(), nullable=False),
        sa.Column('temperature_c', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('device_status', sa.String(length=16), nullable=True),
        sa.Column('device_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['transformer_id'], ['transformers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_iot_telemetry_transformer_received',
        'iot_telemetry',
        ['transformer_id', sa.text('received_at DESC')],
        unique=False,
    )

    op.create_table(
        'iot_alerts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('transformer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('trigger_telemetry_id', sa.BigInteger(), nullable=True),
        sa.Column('fault_type', sa.String(length=32), nullable=False),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('actual_value', sa.Float(), nullable=False),
        sa.Column('threshold_value', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(length=8), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('recommended_action', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['transformer_id'], ['transformers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trigger_telemetry_id'], ['iot_telemetry.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_iot_alerts_status', 'iot_alerts', ['status'], unique=False)
    op.create_index(
        'idx_iot_alerts_triggered', 'iot_alerts', [sa.text('triggered_at DESC')], unique=False
    )
    op.create_index(
        'uq_iot_alerts_open_fault',
        'iot_alerts',
        ['transformer_id', 'fault_type'],
        unique=True,
        postgresql_where=sa.text('resolved_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_iot_alerts_open_fault', table_name='iot_alerts')
    op.drop_index('idx_iot_alerts_triggered', table_name='iot_alerts')
    op.drop_index('ix_iot_alerts_status', table_name='iot_alerts')
    op.drop_table('iot_alerts')
    op.drop_index('idx_iot_telemetry_transformer_received', table_name='iot_telemetry')
    op.drop_table('iot_telemetry')
