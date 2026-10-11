# syntax=docker/dockerfile:1
# Single image for Fly.io (see fly.toml): builds the React SPA, then runs
# FastAPI, which serves both the API and frontend/dist (api/app.py).

# ─── Stage 1: build the frontend ─────────────────────────
FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ─── Stage 2: Python runtime ─────────────────────────────
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first (own layer — only rebuilt when the lock changes),
# straight from uv.lock so the image matches local exactly.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 8080
# --proxy-headers: Fly's edge terminates HTTPS, so trust its forwarded
# scheme/IP headers.
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
