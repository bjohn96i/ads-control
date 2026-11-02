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

## Recording while you work (Mac)

The recorder only captures while the server runs, and a gap is permanent. Install the login
service, which also keeps the Mac awake on mains power:

```bash
cp deploy/mac/org.adscontrol.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/org.adscontrol.plist
launchctl list | grep adscontrol
```

To remove it, run `launchctl unload` on the same file and delete it.

## Checking the panel

```bash
cd api
uv run adscontrol refoss read                 # every channel once
uv run adscontrol refoss watch --channel 17   # run the load, watch both numbers move
uv run adscontrol zone set "Water Heater" --multiplier 2
uv run adscontrol zone set "Living Room" --pin 30,55
```

The multiplier shown is the change on the incoming lines divided by the change on the channel.
About 1 means the clamp sees the whole load. About 2 means a 240 V load is being read from one
leg, and the zone needs `--multiplier 2`.
