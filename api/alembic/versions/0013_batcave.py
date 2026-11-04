"""The office circuit's zone is called Batcave, not Basement (the floor's name)."""

from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.execute("UPDATE zones SET name = 'Batcave' WHERE name = 'Basement'")


def downgrade() -> None:
    op.execute("UPDATE zones SET name = 'Basement' WHERE name = 'Batcave'")
