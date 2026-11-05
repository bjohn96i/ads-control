# ADS-Control: the API with the web page built in. Paths inside the app resolve relative to the
# repo root (data/, web/dist, api/alembic.ini), so the image keeps the repo's layout under /app.

FROM node:22-bookworm-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH=/app/api/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app/api
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY api/ ./
# Editable install (uv's default), so settings find data/ and web/dist from the source tree.
RUN uv sync --frozen --no-dev
COPY --from=web /app/web/dist /app/web/dist

RUN useradd --uid 1000 --create-home adscontrol && install -d -o adscontrol /app/data
USER adscontrol
EXPOSE 8100
CMD ["sh", "-c", "adscontrol migrate && exec adscontrol serve"]
