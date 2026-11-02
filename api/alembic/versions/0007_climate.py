"""Thermostats and what they report over time."""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE thermostats (
            id serial PRIMARY KEY,
            device_id text NOT NULL UNIQUE,
            name text NOT NULL,
            zone_id integer REFERENCES zones ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE thermostat_readings (
            time timestamptz NOT NULL,
            thermostat_id integer NOT NULL,
            ambient_c real,
            humidity real,
            heat_c real,
            cool_c real,
            mode text,
            hvac_status text,
            eco boolean NOT NULL DEFAULT false,
            online boolean NOT NULL DEFAULT true,
            PRIMARY KEY (time, thermostat_id)
        )
        """
    )
    op.execute("SELECT create_hypertable('thermostat_readings', 'time')")


def downgrade() -> None:
    op.execute("DROP TABLE thermostat_readings")
    op.execute("DROP TABLE thermostats")
