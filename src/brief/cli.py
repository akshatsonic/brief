from __future__ import annotations

import asyncio
import os
import re
import shutil
import sqlite3
from datetime import date
from pathlib import Path

import feedparser
import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from brief import __version__
from brief.config import AppConfig, ConfigurationError, FetcherType, SourceConfig, load_config
from brief.fetching import SafeFetcher
from brief.persistence import Database
from brief.scheduling import serve as serve_scheduler
from brief.service import BuildError, NewspaperService
from brief.sources import adapter_for

app = typer.Typer(
    name="brief",
    help="Turn your sources into an LLM-edited daily PDF magazine.",
    no_args_is_help=True,
)
source_app = typer.Typer(help="Add, inspect, and test newspaper sources.", no_args_is_help=True)
app.add_typer(source_app, name="source")
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"brief {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=version_callback, is_eager=True, help="Show the version."
    ),
) -> None:
    """Build and deliver a curated newspaper from feeds and websites."""


@app.command("init")
def initialize(
    config: Path = typer.Option(Path("brief.yaml"), "--config", "-c"),
    force: bool = typer.Option(False, "--force", help="Replace an existing configuration."),
) -> None:
    """Interactively create configuration and state directories."""
    if config.exists() and not force:
        _fail(f"configuration already exists: {config}; pass --force to replace it")
    raw = {
        "publication": {
            "name": typer.prompt("Newspaper name", default="The Brief"),
            "timezone": typer.prompt("Timezone", default="UTC"),
            "schedule": typer.prompt("Daily cron schedule", default="0 7 * * *"),
            "max_articles": 20,
        },
        "sources": [],
        "editorial": {"deduplicate": True, "max_age_hours": 36, "categories": []},
        "output": {"format": "pdf", "theme": "magazine", "directory": "./output"},
        "llm": {
            "enabled": True,
            "backend": "codex-api",
            "model": "gpt-6-astra",
            "api_key_env": "OPENAI_API_KEY",
        },
        "delivery": {"provider": "local"},
    }
    try:
        AppConfig.model_validate(raw)
    except ValidationError as error:
        _fail(f"invalid setup: {error}")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    loaded = load_config(config)
    loaded.output.directory.mkdir(parents=True, exist_ok=True)
    loaded.database.path.parent.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]Created[/green] {config}")
    console.print("Add a source with: [bold]brief source add <url>[/bold]")


@source_app.command("add")
def source_add(
    url: str = typer.Argument(..., help="RSS, Atom, or website listing URL."),
    config: Path = typer.Option(Path("brief.yaml"), "--config", "-c"),
) -> None:
    """Detect and add an RSS feed or website source."""
    loaded = _load(config)
    source_id = typer.prompt("Source ID", default=_source_id(url))
    name = typer.prompt("Source name", default=source_id.replace("-", " ").title())

    async def detect() -> bool:
        temporary = SourceConfig(id=source_id, name=name, type="rss", url=url, request_delay_seconds=0)
        response = await SafeFetcher(loaded.network).fetch(url, temporary)
        return bool(feedparser.parse(response.body).entries)

    try:
        is_feed = asyncio.run(detect())
    except Exception as error:
        _fail(f"could not inspect source: {error}")
    source: dict = {
        "id": source_id,
        "name": name,
        "type": "rss" if is_feed else "website",
        "url": url,
        "category": typer.prompt("Category", default="uncategorized"),
    }
    if not is_feed:
        source["discovery"] = {"article_links": typer.prompt("Article link CSS selector", default="article h2 a")}
        if typer.confirm("Does this site require JavaScript rendering?", default=False):
            source["fetcher"] = "browser"
        content = typer.prompt("Article content CSS selector (blank for automatic)", default="")
        title = typer.prompt("Article title CSS selector", default="h1")
        source["extraction"] = {key: value for key, value in {"title": title, "content": content}.items() if value}
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    raw.setdefault("sources", []).append(source)
    try:
        AppConfig.model_validate(raw)
    except ValidationError as error:
        _fail(f"source is invalid: {error}")
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    console.print(f"[green]Added[/green] {source_id} ({source['type']})")


@source_app.command("list")
def source_list(config: Path = typer.Option(Path("brief.yaml"), "--config", "-c")) -> None:
    """List configured sources."""
    loaded = _load(config)
    table = Table("ID", "Name", "Type", "Fetcher", "Category", "Enabled")
    for source in loaded.sources:
        table.add_row(
            source.id,
            source.name,
            source.type.value,
            source.fetcher.value,
            source.category or "—",
            "yes" if source.enabled else "no",
        )
    console.print(table)


