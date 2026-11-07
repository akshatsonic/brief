from pathlib import Path

import typer
from rich.console import Console

from daily_signal import __version__
from daily_signal.config import ConfigurationError, load_config

app = typer.Typer(
    name="daily-signal",
    help="Turn your sources into a personal daily EPUB newspaper.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"daily-signal {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=version_callback, is_eager=True, help="Show the version."
    ),
) -> None:
    """Build and deliver a curated newspaper from feeds and websites."""


@app.command()
def doctor(
    config: Path = typer.Option(Path("daily-signal.yaml"), "--config", "-c"),
) -> None:
    """Validate configuration and installation prerequisites."""
    try:
        loaded = load_config(config)
    except ConfigurationError as error:
        console.print(f"[red]Configuration error:[/red] {error}")
        raise typer.Exit(1) from error
    console.print(f"[green]Configuration valid:[/green] {loaded.publication.name}")


if __name__ == "__main__":
    app()

