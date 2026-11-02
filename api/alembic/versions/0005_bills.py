"""Power bills, one per billing period."""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bills (
            id serial PRIMARY KEY,
            period_start date NOT NULL,
            period_end date NOT NULL,
            on_peak_kwh double precision,
            off_peak_kwh double precision,
            super_off_peak_kwh double precision,
            total_kwh double precision NOT NULL,
            current_service double precision,
            ecc double precision,
            franchise_fee double precision,
            sales_tax double precision,
            actual_charge double precision NOT NULL,
            budget_payment double precision,
            budget_difference double precision,
            running_difference double precision,
            UNIQUE (period_start, period_end)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE bills")
