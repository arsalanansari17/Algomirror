"""Add app_settings table for platform-wide feature toggles

Revision ID: 005_add_app_settings
Revises: 004_fix_trade_quality_labels
Create Date: 2026-07-05

Adds a singleton app_settings table with strategy_engine_enabled, so admins
can turn off the strategy execution surface (Strategy Builder, Risk Manager,
Supertrend Exit, Order Poller, broker-position reconciliation) for
deployments that only use AlgoMirror to view accounts run by an external
strategy engine.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_add_app_settings'
down_revision = '004_fix_trade_quality_labels'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('strategy_engine_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.execute("INSERT INTO app_settings (strategy_engine_enabled) VALUES (1)")


def downgrade():
    op.drop_table('app_settings')
