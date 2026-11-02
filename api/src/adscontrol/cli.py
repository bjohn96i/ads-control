"""Command line: migrate, serve, refoss."""

import asyncio

import typer
import uvicorn

from adscontrol.config import get_settings
from adscontrol.db.migrate import upgrade_head
from adscontrol.refoss.client import RefossClient, discover_uuid

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
