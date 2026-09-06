FROM python:3.12-slim

# System deps: curl/git for tooling, ffmpeg for clipping, ca-certificates for HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 for the web build and yt-dlp's YouTube JavaScript challenges
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && npm --version

# uv (Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Codex CLI
RUN curl -fsSL https://chatgpt.com/codex/install.sh | sh

# Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash

ENV UV_PROJECT_ENVIRONMENT="/opt/game-vod-clipper-venv" \
    PATH="/opt/game-vod-clipper-venv/bin:/root/.local/bin:${PATH}"

WORKDIR /app

# Leverage Docker layer cache for deps
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY . .

CMD ["sleep", "infinity"]
