"""
Migration: Enforce one MarginTracker row per account

Two code paths could each create a MarginTracker for the same account_id
with no coordination (MarginCalculator.get_available_margin() and the
/margin/tracker and /margin/refresh-tracker routes), so a first-time fetch
or two near-simultaneous refreshes could leave more than one row per
account. Later .first() reads/updates against those extra rows are
nondeterministic. Dedupes existing duplicates (keeping the highest id,
i.e. the most recently created row, per account) before adding the
constraint.
"""

from sqlalchemy import text


def upgrade(db):
    """Dedupe margin_trackers and add a unique constraint on account_id"""

    result = db.session.execute(text("""
        DELETE FROM margin_trackers
        WHERE id NOT IN (
            SELECT MAX(id) FROM margin_trackers GROUP BY account_id
        )
    """))
    if result.rowcount:
        print(f"Removed {result.rowcount} duplicate margin_trackers row(s)")
    db.session.commit()

    try:
        db.session.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_margin_trackers_account_id "
            "ON margin_trackers(account_id)"
        ))
        db.session.commit()
        print("Added unique index on margin_trackers.account_id")
    except Exception as e:
        db.session.rollback()
        error_msg = str(e).lower()
        if 'already exists' in error_msg or 'duplicate' in error_msg:
            print("Unique index already exists, skipping")
        else:
            raise


def downgrade(db):
    """Drop the unique index"""
    db.session.execute(text("DROP INDEX IF EXISTS ux_margin_trackers_account_id"))
    db.session.commit()
