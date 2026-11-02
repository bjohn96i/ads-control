"""Maintenance tasks, per-room items and completions."""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tasks (
            id serial PRIMARY KEY,
            name text NOT NULL UNIQUE,
            category text NOT NULL,
            notes text NOT NULL DEFAULT '',
            interval_months integer CHECK (interval_months > 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE task_items (
            id serial PRIMARY KEY,
            task_id integer NOT NULL REFERENCES tasks ON DELETE CASCADE,
            name text NOT NULL,
            UNIQUE (task_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE completions (
            id serial PRIMARY KEY,
            task_id integer NOT NULL REFERENCES tasks ON DELETE CASCADE,
            item_id integer REFERENCES task_items ON DELETE CASCADE,
            done_on date NOT NULL,
            precision text NOT NULL DEFAULT 'day' CHECK (precision IN ('day', 'month', 'mid_month')),
            who text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX completions_once ON completions (task_id, COALESCE(item_id, 0), done_on)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE completions")
    op.execute("DROP TABLE task_items")
    op.execute("DROP TABLE tasks")
