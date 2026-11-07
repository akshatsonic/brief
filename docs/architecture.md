# Architecture

Daily Signal is a modular monolith. Typer commands and APScheduler call the same orchestration
service.

```text
YAML → source adapters → safe fetch service → Article models → processors
                                                        ↓
SQLite ← run/edition state ← orchestration → EPUB renderer → delivery
```

Configuration is validated before I/O. Source adapters normalize to `Article`; safe fetching owns
URL/DNS checks, robots, rate limits, timeouts, size limits, and HTTP/browser selection. Processing
is deterministic and offline. SQLite constraints and a lease provide restart safety and delivery
idempotency. Rendering and delivery remain separate so `build` never sends mail.

Stored timestamps are UTC ISO 8601 values; edition dates and cron use the publication timezone.
Protocols support future processors, renderers, and delivery providers without a v0.1 marketplace.

