"""The office room is called Batcave too, matching its circuit."""

from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.execute("UPDATE zones SET room = 'Batcave' WHERE room = 'John''s Office'")


def downgrade() -> None:
    op.execute("UPDATE zones SET room = 'John''s Office' WHERE room = 'Batcave'")
