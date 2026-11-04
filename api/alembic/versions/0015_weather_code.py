"""Current conditions with the outdoor temperature: Open-Meteo's WMO weather code and day or night."""

from alembic import op

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE outdoor_readings ADD COLUMN weather_code smallint, ADD COLUMN is_day boolean"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE outdoor_readings DROP COLUMN weather_code, DROP COLUMN is_day")
