# Brief

**Your sources. Your newspaper. Your schedule.**

Brief turns RSS feeds and websites into a curated daily PDF magazine for Kindle. It normalizes
scraped articles, uses an LLM editor to deduplicate, categorize, summarize, and select stories, then
produces a Kindle-sized PDF with source links, key points, and watchouts. The editorial pass can use
the OpenAI Responses API or a locally authenticated Codex CLI.

## Quickstart

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Git.

```bash
git clone https://github.com/akshatsonic/brief.git
cd brief
uv sync
uv run brief --help
```

Install the Chromium browser used for PDF rendering. This is separate from installing the Python
package:

```bash
uv run scrapling install
```

Initialize a local config, then add at least one source:

```bash
uv run brief init
uv run brief source add https://news.ycombinator.com/rss
uv run brief source list
uv run brief source test hackernews
```

`source add` detects RSS/Atom feeds. For a website, it asks for discovery and extraction selectors.
Use HTTP fetching by default. Set a website source's `fetcher: browser` only when it needs
JavaScript rendering.

Choose and authenticate an editorial backend:

```bash
# OpenAI Responses API
export OPENAI_API_KEY='your-api-key'
uv run brief build --codex-api

# Or local Codex CLI authentication; this does not require OPENAI_API_KEY
codex login status
uv run brief build --codex-cli
```

The build writes to `output/` by default:

```text
the-brief-YYYY-MM-DD.pdf
the-brief-YYYY-MM-DD.scraped.json
the-brief-YYYY-MM-DD.articles.json
```

The `.scraped.json` file contains normalized scraper results before editorial selection. The
`.articles.json` file is the final list used to render the PDF. Its fixed fields are `id`, optional
`image`, `heading`, `text_summary`, `source_url`, `genre`, `watchouts`, and `important_points`.
Binary image data is excluded from both JSON files; supported images are embedded in the PDF.

Use `--date YYYY-MM-DD` for a dated edition. Use `--dry-run` to inspect discovery and deterministic
filtering before the LLM call; dry runs do not call the model or write files.

## Editorial layer

Brief uses OpenAI Structured Outputs with a strict JSON Schema derived from Pydantic models. The
model is prompted to write as a careful newspaper editor, use only scraped facts, deduplicate
stories about the same event, and flag material uncertainty. Brief verifies each returned article
ID and restores its source and image URLs from trusted scraper records. The model cannot select
unknown IDs or replace URLs.

The built-in genres are World, Politics & Policy, Business & Economy, Technology, Science, Health,
Climate & Environment, Culture, Sports, and Other. If `editorial.categories` is non-empty, it is
applied to those genre labels after the model returns its selection. Leave it empty to allow all
genres.

The default `brief.example.yaml` selects `codex-api`, model `gpt-6-astra`. For the local CLI backend,
set `llm.backend: codex-cli`; it runs `codex exec` with schema-constrained output in an ephemeral,
read-only temporary directory. `llm.codex_model` optionally pins the Codex model. If omitted,
Codex uses the model in your local Codex settings. To choose another backend for one build, pass
`--codex-api` or `--codex-cli`; they are mutually exclusive.

## Configuration

`brief init` creates `brief.yaml`, the output directory, and the state directory. It starts with no
sources, so add one before a full build. To configure manually, copy
[`brief.example.yaml`](brief.example.yaml):

```bash
cp brief.example.yaml brief.yaml
```

Relative paths resolve from the directory containing the config file. A source requires `id`,
`name`, `type`, and `url`. Website discovery/extraction selectors are optional. Pagination is used
only when explicitly configured and is bounded by `max_pages`.

Important settings:

```yaml
publication:
  name: The Brief
  timezone: Asia/Kolkata
  schedule: "0 7 * * *"
  max_articles: 20

editorial:
  max_age_hours: 36
  min_content_words: 40
  categories: []

output:
  format: pdf
  theme: magazine
  directory: ./output
  include_images: true
  max_image_mb: 5
  # template_directory: ./themes/my-magazine

llm:
  enabled: true
  backend: codex-api # codex-api or codex-cli
  model: gpt-6-astra
  api_key_env: OPENAI_API_KEY
  timeout_seconds: 120
  max_input_articles: 60
  codex_command: codex
  codex_model: gpt-6-luna
```

Secrets never belong in YAML. The OpenAI API key comes from the environment variable named by
`llm.api_key_env`. The Codex CLI backend uses the account already authenticated by `codex login`.

