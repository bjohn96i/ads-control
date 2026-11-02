"""Channel readings, rollups and zones."""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None

# name, channels, kind, pin_x, pin_y (percent across and down the house picture), seasonal
ZONES = [
    ("Whole House", [1, 7], "incoming", 0, 0, False),
    ("Fridge/Stove", [2], "circuit", 62, 56, False),
    ("Dishwasher", [3], "circuit", 62, 66, False),
    ("Dryer", [5, 11], "circuit", 38, 88, False),
    ("Basement", [6], "circuit", 14, 88, False),
    ("Microwave/Sink Light", [8], "circuit", 84, 56, False),
    ("Washer", [9], "circuit", 62, 88, False),
    ("Guest Bedroom (Upstairs)", [10], "circuit", 38, 34, False),
    ("Downstairs A/C", [12], "circuit", 14, 66, True),
    ("Primary Bedroom", [14], "circuit", 68, 34, False),
    ("Living Room", [15], "circuit", 28, 56, False),
    ("Water Heater", [17], "circuit", 84, 88, False),
    ("Upstairs A/C", [18], "circuit", 50, 18, True),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE channel_readings (
            time timestamptz NOT NULL,
            channel smallint NOT NULL,
            power_w real NOT NULL,
            voltage_v real NOT NULL,
            current_a real NOT NULL,
            power_factor real NOT NULL,
            consume_wh integer NOT NULL,
            PRIMARY KEY (time, channel)
        )
        """
    )
    op.execute("SELECT create_hypertable('channel_readings', 'time')")
    op.execute(
        "ALTER TABLE channel_readings SET (timescaledb.compress, timescaledb.compress_segmentby = 'channel')"
    )
    op.execute("SELECT add_compression_policy('channel_readings', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('channel_readings', INTERVAL '90 days')")

    with op.get_context().autocommit_block():
        for view, bucket in (
            ("channel_hourly", "time_bucket('1 hour', time)"),
            # Local days, so a day's kWh matches the day the household lived through.
            ("channel_daily", "time_bucket('1 day', time, 'America/New_York')"),
        ):
            op.execute(
                f"""
                CREATE MATERIALIZED VIEW {view}
                WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
                SELECT {bucket} AS bucket, channel,
                       avg(power_w) AS avg_w, min(power_w) AS min_w, max(power_w) AS max_w,
                       count(*) AS samples
                FROM channel_readings
                GROUP BY 1, 2
                WITH NO DATA
                """
            )
        op.execute(
            "SELECT add_continuous_aggregate_policy('channel_hourly', start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '15 minutes')"
        )
        op.execute(
            "SELECT add_continuous_aggregate_policy('channel_daily', start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 day', schedule_interval => INTERVAL '1 hour')"
        )

    op.execute(
        """
        CREATE TABLE zones (
            id serial PRIMARY KEY,
            name text NOT NULL UNIQUE,
            channels smallint[] NOT NULL,
            multiplier real NOT NULL DEFAULT 1,
            kind text NOT NULL CHECK (kind IN ('incoming', 'circuit')),
            pin_x real NOT NULL,
            pin_y real NOT NULL,
            seasonal boolean NOT NULL DEFAULT false
        )
        """
    )
    insert = sa.text(
        "INSERT INTO zones (name, channels, kind, pin_x, pin_y, seasonal) "
        "VALUES (:name, :channels, :kind, :pin_x, :pin_y, :seasonal)"
    )
    for name, channels, kind, pin_x, pin_y, seasonal in ZONES:
        op.get_bind().execute(
            insert,
            dict(
                name=name, channels=channels, kind=kind, pin_x=pin_x, pin_y=pin_y, seasonal=seasonal
            ),
        )


def downgrade() -> None:
    op.execute("DROP TABLE zones")
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW channel_daily")
        op.execute("DROP MATERIALIZED VIEW channel_hourly")
    op.execute("DROP TABLE channel_readings")
