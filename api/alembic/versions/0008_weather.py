"""Outdoor temperature, so a hot week is not mistaken for a bad setting."""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("CREATE TABLE outdoor_readings (time timestamptz PRIMARY KEY, temp_c real NOT NULL)")


def downgrade() -> None:
    op.execute("DROP TABLE outdoor_readings")
