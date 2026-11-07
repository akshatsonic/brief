FROM ghcr.io/astral-sh/uv:latest AS uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    HOME=/home/daily-signal
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
RUN useradd --create-home --uid 10001 daily-signal \
    && mkdir -p /data /output /config \
    && chown -R daily-signal:daily-signal /app /data /output
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv sync --no-dev && uv run scrapling install \
    && chown -R daily-signal:daily-signal /app /home/daily-signal
USER daily-signal
VOLUME ["/data", "/output"]
HEALTHCHECK --interval=60s --timeout=20s --start-period=30s --retries=3 \
    CMD uv run daily-signal doctor --skip-network --config /config/daily-signal.yaml || exit 1
ENTRYPOINT ["uv", "run", "daily-signal"]
CMD ["serve", "--config", "/config/daily-signal.yaml"]

