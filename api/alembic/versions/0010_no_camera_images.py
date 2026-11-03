"""Google gives no event pictures for these cameras, so the image time goes."""

from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute("ALTER TABLE cameras DROP COLUMN image_at")


def downgrade() -> None:
    op.execute("ALTER TABLE cameras ADD COLUMN image_at timestamptz")
