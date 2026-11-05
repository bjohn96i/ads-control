# ADS-Control

A self-hosted dashboard for one house: live energy use by circuit, thermostats, cameras, utility
bills and a maintenance list, on one screen. It runs on a computer at home, talks to the devices
on the local network, and keeps its data there.

It was built for a specific house, so some parts assume that house's equipment (listed below).
The code is small and plain enough to adapt.

## What it does

- **Energy**: records every circuit of a Refoss EM16 energy monitor every 10 seconds, ranks
  circuits and rooms by energy and estimated cost, and shows today's use and a live line. Gaps in
  the recording are shown as gaps, never as low use.
- **Unusual use**: flags a circuit that runs well above its usual level for the hour, or creeps up
  over weeks. Flags appear on screen only; there are no notifications.
- **Climate**: Nest thermostat readings next to the A/C circuit's power, an estimate of what one
  degree costs, and setpoint changes behind a household PIN. It never changes a schedule.
- **Cameras**: Nest camera and doorbell events, live video on request (behind the PIN), and public
  traffic cameras from Georgia 511.
- **Bills**: reads Georgia Power PDF bills and compares billed kWh with what was measured.
- **Maintenance**: recurring tasks (every so many days, weeks or months), per-room tracking, a
  phone-friendly page and a JSON backup.
- **Home page**: a cutaway picture of the house with each room's live power, the weather and
  rate period, and summary cards.

## Built for

