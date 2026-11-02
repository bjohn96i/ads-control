"""Command line: migrate, serve, refoss."""

import asyncio

import typer
import uvicorn
from sqlalchemy import text

from adscontrol.config import get_settings
from adscontrol.db.engine import create_engine
from adscontrol.db.migrate import upgrade_head
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
