"""Cameras and their events. Only the latest image per camera is kept, as a file."""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cameras (
            id serial PRIMARY KEY,
            device_id text NOT NULL UNIQUE,
            name text NOT NULL,
            kind text NOT NULL,
            image_at timestamptz
        )
        """
    )
    op.execute(
        """
        CREATE TABLE camera_events (
            id serial PRIMARY KEY,
            camera_id integer NOT NULL REFERENCES cameras ON DELETE CASCADE,
            type text NOT NULL,
            occurred_at timestamptz NOT NULL,
            event_id text NOT NULL UNIQUE
        )
        """
    )
    op.execute("CREATE INDEX camera_events_latest ON camera_events (camera_id, occurred_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE camera_events")
    op.execute("DROP TABLE cameras")