@source_app.command("test")
def source_test(
    source_id: str = typer.Argument(..., help="Configured source identifier."),
    config: Path = typer.Option(Path("brief.yaml"), "--config", "-c"),
    limit: int = typer.Option(3, min=1, max=10, help="Number of sample articles."),
) -> None:
    """Discover and extract sample articles with diagnostics."""
    loaded = _load(config)
    source = next((candidate for candidate in loaded.sources if candidate.id == source_id), None)
    if source is None:
        _fail(f"unknown source: {source_id}")

    async def run() -> None:
        adapter = adapter_for(source, SafeFetcher(loaded.network))
        items = await adapter.discover()
        console.print(f"Discovered [bold]{len(items)}[/bold] candidate articles")
        table = Table("Title", "Words", "Published", "URL")
        for item in items[:limit]:
            try:
                article = await adapter.extract(item)
                table.add_row(
                    article.title,
                    str(len(article.content_text.split())),
                    article.published_at.isoformat() if article.published_at else "unknown",
                    article.url,
                )
            except Exception as error:
                table.add_row(item.title or "unknown", "error", type(error).__name__, str(error))
        console.print(table)

    try:
        asyncio.run(run())
    except Exception as error:
        _fail(f"source test failed: {type(error).__name__}: {error}")


@app.command()
def build(
    config: Path = typer.Option(Path("brief.yaml"), "--config", "-c"),
    publication_date: str | None = typer.Option(None, "--date", help="Edition date (YYYY-MM-DD)."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Discover and filter without calling OpenAI or writing files."
    ),
    codex_cli: bool = typer.Option(False, "--codex-cli", help="Run the editorial pass through local `codex exec`."),
    codex_api: bool = typer.Option(
        False, "--codex-api", help="Run the editorial pass through the OpenAI Responses API."
    ),
) -> None:
    """Build an LLM-edited PDF magazine without delivering it."""
    loaded = _load(config)
    if codex_cli and codex_api:
        _fail("choose only one editorial backend: --codex-cli or --codex-api")
    editorial_backend = "codex-cli" if codex_cli else "codex-api" if codex_api else loaded.llm.backend
    target_date = None
    if publication_date:
        try:
            target_date = date.fromisoformat(publication_date)
        except ValueError:
            _fail("--date must use YYYY-MM-DD format")
    try:
        with console.status("Discovering and curating articles…"):
            result = asyncio.run(
                NewspaperService(loaded, editorial_backend=editorial_backend).build(target_date, dry_run=dry_run)
            )
    except BuildError as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"build failed: {type(error).__name__}: {error}")
    console.print(f"Discovered [bold]{result.discovered_count}[/bold]; selected [bold]{result.selected_count}[/bold].")
    if not dry_run:
        console.print(f"Editorial backend: [bold]{editorial_backend}[/bold]")
    if result.artifact:
        console.print(f"[green]Built[/green] {result.artifact}")
        if result.normalized_articles:
            console.print(f"[green]Scraped articles[/green] {result.normalized_articles}")
        if result.final_articles:
            console.print(f"[green]Final articles[/green] {result.final_articles}")
    elif dry_run:
        console.print("[yellow]Dry run:[/yellow] OpenAI was not called and no database or files were written.")
    for diagnostic in result.diagnostics:
        console.print(f"[yellow]Warning:[/yellow] {diagnostic}")


@app.command()
def publish(
    now: bool = typer.Option(False, "--now", help="Publish the current edition immediately."),
    config: Path = typer.Option(Path("brief.yaml"), "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Discover and select without building or sending."),
) -> None:
    """Build and deliver an edition now."""
    if not now:
        _fail("publish requires --now; use `serve` for scheduled publishing")
    loaded = _load(config)
    try:
        with console.status("Building and publishing…"):
            result, delivery = asyncio.run(NewspaperService(loaded).publish(dry_run=dry_run))
    except Exception as error:
        _fail(f"publish failed: {type(error).__name__}: {error}")
    if dry_run:
        console.print(
            f"[yellow]Dry run:[/yellow] discovered {result.discovered_count}, "
            f"selected {result.selected_count}; nothing was written or sent."
        )
    elif delivery is None:
        console.print("[yellow]Skipped:[/yellow] this edition was already delivered successfully.")
    else:
        console.print(f"[green]Published:[/green] {delivery.message}")


@app.command()
def runs(
    config: Path = typer.Option(Path("brief.yaml"), "--config", "-c"),
    limit: int = typer.Option(20, min=1, max=200),
) -> None:
    """Show recent publishing and build executions."""
    loaded = _load(config)
    database = Database(loaded.database.path)
    database.migrate()
    table = Table("Started", "Kind", "Status", "Error")
    for row in database.recent_runs(limit):
        table.add_row(row["started_at"], row["kind"], row["status"], row["error_summary"] or "—")
    console.print(table)


