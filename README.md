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

## Maintenance

Open `http://<this-mac's-address>:8100/maintenance` on a phone on the home Wi-Fi. There is no login:
anyone on the network can read energy and change the maintenance list. Cameras and thermostat
changes need the PIN, which only works over HTTPS.

```bash
cd api
uv run adscontrol maintenance import ../data/maintenance_seed.yaml   # adds what is missing, safe to repeat
curl -s localhost:8100/api/maintenance/export > ../data/maintenance-backup.json
```

## PIN and HTTPS

```bash
cd api && uv run adscontrol pin set                # run in your own terminal; it asks twice
brew install caddy
cp deploy/mac/org.adscontrol.caddy.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/org.adscontrol.caddy.plist
caddy trust                                        # asks for your Mac password
```

Add a Local DNS record on the Pi-hole: `control.home.arpa` pointing at this Mac's address. On each
phone, install Caddy's root certificate from
`~/Library/Application Support/Caddy/pki/authorities/local/root.crt` and, on iPhone, turn it on
under Settings > General > About > Certificate Trust Settings. That certificate lets its holder
vouch for any site on that phone, so keep the Mac's copy of its private key private.

Five wrong PINs lock it for a minute, doubling up to an hour, for everyone. Changing the PIN signs
every device out. For local development without HTTPS, set `ALLOW_INSECURE_PIN=true`.

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
