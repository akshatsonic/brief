# Daily Signal

**Your sources. Your newspaper. Your schedule.**

Daily Signal is a self-hosted, CLI-first personal newspaper engine. It discovers articles from
RSS/Atom feeds and websites, applies deterministic editorial rules, creates a Kindle-friendly
EPUB 3 edition, and optionally submits it to Kindle over SMTP. It has no LLM dependency.

## Requirements and installation

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Optional: Scrapling's browser for JavaScript-rendered sources

```bash
git clone <your-fork-url> brief
cd brief
uv sync --extra dev
uv run daily-signal init
uv run daily-signal source add https://news.ycombinator.com/rss
uv run daily-signal source list
uv run daily-signal build --dry-run
uv run daily-signal build
```

Once published to PyPI, `pipx install daily-signal` exposes the same command. Every command has
`--help`. For JavaScript sources, run `uv run scrapling install`, then explicitly configure
`fetcher: browser`. HTTP remains the default; Daily Signal never enables challenge solving.

## Configuration and usage

Copy [`daily-signal.example.yaml`](daily-signal.example.yaml) for a complete starting point. Paths
are resolved relative to the YAML file. Required fields are publication name and each source's ID,
name, type, and URL. RSS sources support `fetch_article: auto|always|never`. Website selectors are
optional, and pagination occurs only with an explicit next selector and bounded page count.

```bash
uv run daily-signal source test hackernews
uv run daily-signal build --date 2026-11-07
uv run daily-signal runs
uv run daily-signal doctor
```

## Kindle delivery

In Amazon's Personal Document Settings, note your Kindle address and approve the SMTP sender.
Set `delivery.provider: kindle` and `delivery.kindle_email` in YAML (or use
`DAILY_SIGNAL_KINDLE_EMAIL`). Credentials must only be environment variables:

```bash
export DAILY_SIGNAL_SMTP_HOST=smtp.example.com
export DAILY_SIGNAL_SMTP_PORT=587
export DAILY_SIGNAL_SMTP_USERNAME=sender@example.com
export DAILY_SIGNAL_SMTP_PASSWORD='...'
export DAILY_SIGNAL_SMTP_FROM=sender@example.com
export DAILY_SIGNAL_SMTP_SECURITY=starttls  # or ssl
uv run daily-signal publish --now --dry-run
uv run daily-signal publish --now
```

SMTP success means the SMTP server accepted the message, not that Amazon imported it. Successful
submissions are persisted and the same edition/provider is not submitted twice.

## Scheduling and Docker

`serve` is a foreground process for Docker, systemd, or another supervisor. Closing a terminal
stops it. It uses the configured IANA timezone and cron expression, bounded retries, overlap
prevention, and an expiring SQLite lease.

```bash
uv run daily-signal serve
cp daily-signal.docker.yaml daily-signal.yaml
docker compose up --build
```

Compose mounts configuration, `./data`, and `./output`; the Docker example uses absolute container
paths so state survives container replacement.

## EPUB validation

Daily Signal writes EPUB 3 with navigation and NCX compatibility. If
[EPUBCheck](https://www.w3.org/publishing/epubcheck/) is installed:

```bash
epubcheck output/the-morning-brief-2026-11-07.epub
```

## Responsible use

Daily Signal respects robots.txt by default, rejects private/local network targets, applies
timeouts and size limits, sanitizes article HTML, and does not execute scraped scripts. It does
not bypass paywalls, authentication, robots rules, or anti-bot challenges.

Public accessibility does not grant republication rights. Users are responsible for source terms,
copyright, licensing, and permitted use. Attribution and original links are always retained.

## Development

```bash
uv sync --extra dev
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv build
```

Tests use local fixtures and mocked SMTP; they do not contact live sites or send email. See
[`docs/architecture.md`](docs/architecture.md), [`docs/troubleshooting.md`](docs/troubleshooting.md),
and [`CONTRIBUTING.md`](CONTRIBUTING.md). Licensed under the MIT License.

