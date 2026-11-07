# Troubleshooting

- **Configuration:** run `daily-signal doctor`. Unknown fields are rejected. Relative paths are
  relative to the YAML file.
- **No articles:** run `source test <id>` and check selectors, robots, age, category allowlists, and
  minimum word count. Try `fetch_article: always` for summary-only feeds.
- **Browser source:** run `uv run scrapling install`; use a browser only for actual JavaScript.
- **Kindle document missing:** confirm Amazon approved the sender, recipient and attachment size.
  SMTP success does not prove Kindle import.
- **Scheduler stops:** `serve` is foreground-only; use Compose, systemd, or another supervisor.
- **Reader rejects EPUB:** run EPUBCheck and report the result with a minimal, non-copyrighted
  fixture.
