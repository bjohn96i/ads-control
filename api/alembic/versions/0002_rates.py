"""Dated electricity rates, seeded from the published tariff."""

import sqlalchemy as sa

from adscontrol.rates import SEED_RATE
from alembic import op

revision = "0002"
down_revision = "0001"


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
        SEED_RATE.__dict__,
    )


def downgrade() -> None:
    op.execute("DROP TABLE rate_versions")