| Piece | Used for | Notes |
|---|---|---|
| [Refoss EM16](https://refoss.net/) | Circuit power | Read-only over the LAN; nothing is ever switched |
| Google Nest (Device Access) | Thermostats, cameras | Needs a [Device Access](https://developers.google.com/nest/device-access) project (one-time US$5 fee) and a Google Cloud project |
| Georgia Power TOU-OA rates | Cost estimates | Hard-coded in `api/src/adscontrol/rates.py`; change it for another utility |
| [Open-Meteo](https://open-meteo.com/) | Outdoor weather | Free, no key; only a city-level location is sent |
| [Georgia 511](https://511ga.org/) | Traffic cameras | Optional; listed in `data/traffic_cameras.yaml` |
| Lanthorn | Network panel | Optional sister app that reports network traffic |

Stack: Python 3.12 with FastAPI and async SQLAlchemy, TimescaleDB, Alembic; React 19 with Vite and
TanStack Query; plain CSS.

## Getting started

You need Docker (or any TimescaleDB 2.x server), [uv](https://docs.astral.sh/uv/) and Node 20+.

1. **Database.** Create a role and database with the TimescaleDB extension, for example:

   ```bash
   docker run -d --name adscontrol-db -p 5432:5432 -e POSTGRES_PASSWORD=postgres \
     timescale/timescaledb:2.30.2-pg16
   docker exec adscontrol-db psql -U postgres \
     -c "CREATE ROLE adscontrol LOGIN PASSWORD 'adscontrol'" \
     -c "CREATE DATABASE adscontrol OWNER adscontrol"
   docker exec adscontrol-db psql -U postgres -d adscontrol -c "CREATE EXTENSION IF NOT EXISTS timescaledb"
   ```

2. **Configuration.** Copy `.env.example` to `.env` and fill in what applies (see below). At the
   least, set `REFOSS_HOST` and `ALLOWED_HOSTS`.

3. **Run it.**

   ```bash
   cd web && npm install && npm run build && cd ..   # the server serves web/dist
   cd api
   uv sync
   uv run adscontrol migrate
   uv run adscontrol serve        # http://localhost:8100
   ```

   For front-end work, `npm run dev` in `web/` starts Vite on port 5174 and forwards `/api` to the
   server.

## Configuration

Settings come from `.env` (see `.env.example`). The main ones:

| Setting | What it is |
|---|---|
| `DATABASE_URL` | Postgres/TimescaleDB connection |
| `REFOSS_HOST` | The energy monitor's LAN address |
| `ALLOWED_HOSTS` | JSON list of the hostnames this server answers to, such as its LAN IP and `.local` name. Others are refused. Defaults to `["localhost"]` only |
| `HOUSEHOLD` | JSON list of first names for the maintenance page's "who's using this phone" |
| `WEATHER_LAT`, `WEATHER_LON` | Approximate location for the weather (rounded to one decimal before sending) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SDM_PROJECT_ID` | Google Nest Device Access |
| `GOOGLE_PUBSUB_SUBSCRIPTION` | Pub/Sub subscription for camera events |
| `LANTHORN_URL` | Where Lanthorn runs, if you use it |

Circuits are set up as zones in the database migrations (`api/alembic/versions/`). Adjust a zone's
multiplier or its label position on the house picture with:

```bash
cd api
uv run adscontrol refoss read                        # every channel once
uv run adscontrol refoss watch --channel 17          # run the load and watch the numbers move
uv run adscontrol zone set "Water Heater" --multiplier 2
uv run adscontrol zone set "Living Room" --pin 30,55
```

A 240 V load read with one clamp shows half its power; `watch` reports a multiplier near 2 for
these, and `zone set --multiplier 2` corrects past and future readings.

The house picture is `web/public/house.jpg`; label positions are percentages across and down it.

## Google Nest

1. Create a [Device Access](https://console.nest.google.com/device-access) project and a Google
   Cloud OAuth client (Web application, redirect URI `https://www.google.com`).
2. For camera events, create a Pub/Sub topic and a pull subscription, and grant
   `sdm-publisher@googlegroups.com` the Publisher role on the topic.
3. Put the IDs in `.env`, then link your account and pick your devices:

   ```bash
   cd api
   uv run adscontrol nest login     # in your own terminal; it opens Google's consent screen
   uv run adscontrol nest list
   uv run adscontrol nest pair "Upstairs" "Upstairs A/C"   # a thermostat and its A/C circuit's zone
   ```

While the Google Cloud app is in Testing, Google's sign-in expires every 7 days. Publishing it
(Google Auth Platform → Audience) stops that; personal Device Access projects don't need Google's
verification, and the consent screen just shows an "unverified app" warning.

## Running on a Mac

The recorder only captures while the server runs, so a gap is permanent. A launchd service keeps
it running and the Mac awake on mains power:

```bash
cp deploy/mac/org.adscontrol.plist ~/Library/LaunchAgents/     # edit the paths in it first
launchctl load ~/Library/LaunchAgents/org.adscontrol.plist
```

## PIN and HTTPS

Cameras and thermostat changes need a household PIN, and the PIN only works over HTTPS. Caddy
provides a local certificate:

```bash
cd api && uv run adscontrol pin set     # in your own terminal; it asks twice
brew install caddy
cp deploy/mac/org.adscontrol.caddy.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/org.adscontrol.caddy.plist
caddy trust
```

Edit `deploy/Caddyfile` to list your own IP and `.local` name. On each phone, install Caddy's root
certificate (`~/Library/Application Support/Caddy/pki/authorities/local/root.crt`) and, on iPhone,
trust it under Settings > General > About > Certificate Trust Settings. That certificate can vouch
for any site on that phone, so keep the computer's copy of its private key private.

## Security and privacy

- It is meant for a home network and has no user accounts. Anyone on the network can read energy
  and edit the maintenance list; cameras and thermostat changes need the PIN.
- Five wrong PINs lock it for a minute, doubling up to an hour. Changing the PIN signs every device
  out, and the sidebar's **Lock** button signs out one device.
- The server answers only to the hostnames in `ALLOWED_HOSTS`, which blocks DNS-rebinding pages,
  and only trusts a forwarded HTTPS header from Caddy on the same machine.
- Data stays on the home server. What leaves it: requests to Google for Nest data, a city-level
  location to Open-Meteo, and the browser loading Georgia 511 camera pictures and Google Fonts.
- House camera images are never stored. The privacy policy used for Google's consent screen is at
  <https://bjohn96i.github.io/ads-control/privacy.html>.

## Tests

```bash
cd api
uv run pytest -m "not integration"   # no Docker needed
uv run pytest                        # also the database tests (starts a Timescale container)
cd ../web
npm run test:run
```

## License

[MIT](LICENSE). The look follows the MIT-licensed
[PRMGR Observatory starter](https://github.com/prmgr-org/prmgr-observatory-starter).
