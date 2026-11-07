# Troubleshooting

- **Configuration:** run `brief doctor`. Unknown fields are rejected. Relative paths are
  relative to the YAML file.
- **No articles:** run `source test <id>` and check selectors, robots, age, category allowlists, and
  minimum word count. Try `fetch_article: always` for summary-only feeds.
- **Browser source:** run `uv run scrapling install`; use a browser only for actual JavaScript.
- **PDF browser missing:** run `uv run scrapling install`; PDF rendering uses the installed Chromium.
  An existing compatible binary can be selected with `BRIEF_CHROMIUM_EXECUTABLE`.
- **OpenAI key missing:** export the variable named by `llm.api_key_env` (default:
  `OPENAI_API_KEY`) or build with `--codex-cli`.
- **Codex CLI fails:** run `codex login status`, confirm `codex exec --help`, then run
  `brief doctor`. The CLI backend uses a read-only ephemeral session.
- **Kindle document missing:** confirm Amazon approved the sender, recipient and attachment size.
  SMTP success does not prove Kindle import.
- **Scheduler stops:** `serve` is foreground-only; use Compose, systemd, or another supervisor.
- **PDF is clipped:** use the built-in template first, then check custom CSS at the 6 × 9 inch page
  size. Long summaries should remain near the editorial prompt's 70–110 word target.
