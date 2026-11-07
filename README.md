# Brief

**Your sources. Your newspaper. Your schedule.**

Brief is a self-hosted, CLI-first personal newspaper engine. It discovers articles from
RSS/Atom feeds and websites, applies deterministic editorial rules, creates a Kindle-friendly
EPUB 3 edition, and optionally submits it to Kindle over SMTP. It has no LLM dependency.

## Run locally

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Git

### 1. Clone and install

```bash
git clone https://github.com/akshatsonic/brief.git
cd brief
uv sync
uv run brief --help
```

`uv sync` creates an isolated `.venv` and installs the locked dependencies. You do not need to
activate the environment when commands are prefixed with `uv run`.

### 2. Create the configuration

Use the interactive setup:

```bash
uv run brief init
```

This creates `brief.yaml`, `output/`, and the local state directory. Alternatively, start from the
example and edit it:

```bash
cp brief.example.yaml brief.yaml
```

At minimum, configure a publication name and one source. Relative output and database paths are
resolved from the directory containing `brief.yaml`.

### 3. Add and test sources

Add an RSS feed or website interactively:

```bash
uv run brief source add https://news.ycombinator.com/rss
uv run brief source list
uv run brief source test hackernews
```

`source add` detects RSS/Atom feeds. For websites it asks for discovery and extraction selectors.
Standard HTTP is used by default.

For a JavaScript-rendered website, install Scrapling's browser once:

```bash
uv run scrapling install
```

Then set that source's `fetcher` to `browser`. Brief does not enable challenge solving or bypass
access controls.

### 4. Check the installation

```bash
uv run brief doctor
```

The doctor checks configuration, database and output access, source connectivity, optional browser
requirements, and SMTP settings when Kindle delivery is enabled. Use `--skip-network` when you only
want local checks.

### 5. Build an edition

First inspect what would be selected without writing anything:

```bash
uv run brief build --dry-run
```

Then generate the EPUB:

```bash
uv run brief build
```

The generated newspaper is written to `output/`, for example:

```text
output/the-morning-brief-2026-11-07.epub
```

SQLite state is stored at `.brief/brief.db` by default. Both locations can be changed in
`brief.yaml`.

Useful commands:

```bash
uv run brief build --date 2026-11-07  # build a specific edition date
uv run brief runs                     # show execution history
uv run brief publish --now            # build and run the configured delivery provider
uv run brief serve                    # run the foreground scheduler
```

`serve` must remain running. Use Docker, systemd, launchd, or another supervisor for unattended
daily publishing.

Once published to PyPI, `pipx install brief` will expose the command without `uv run`. Every command
and subcommand supports `--help`.

## Configuration and usage

Copy [`brief.example.yaml`](brief.example.yaml) for a complete starting point. Paths
are resolved relative to the YAML file. Required fields are publication name and each source's ID,
name, type, and URL. RSS sources support `fetch_article: auto|always|never`. Website selectors are
optional, and pagination occurs only with an explicit next selector and bounded page count.

## Kindle delivery

In Amazon's Personal Document Settings, note your Kindle address and approve the SMTP sender.
Set `delivery.provider: kindle` and `delivery.kindle_email` in YAML (or use
`BRIEF_KINDLE_EMAIL`). Credentials must only be environment variables:

```bash
export BRIEF_SMTP_HOST=smtp.example.com
export BRIEF_SMTP_PORT=587
export BRIEF_SMTP_USERNAME=sender@example.com
export BRIEF_SMTP_PASSWORD='...'
export BRIEF_SMTP_FROM=sender@example.com
export BRIEF_SMTP_SECURITY=starttls  # or ssl
uv run brief publish --now --dry-run
uv run brief publish --now
```

SMTP success means the SMTP server accepted the message, not that Amazon imported it. Successful
submissions are persisted and the same edition/provider is not submitted twice.

## Scheduling and Docker

`serve` is a foreground process for Docker, systemd, or another supervisor. Closing a terminal
stops it. It uses the configured IANA timezone and cron expression, bounded retries, overlap
prevention, and an expiring SQLite lease.

```bash
uv run brief serve
cp brief.docker.yaml brief.yaml
docker compose up --build
```

Compose mounts configuration, `./data`, and `./output`; the Docker example uses absolute container
paths so state survives container replacement.

## EPUB validation

Brief writes EPUB 3 with navigation and NCX compatibility. If
[EPUBCheck](https://www.w3.org/publishing/epubcheck/) is installed:

```bash
epubcheck output/the-morning-brief-2026-11-07.epub
```

## Responsible use

Brief respects robots.txt by default, rejects private/local network targets, applies
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

