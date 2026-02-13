"""Add trailing stop columns to strategies table

Revision ID: 20260212_trailing_stop
Revises: 20260210_add_execution_audit_log
Create Date: 2026-02-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260212_trailing_stop'
down_revision = '20260210_audit'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add trailing stop configuration columns to strategies table
    op.add_column('strategies', sa.Column('trailing_stop_enabled', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('strategies', sa.Column('trailing_activation_pct', sa.Numeric(6, 3), nullable=True, server_default='0.8'))
    op.add_column('strategies', sa.Column('trailing_step_pct', sa.Numeric(6, 3), nullable=True, server_default='0.1'))
    op.add_column('strategies', sa.Column('trailing_lock_pct', sa.Numeric(6, 3), nullable=True, server_default='0.05'))
    op.add_column('strategies', sa.Column('trailing_current_floor_pct', sa.Numeric(6, 3), nullable=True))
    op.add_column('strategies', sa.Column('trailing_high_water_pct', sa.Numeric(6, 3), nullable=True))
    op.add_column('strategies', sa.Column('trailing_margin_used', sa.Numeric(14, 2), nullable=True))
    op.add_column('strategies', sa.Column('trailing_activated_at', sa.DateTime(), nullable=True))
    op.add_column('strategies', sa.Column('trailing_sl_order_ids', sa.JSON(), nullable=True))


def downgrade() -> None:
    # Remove trailing stop columns
    op.drop_column('strategies', 'trailing_sl_order_ids')
    op.drop_column('strategies', 'trailing_activated_at')
    op.drop_column('strategies', 'trailing_margin_used')
    op.drop_column('strategies', 'trailing_high_water_pct')
    op.drop_column('strategies', 'trailing_current_floor_pct')
    op.drop_column('strategies', 'trailing_lock_pct')
    op.drop_column('strategies', 'trailing_step_pct')
    op.drop_column('strategies', 'trailing_activation_pct')
    op.drop_column('strategies', 'trailing_stop_enabled')