@app.command()
def serve(
    config: Path = typer.Option(Path("brief.yaml"), "--config", "-c"),
) -> None:
    """Run the foreground scheduler for Docker or systemd."""
    loaded = _load(config)
    console.print(
        f"Scheduling [bold]{loaded.publication.name}[/bold] at "
        f"[bold]{loaded.publication.schedule}[/bold] ({loaded.publication.timezone})."
    )
    console.print("Keep this process running; press Ctrl-C to stop.")
    try:
        serve_scheduler(loaded)
    except Exception as error:
        _fail(f"scheduler stopped: {type(error).__name__}: {error}")


@app.command()
def doctor(
    config: Path = typer.Option(Path("brief.yaml"), "--config", "-c"),
    skip_network: bool = typer.Option(False, "--skip-network", help="Skip source connectivity checks."),
) -> None:
    """Validate configuration, database, output, browser, and delivery settings."""
    loaded = _load(config)
    checks: list[tuple[str, bool, str]] = [("Configuration", True, loaded.publication.name)]
    try:
        Database(loaded.database.path).migrate()
        with sqlite3.connect(loaded.database.path) as connection:
            connection.execute("SELECT 1")
        checks.append(("Database", True, str(loaded.database.path)))
    except Exception as error:
        checks.append(("Database", False, str(error)))
    try:
        loaded.output.directory.mkdir(parents=True, exist_ok=True)
        checks.append(("Output", os.access(loaded.output.directory, os.W_OK), str(loaded.output.directory)))
    except OSError as error:
        checks.append(("Output", False, str(error)))
    if loaded.output.template_directory is not None:
        template_directory = loaded.output.template_directory
        checks.append(
            (
                "Templates",
                template_directory.is_dir(),
                str(template_directory) if template_directory.is_dir() else "directory does not exist",
            )
        )
    if any(source.fetcher is FetcherType.BROWSER for source in loaded.sources):
        checks.append(("Browser", True, "configured; run `scrapling install` before first use"))
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            chromium_path = Path(os.getenv("BRIEF_CHROMIUM_EXECUTABLE") or playwright.chromium.executable_path)
        checks.append(
            (
                "PDF browser",
                chromium_path.is_file(),
                str(chromium_path) if chromium_path.is_file() else "missing; run `uv run scrapling install`",
            )
        )
    except Exception as error:
        checks.append(("PDF browser", False, str(error)))
    if loaded.llm.enabled:
        if loaded.llm.backend == "codex-cli":
            codex_path = shutil.which(loaded.llm.codex_command)
            checks.append(("Codex CLI", bool(codex_path), codex_path or "command not found"))
        else:
            checks.append(
                (
                    "OpenAI",
                    bool(os.getenv(loaded.llm.api_key_env)),
                    f"{loaded.llm.api_key_env} is configured"
                    if os.getenv(loaded.llm.api_key_env)
                    else f"missing {loaded.llm.api_key_env}",
                )
            )
    if loaded.delivery.provider == "kindle":
        required = ["BRIEF_SMTP_HOST", "BRIEF_SMTP_USERNAME", "BRIEF_SMTP_PASSWORD"]
        missing = [name for name in required if not os.getenv(name)]
        checks.append(("SMTP", not missing, "missing: " + ", ".join(missing) if missing else "configured"))
    if not skip_network:

        async def check_sources() -> list[tuple[str, bool, str]]:
            fetcher = SafeFetcher(loaded.network)
            results = []
            for source in loaded.sources:
                if not source.enabled:
                    continue
                try:
                    response = await fetcher.fetch(source.url, source)
                    results.append((f"Source: {source.id}", True, f"HTTP {response.status}"))
                except Exception as error:
                    results.append((f"Source: {source.id}", False, str(error)))
            return results

        checks.extend(asyncio.run(check_sources()))
    table = Table("Check", "Status", "Details")
    for name, ok, details in checks:
        table.add_row(name, "[green]OK[/green]" if ok else "[red]FAIL[/red]", details)
    console.print(table)
    if not all(ok for _, ok, _ in checks):
        raise typer.Exit(1)


def _load(path: Path) -> AppConfig:
    try:
        return load_config(path)
    except ConfigurationError as error:
        _fail(f"configuration error: {error}")


def _source_id(url: str) -> str:
    host = url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    value = "-".join(part for part in host.split(".") if part not in {"www", "com", "org", "net"})
    return (re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-") or "source")[:64]


def _fail(message: str) -> None:
    console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
