"""Moves every table's rows from one ADS-Control database to another, for a change of server.

Row by row with COPY rather than pg_dump/pg_restore: a TimescaleDB restore needs the same
extension version on both sides, and a server move is exactly when they differ.
"""

from datetime import datetime

import psycopg

# Parents before children (foreign keys); alembic_version stays out, both sides are at head.
TABLES = [
    "zones",
    "rate_versions",
    "auth_settings",
    "bills",
    "cameras",
    "thermostats",
    "tasks",
    "task_items",
    "completions",
    "findings",
    "outdoor_readings",
    "thermostat_readings",
    "camera_events",
    "channel_readings",
]
TIME_COLUMN = {
    "channel_readings": "time",
    "thermostat_readings": "time",
    "outdoor_readings": "time",
    "camera_events": "occurred_at",
}
AGGREGATES = ["channel_hourly", "channel_daily"]


def _conninfo(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


async def _columns(conn: psycopg.AsyncConnection, table: str) -> list[str]:
    rows = await conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] for r in await rows.fetchall()]


async def _primary_key(conn: psycopg.AsyncConnection, table: str) -> list[str]:
    rows = await conn.execute(
        "SELECT a.attname FROM pg_index i "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = %s::regclass AND i.indisprimary",
        (table,),
    )
    return [r[0] for r in await rows.fetchall()]


async def _stream(src, dst, table: str, columns: list[str], into: str, since) -> int:
    cols = ", ".join(columns)
    where = f" WHERE {TIME_COLUMN[table]} >= %s" if since and table in TIME_COLUMN else ""
    query = f"COPY (SELECT {cols} FROM {table}{where}) TO STDOUT"
    rows = 0
    async with src.cursor() as out_cur, dst.cursor() as in_cur:
        async with (
            out_cur.copy(query, (since,) if where else None) as out,
            in_cur.copy(f"COPY {into} ({cols}) FROM STDIN") as inp,
        ):
            async for chunk in out:
                await inp.write(chunk)
                rows += bytes(chunk).count(b"\n")
    return rows


async def copy_data(source_url: str, target_url: str, since: datetime | None) -> dict[str, int]:
    """Full copy (since None) replaces the target's rows; with since, it merges the final rows.

    The final pass upserts the small tables rather than emptying them: emptying cameras would
    cascade into camera_events and erase history older than since.
    """
    counts: dict[str, int] = {}
    async with (
        await psycopg.AsyncConnection.connect(_conninfo(source_url)) as src,
        await psycopg.AsyncConnection.connect(_conninfo(target_url)) as dst,
    ):
        if since is None:
            await dst.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
        for table in TABLES:
            columns = await _columns(src, table)
            if since is None:
                counts[table] = await _stream(src, dst, table, columns, table, None)
                continue
            await dst.execute(f"CREATE TEMP TABLE stage (LIKE {table}) ON COMMIT DROP")
            counts[table] = await _stream(src, dst, table, columns, "stage", since)
            cols = ", ".join(columns)
            key = await _primary_key(dst, table)
            if table in TIME_COLUMN:
                action = "DO NOTHING"
            else:
                updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in key)
                action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
            await dst.execute(
                f"INSERT INTO {table} ({cols}) SELECT {cols} FROM stage "
                f"ON CONFLICT ({', '.join(key)}) {action}"
            )
            await dst.execute("DROP TABLE stage")
        # Copied ids came with their values; move each sequence past them.
        sequences = await dst.execute(
            "SELECT s.relname, t.relname, a.attname FROM pg_class s "
            "JOIN pg_depend d ON d.objid = s.oid AND d.deptype = 'a' "
            "JOIN pg_class t ON t.oid = d.refobjid "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid "
            "WHERE s.relkind = 'S' AND t.relnamespace = 'public'::regnamespace"
        )
        for seq, table, column in await sequences.fetchall():
            await dst.execute(
                f"SELECT setval('{seq}', coalesce(max({column}), 1), max({column}) IS NOT NULL) "
                f"FROM {table}"
            )
        await dst.commit()
    # Refreshing an aggregate can't run inside a transaction.
    async with await psycopg.AsyncConnection.connect(_conninfo(target_url), autocommit=True) as dst:
        for view in AGGREGATES:
            await dst.execute(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")
    return counts