## Magazine design

The built-in template creates a 6 × 9 inch PDF, with one feature story per page, an optional image,
a large heading, summary, key points, watchouts, and a source link. The layout uses 27pt headings
and 16pt summaries. Kindle renders fixed PDFs differently across devices; test the result in Kindle
Previewer and on your target device.

To customize it, set `output.template_directory`. Copy the built-in template and stylesheet:

```bash
mkdir -p themes/my-magazine
cp src/brief/templates/magazine.html themes/my-magazine/
cp src/brief/templates/magazine-pdf.css themes/my-magazine/style.css
```

The custom `magazine.html` receives `edition`, `article_images`, and `css`; `style.css` replaces the
built-in print stylesheet. Keep the 6 × 9 inch page size and make image output conditional. See
[`docs/themes.md`](docs/themes.md) for details.

## Useful commands

```bash
uv run brief doctor                 # check config, Chromium, backend auth, and settings
uv run brief build --dry-run        # discover and filter without an LLM call
uv run brief build --codex-cli      # curate with local Codex CLI and make the PDF
uv run brief build --codex-api      # curate with OpenAI API and make the PDF
uv run brief build --date 2026-11-07
uv run brief publish --now --dry-run
uv run brief publish --now
uv run brief runs
uv run brief serve
```

Every command supports `--help`. `serve` is a foreground scheduler. It must keep running under
Docker, systemd, launchd, or another supervisor for unattended publishing. Scheduled runs use
`llm.backend` from the config; CLI flags only override one manual `build` command.

## Kindle delivery

In Amazon's Personal Document Settings, approve the sender address and note the Kindle email
address. Set `delivery.provider: kindle` and `delivery.kindle_email` in YAML. Credentials must come
from environment variables:

```bash
export BRIEF_SMTP_HOST=smtp.example.com
export BRIEF_SMTP_PORT=587
export BRIEF_SMTP_USERNAME=sender@example.com
export BRIEF_SMTP_PASSWORD='...'
export BRIEF_SMTP_FROM=sender@example.com
export BRIEF_SMTP_SECURITY=starttls # or ssl
uv run brief publish --now --dry-run
uv run brief publish --now
```

`BRIEF_KINDLE_EMAIL` can override the configured recipient. SMTP acceptance confirms submission to
the mail server, not import into the Kindle library. Successful edition/provider deliveries are
stored in SQLite to prevent duplicate submissions.

## Docker

The supplied Compose setup mounts config, persistent SQLite data, and output. Start it with:

```bash
cp brief.docker.yaml brief.yaml
docker compose up --build
```

Set the chosen LLM credentials in the environment for the Compose service. For API mode, provide
`OPENAI_API_KEY`; for Codex CLI mode, arrange Codex CLI installation and authentication in the
container before relying on scheduled runs. The Docker image installs Scrapling's browser during
build for Chromium based PDF output.

## Diagnostics and troubleshooting

```bash
uv run brief doctor
uv run brief doctor --skip-network
uv run brief source test <source-id>
```

If PDF browser validation fails, run `uv run scrapling install`. If a build returns no eligible
stories, inspect the `.scraped.json` sidecar and check source extraction, age/content filters, and
`editorial.categories`. If the API backend reports a missing key, export the variable configured
in `llm.api_key_env`. For Codex CLI failures, run `codex login status` and `codex exec --help`.
Additional notes are in [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Responsible use

Brief respects robots.txt by default, rejects private/local network destinations, applies timeouts
and response size limits, sanitizes extracted HTML, and does not execute scraped scripts. It does
not bypass paywalls, authentication, robots rules, or anti-bot challenges.

When LLM editing is enabled, selected article text is sent to the configured OpenAI or Codex
backend. Review source terms and data handling requirements before enabling it. Public
accessibility does not grant republication rights; users are responsible for copyright, licensing,
and permitted use. Source attribution and original links are retained.

## Development

```bash
uv sync --extra dev
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv build
```

Tests use local fixtures, mocked LLM transports, a fake PDF writer, and mocked SMTP; they do not
contact live sites or model services. See [`docs/architecture.md`](docs/architecture.md),
[`docs/troubleshooting.md`](docs/troubleshooting.md), and [`CONTRIBUTING.md`](CONTRIBUTING.md).
Licensed under the MIT License.
