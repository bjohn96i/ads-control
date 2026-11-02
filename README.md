# ADS-Control

The house dashboard: live energy by zone, maintenance, bills, climate and cameras. The sister
app to Lanthorn. It runs on your own hardware and talks to your devices on the LAN.

The look follows the MIT-licensed
[PRMGR Observatory starter](https://github.com/prmgr-org/prmgr-observatory-starter).

## Local development

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 20+, and a TimescaleDB server. It
shares Lanthorn's `lanthorn-db` container, with its own role and database:

```bash
docker exec lanthorn-db psql -U lanthorn -d postgres -c "CREATE ROLE adscontrol LOGIN PASSWORD 'adscontrol'" -c "CREATE DATABASE adscontrol OWNER adscontrol"
docker exec lanthorn-db psql -U lanthorn -d adscontrol -c "CREATE EXTENSION IF NOT EXISTS timescaledb"
cd api
uv sync
uv run adscontrol migrate
uv run adscontrol serve --dev       # http://localhost:8100
```

Tests:

```bash
cd api
uv run pytest -m "not integration"  # no Docker needed
uv run pytest                       # includes database tests (starts a Timescale container)
```
