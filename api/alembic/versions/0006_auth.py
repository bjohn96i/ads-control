"""The shared household PIN: one row, holding its hash and the failed-attempt state."""

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth_settings (
            id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            pin_hash bytea NOT NULL,
            pin_salt bytea NOT NULL,
            signing_key bytea NOT NULL,
            generation integer NOT NULL,
            failures integer NOT NULL DEFAULT 0,
            locked_until timestamptz
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE auth_settings")
