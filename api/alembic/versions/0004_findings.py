"""Anomaly and creep findings: at most one open per zone and kind."""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE findings (
            id serial PRIMARY KEY,
            zone_id integer NOT NULL REFERENCES zones ON DELETE CASCADE,
            kind text NOT NULL CHECK (kind IN ('anomaly', 'creep')),
            opened_at timestamptz NOT NULL,
            last_seen timestamptz NOT NULL,
            resolved_at timestamptz,
            evidence jsonb NOT NULL
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX findings_open ON findings (zone_id, kind) WHERE resolved_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE findings")
