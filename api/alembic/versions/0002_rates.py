"""Dated electricity rates, seeded from the published tariff."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"

# Copied from rates.SEED_RATE as it stood when this migration was written; a later rate change
# belongs in a new migration, not here.
SEED_RATE = {
    "effective_from": "2026-06-01",
    "on_peak_c": 35.0137,
    "off_peak_c": 14.0366,
    "super_off_peak_c": 5.6606,
    "basic_per_day": 0.4603,
    "adder_factor": 1.1882,
    "source": "TOU-OA-14 (Jan 2025) + TOU-FCR-TP-5 (Jun 2026), adders from the Oct 2026 bill",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rate_versions (
            effective_from date PRIMARY KEY,
            on_peak_c double precision NOT NULL,
            off_peak_c double precision NOT NULL,
            super_off_peak_c double precision NOT NULL,
            basic_per_day double precision NOT NULL,
            adder_factor double precision NOT NULL,
            source text NOT NULL
        )
        """
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO rate_versions VALUES (:effective_from, :on_peak_c, :off_peak_c, :super_off_peak_c, :basic_per_day, :adder_factor, :source)"
        ),
        SEED_RATE,
    )


def downgrade() -> None:
    op.execute("DROP TABLE rate_versions")
