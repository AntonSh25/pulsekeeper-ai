FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PULSEKEEPER_CONFIG=/config/config.toml \
    PULSEKEEPER_STORAGE_DIR=/data \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

VOLUME ["/data", "/config"]

HEALTHCHECK --interval=5m --timeout=15s --start-period=30s --retries=3 \
    CMD pulsekeeper doctor --config "$PULSEKEEPER_CONFIG" || exit 1

ENTRYPOINT ["pulsekeeper"]
CMD ["doctor"]
