"""Maintenance repeats in days, weeks or months, not only months."""

from alembic import op

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    op.execute("ALTER TABLE tasks RENAME COLUMN interval_months TO repeat_every")
    op.execute(
        "ALTER TABLE tasks ADD COLUMN repeat_unit text NOT NULL DEFAULT 'month' "
        "CHECK (repeat_unit IN ('day', 'week', 'month'))"
    )


def downgrade() -> None:
    # Months only after this: day and week repeats become the nearest whole month (at least one).
    op.execute(
        """
        UPDATE tasks SET repeat_every = GREATEST(1, round(
            repeat_every * CASE repeat_unit WHEN 'week' THEN 7 ELSE 1 END / 30.0))
        WHERE repeat_unit <> 'month' AND repeat_every IS NOT NULL
        """
    )
    op.execute("ALTER TABLE tasks DROP COLUMN repeat_unit")
    op.execute("ALTER TABLE tasks RENAME COLUMN repeat_every TO interval_months")
