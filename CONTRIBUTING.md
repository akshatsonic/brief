# Contributing

Thank you for helping improve Brief. Open an issue before large behavioral changes. Small
fixes may go directly to a focused pull request.

1. Install Python 3.12+ and uv, then run `uv sync --extra dev`.
2. Run `uv run pytest` and `uv run ruff check .` before changing code.
3. Add fixture-based tests for new sources; tests must not require live websites or credentials.

Keep commits narrow, preserve the canonical article model, and do not add behavior that bypasses
access restrictions. Pull requests should describe behavior, tests, configuration compatibility,
and security implications.

