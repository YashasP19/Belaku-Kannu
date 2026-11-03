"""sync transformers columns

Adds the live-status columns the Transformer model expects but the initial
schema lacked.

Revision ID: 3e6dbe60df0d
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa

revision = '3e6dbe60df0d'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

COLUMNS = [
    ('age_years', sa.Integer()),
    ('is_metered', sa.Boolean()),
    ('current_load_kw', sa.Float()),
    ('current_load_pct', sa.Float()),
    ('current_oil_temp_c', sa.Float()),
    ('current_health_score', sa.Integer()),
    ('current_failure_risk', sa.Float()),
    ('expected_lifetime_days', sa.Integer()),
    ('current_status', sa.String(length=50)),
    ('last_updated', sa.DateTime()),
]


def upgrade() -> None:
    for name, typ in COLUMNS:
        op.add_column('transformers', sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column('transformers', name)
