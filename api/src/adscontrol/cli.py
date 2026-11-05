"""Command line: migrate, serve, refoss."""

import asyncio
from pathlib import Path

import typer
import uvicorn
import yaml
from sqlalchemy import text

from adscontrol.app import jobs_allowed  # noqa: F401 - re-exported for the CLI's users
from adscontrol.auth import set_pin
from adscontrol.config import get_settings
from adscontrol.db.engine import create_engine, make_session_factory
from adscontrol.db.migrate import upgrade_head
from adscontrol.maintenance.repo import import_tasks
from adscontrol.nest.sdm import (
    NestError,
    SdmClient,
    authorization_url,
    code_from_pasted,
    exchange_code,
)
from adscontrol.nest.thermostat import pair_thermostat
from adscontrol.refoss.client import RefossClient, discover_uuid
from adscontrol.refoss.watch import watch

app = typer.Typer(no_args_is_help=True)
refoss = typer.Typer(no_args_is_help=True, help="The Refoss energy monitor.")
app.add_typer(refoss, name="refoss")


@refoss.command("read")
def refoss_read() -> None:
    """Read every channel once and print it."""

    async def run() -> None:
        host = get_settings().refoss_host
        for r in await RefossClient(host, await discover_uuid(host)).read_channels():
            typer.echo(f"{r.channel:>2}  {r.power_w:>8.1f} W  {r.voltage_v:>6.1f} V")

    asyncio.run(run())


@refoss.command("watch")
def refoss_watch(channel: int = typer.Option(..., help="Channel number, 1 to 18.")) -> None:
    """Follow one channel and the incoming total while you run a load. Ctrl-C to stop."""

    async def run() -> None:
        host = get_settings().refoss_host
        client = RefossClient(host, await discover_uuid(host))
        await watch(client, channel, typer.echo)

    asyncio.run(run())


zone = typer.Typer(no_args_is_help=True, help="The zones on the house picture.")
app.add_typer(zone, name="zone")


@zone.command("set")
def zone_set(
    name: str,
    multiplier: float | None = typer.Option(None, help="Correction for a 240 V one-clamp load."),
    pin: str | None = typer.Option(None, help="Position on the picture as X,Y percent."),
) -> None:
    """Change a zone's multiplier or pin."""
    if multiplier is not None and multiplier <= 0:
        raise typer.BadParameter("multiplier must be above 0")
    x, y = (float(v) for v in pin.split(",")) if pin else (None, None)

    async def run() -> int:
        engine = create_engine(get_settings().database_url)
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE zones SET multiplier = COALESCE(:m, multiplier), pin_x = COALESCE(:x, pin_x), pin_y = COALESCE(:y, pin_y) WHERE name = :name"
                ),
                {"m": multiplier, "x": x, "y": y, "name": name},
            )
        await engine.dispose()
        return result.rowcount

    if asyncio.run(run()) == 0:
        raise typer.BadParameter(f"no zone named {name!r}")


maintenance = typer.Typer(no_args_is_help=True, help="The maintenance list.")
app.add_typer(maintenance, name="maintenance")


@maintenance.command("import")
def maintenance_import(path: Path) -> None:
    """Add tasks and history from a YAML file. Safe to repeat; never overwrites."""

    async def run() -> dict[str, int]:
        engine = create_engine(get_settings().database_url)
        async with make_session_factory(engine)() as session:
            counts = await import_tasks(session, yaml.safe_load(path.read_text()))
            await session.commit()
        await engine.dispose()
        return counts

    typer.echo(asyncio.run(run()))


pin = typer.Typer(no_args_is_help=True, help="The household PIN.")
app.add_typer(pin, name="pin")


@pin.command("set")
def pin_set() -> None:
    """Set or change the PIN, 6 to 12 digits. Changing it signs every device out."""
    value = typer.prompt("New PIN", hide_input=True, confirmation_prompt=True)

    async def run() -> None:
        engine = create_engine(get_settings().database_url)
        async with make_session_factory(engine)() as session:
            await set_pin(session, value)
            await session.commit()
        await engine.dispose()

    try:
        asyncio.run(run())
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo("PIN set.")


nest = typer.Typer(no_args_is_help=True, help="The Nest thermostats.")
app.add_typer(nest, name="nest")


def _sdm_client() -> SdmClient:
    settings = get_settings()
    if not (settings.google_client_id and settings.sdm_project_id):
        raise typer.BadParameter(
            "set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and SDM_PROJECT_ID in .env"
        )
    return SdmClient(
        settings.google_client_id,
        settings.google_client_secret.get_secret_value(),
        settings.sdm_project_id,
        settings.nest_token_path,
    )


@nest.command("login")
def nest_login() -> None:
    """Link your Google account. Choose your thermostats and cameras on Google's screen."""
    settings = get_settings()
    client = _sdm_client()
    typer.echo(
        "Open this in a private browser window, signed in to the account with your devices:\n"
    )
    typer.echo(authorization_url(settings.sdm_project_id, settings.google_client_id))
    typer.echo("\nAfter you allow access you land on google.com. Copy that whole address.")
    pasted = typer.prompt("Paste it here", hide_input=True)

    async def run() -> None:
        await exchange_code(
            settings.google_client_id,
            settings.google_client_secret.get_secret_value(),
            code_from_pasted(pasted),
            settings.nest_token_path,
        )
        for t in await client.list_thermostats():
            typer.echo(f"Found {t.name}: {t.mode}, {t.hvac_status}, online={t.online}")

    try:
        asyncio.run(run())
    except NestError as exc:
        typer.echo(f"Failed: {exc}", err=True)
        raise typer.Exit(1) from exc


@nest.command("list")
def nest_list() -> None:
    """Show what each thermostat reports right now."""
    try:
        for t in asyncio.run(_sdm_client().list_thermostats()):
            typer.echo(t)
    except NestError as exc:
        typer.echo(f"Failed: {exc}", err=True)
        raise typer.Exit(1) from exc


@nest.command("pair")
def nest_pair(thermostat: str, zone: str) -> None:
    """Connect a thermostat to its A/C zone."""

    async def run() -> None:
        engine = create_engine(get_settings().database_url)
        async with make_session_factory(engine)() as session:
            await pair_thermostat(session, thermostat, zone)
            await session.commit()
        await engine.dispose()

    try:
        asyncio.run(run())
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def migrate() -> None:
    """Create or update the schema."""
    upgrade_head(get_settings().database_url)


@app.command()
def serve(dev: bool = typer.Option(False, help="Reload on code changes.")) -> None:
    """Run the API, the recorder jobs and the built web page."""
    settings = get_settings()
    uvicorn.run(
        "adscontrol.app:create_app",
        factory=True,
        host=settings.bind_host,
        port=settings.port,
        reload=dev,
    )
