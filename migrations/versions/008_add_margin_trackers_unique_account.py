"""Enforce one MarginTracker row per account

Revision ID: 008_unique_tracker
Revises: 007_add_session_token
Create Date: 2026-08-07

Two code paths could each create a MarginTracker for the same account_id
with no coordination (MarginCalculator.get_available_margin() and the
/margin/tracker and /margin/refresh-tracker routes), so a first-time fetch
or two near-simultaneous refreshes could leave more than one row per
account. Dedupes existing duplicates (keeping the highest id, i.e. the
most recently created row, per account) before adding the constraint.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_unique_tracker'
down_revision = '007_add_session_token'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        DELETE FROM margin_trackers
        WHERE id NOT IN (
            SELECT MAX(id) FROM margin_trackers GROUP BY account_id
        )
    """))

    inspector = sa.inspect(bind)
    existing_indexes = [ix['name'] for ix in inspector.get_indexes('margin_trackers')]
    if 'ux_margin_trackers_account_id' not in existing_indexes:
        with op.batch_alter_table('margin_trackers', schema=None) as batch_op:
            batch_op.create_unique_constraint('ux_margin_trackers_account_id', ['account_id'])


def downgrade():
    with op.batch_alter_table('margin_trackers', schema=None) as batch_op:
        batch_op.drop_constraint('ux_margin_trackers_account_id', type_='unique')
