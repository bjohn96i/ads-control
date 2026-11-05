"""Hourly energy from the monitor's counters and hourly history, and hand-entered daily totals.

channel_energy holds raw Wh per channel per hour (before zone multipliers): from counter deltas
('counter'), a gap's delta spread by time ('spread'), or the monitor's own hourly history
('device', which wins). manual_daily_energy holds whole-house days from before recording.
"""

from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE channel_energy (
            hour timestamptz NOT NULL,
            channel smallint NOT NULL,
            wh double precision NOT NULL,
            source text NOT NULL CHECK (source IN ('counter', 'spread', 'device')),
            PRIMARY KEY (hour, channel)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE manual_daily_energy (
            day date PRIMARY KEY,
            kwh double precision NOT NULL CHECK (kwh >= 0),
            source text NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE manual_daily_energy")
    op.execute("DROP TABLE channel_energy")
