# ---- builder ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# Copy application code
COPY mitty/ mitty/

# ---- runtime ----
FROM python:3.12-slim-bookworm

# Install supercronic (cron for containers)
ARG SUPERCRONIC_VERSION=v0.2.33
ARG SUPERCRONIC_SHA=71b0d58cc53f6bd72cf2f293e09e294b79c666d8
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
         -o /usr/local/bin/supercronic \
    && echo "${SUPERCRONIC_SHA}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual-env and app from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/mitty /app/mitty

# Copy crontab
COPY crontab /app/crontab

# Put venv on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root
RUN useradd --create-home appuser
USER appuser

CMD ["supercronic", "/app/crontab"]
