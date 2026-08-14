"""Add privacy_hide_* columns to app_settings for Privacy Mode

Revision ID: 010_add_privacy_mode
Revises: 009_add_position_tags
Create Date: 2026-08-14

Adds 5 boolean columns to the existing app_settings singleton table -
privacy_hide_account_name, privacy_hide_quantity, privacy_hide_avg_price,
privacy_hide_pnl, privacy_hide_value - configuring which categories of
sensitive data the navbar Privacy Mode toggle blurs when switched on.
Defaults to True (hide everything) so the feature is useful the moment
it's toggled on, without a trip to Platform Settings first.

Unlike migration 005 (which created app_settings from scratch and could
lean on app/__init__.py's unconditional db.create_all() as a fallback),
create_all() never alters an existing table to add new columns - it only
creates tables that don't exist yet. So this migration is the only path
that actually adds these columns; it's guarded with a column-existence
check per column to stay idempotent on repeat runs.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '010_add_privacy_mode'
down_revision = '009_add_position_tags'
branch_labels = None
depends_on = None


NEW_COLUMNS = [
    'privacy_hide_account_name',
    'privacy_hide_quantity',
    'privacy_hide_avg_price',
    'privacy_hide_pnl',
    'privacy_hide_value',
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col['name'] for col in inspector.get_columns('app_settings')}

    for column_name in NEW_COLUMNS:
        if column_name not in existing_columns:
            op.add_column(
                'app_settings',
                sa.Column(column_name, sa.Boolean(), nullable=False, server_default=sa.true()),
            )


def downgrade():
    for column_name in NEW_COLUMNS:
        op.drop_column('app_settings', column_name)
