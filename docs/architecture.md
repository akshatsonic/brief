# Architecture

Brief is a modular monolith. Typer commands and APScheduler call the same orchestration
service.

```text
YAML → source adapters → safe fetch → normalized articles → scraped JSON
                                                   ↓
SQLite ← run state ← orchestration ← structured LLM editorial pass
                                                   ↓
delivery ← Kindle-sized PDF ← final article JSON ← trusted URL restoration
```

Configuration is validated before I/O. Source adapters normalize to `Article`; the model includes
an optional `image_url` discovered from feed metadata or standard page metadata. Missing,
malformed, or unsafe image URLs normalize to `None`. The editorial layer uses either the OpenAI
Responses API or local `codex exec`, both constrained by the same Pydantic-derived JSON Schema.
Only known article IDs are accepted, and source/image URLs must exactly match scraper output.
After selection, supported images are fetched through the same safety boundary and embedded in a
6 × 9 inch PDF. Safe fetching owns URL/DNS checks, robots, rate limits, timeouts, size limits, and
HTTP/browser selection. SQLite constraints and a lease provide restart safety and delivery
idempotency. Rendering and delivery remain separate so `build` never sends mail.

Stored timestamps are UTC ISO 8601 values; edition dates and cron use the publication timezone.
Protocols support future processors, renderers, and delivery providers without a v0.1 marketplace.

