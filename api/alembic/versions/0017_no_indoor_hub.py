"""Remove the indoor Hub Max (a display with a camera); the app no longer lists displays."""

from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    op.execute("DELETE FROM cameras WHERE kind = 'display'")  # its events go with it (cascade)


def downgrade() -> None:
    pass  # the next camera sync would not bring it back either; nothing to restore
