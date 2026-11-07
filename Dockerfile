FROM ghcr.io/astral-sh/uv:latest AS uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    HOME=/home/brief
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
RUN useradd --create-home --uid 10001 brief \
    && mkdir -p /data /output /config \
    && chown -R brief:brief /app /data /output
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv sync --no-dev && uv run scrapling install \
    && chown -R brief:brief /app /home/brief
USER brief
VOLUME ["/data", "/output"]
HEALTHCHECK --interval=60s --timeout=20s --start-period=30s --retries=3 \
    CMD uv run brief doctor --skip-network --config /config/brief.yaml || exit 1
ENTRYPOINT ["uv", "run", "brief"]
CMD ["serve", "--config", "/config/brief.yaml"]

