"""Command line: migrate, serve."""

import typer
import uvicorn

from adscontrol.config import get_settings
from adscontrol.db.migrate import upgrade_head

app = typer.Typer(no_args_is_help=True)


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
