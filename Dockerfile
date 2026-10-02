# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.9

FROM ${NODE_IMAGE} AS node
FROM ${UV_IMAGE} AS uv

FROM node AS frontend
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src ./src
RUN npm run build

FROM node AS codex
RUN npm install --global --prefix /opt/codex --no-audit --no-fund @openai/codex

FROM ${PYTHON_IMAGE} AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl ffmpeg git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=codex /opt/codex /opt/codex
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/game-vod-clipper-venv \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/game-vod-clipper-venv/bin:/opt/codex/bin:${PATH}"
WORKDIR /app

FROM base AS python-dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra web --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src ./src
# Editable installation keeps the existing source-relative assets/skill lookup.
RUN uv sync --frozen --extra web --no-dev
COPY skills/game-vod-boss-clipper/SKILL.md ./skills/game-vod-boss-clipper/SKILL.md

# VS Code selects this target; the default image below runs the service.
FROM python-dependencies AS development
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/root/.local/bin:${PATH}"
CMD ["sleep", "infinity"]

FROM base AS runtime
COPY --from=python-dependencies /opt/game-vod-clipper-venv /opt/game-vod-clipper-venv
COPY --from=python-dependencies /app /app
COPY --from=frontend /build/web/dist ./web/dist

ARG APP_UID=1000
ARG APP_GID=1000
RUN if ! getent group "${APP_GID}" >/dev/null; then groupadd --gid "${APP_GID}" bosscut; fi \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home bosscut \
    && mkdir -p /data/downloads /data/clips /data/runs /home/bosscut/.codex \
    && chown "${APP_UID}:${APP_GID}" /data /data/downloads /data/clips /data/runs /home/bosscut/.codex \
    && chmod 700 /data/runs /home/bosscut/.codex
ENV GAME_VOD_ROOT=/data \
    GAME_VOD_HOST=0.0.0.0 \
    CODEX_HOME=/home/bosscut/.codex
USER bosscut
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).close()"]
CMD ["game-vod-web"]
