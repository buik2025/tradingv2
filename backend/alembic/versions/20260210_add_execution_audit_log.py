"""Add ExecutionAuditLog table for trade audit trail

Revision ID: 20260210_audit
Revises: 20260210_encrypt
Create Date: 2026-02-10 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260210_audit'
down_revision: Union[str, None] = '20260210_encrypt'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'execution_audit_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(50), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('correlation_id', sa.String(50), nullable=False),
        sa.Column('agent', sa.String(50), nullable=False),
        sa.Column('trade_id', sa.String(100), nullable=True),
        sa.Column('position_id', sa.String(100), nullable=True),
        sa.Column('order_id', sa.String(100), nullable=True),
        sa.Column('instrument', sa.String(100), nullable=True),
        sa.Column('instrument_token', sa.Integer(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('regime', sa.String(50), nullable=True),
        sa.Column('regime_confidence', sa.Float(), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('pnl', sa.Float(), nullable=True),
        sa.Column('pnl_pct', sa.Float(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=True, default=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for common queries
    op.create_index('ix_execution_audit_log_event_id', 'execution_audit_log', ['event_id'], unique=True)
    op.create_index('ix_execution_audit_log_timestamp', 'execution_audit_log', ['timestamp'])
    op.create_index('ix_execution_audit_log_event_type', 'execution_audit_log', ['event_type'])
    op.create_index('ix_execution_audit_log_correlation_id', 'execution_audit_log', ['correlation_id'])
    op.create_index('ix_execution_audit_log_trade_id', 'execution_audit_log', ['trade_id'])
    op.create_index('ix_execution_audit_log_position_id', 'execution_audit_log', ['position_id'])
    op.create_index('ix_execution_audit_log_order_id', 'execution_audit_log', ['order_id'])


def downgrade() -> None:
    op.drop_index('ix_execution_audit_log_order_id', table_name='execution_audit_log')
    op.drop_index('ix_execution_audit_log_position_id', table_name='execution_audit_log')
    op.drop_index('ix_execution_audit_log_trade_id', table_name='execution_audit_log')
    op.drop_index('ix_execution_audit_log_correlation_id', table_name='execution_audit_log')
    op.drop_index('ix_execution_audit_log_event_type', table_name='execution_audit_log')
    op.drop_index('ix_execution_audit_log_timestamp', table_name='execution_audit_log')
    op.drop_index('ix_execution_audit_log_event_id', table_name='execution_audit_log')
    op.drop_table('execution_audit_log')
