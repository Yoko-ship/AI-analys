FROM node:20-slim AS frontend-builder

WORKDIR /app

# The lockfile is copied so the build uses `npm ci` — a reproducible install from
# pinned versions. `npm install` re-resolves the tree on every build, which means
# the image you test is not necessarily the image you ship.
COPY package.json package-lock.json vite.config.js /app/
COPY frontend /app/frontend

RUN npm ci \
    && npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Tashkent

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata fonts-dejavu-core \
    && groupadd --system appuser \
    && useradd --system --gid appuser --create-home --home-dir /home/appuser appuser \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-server.txt /app/
RUN pip install --upgrade pip \
    && pip install -r requirements-server.txt

COPY . /app
COPY --from=frontend-builder /app/web/dist /app/web/dist

# Frontend sources are build inputs, not runtime files: the compiled bundle already
# came from the builder stage above. They cannot be excluded via .dockerignore
# (that applies to every stage, and the builder needs them), so they are dropped
# here — ~3 MB of raw PNG assets plus the JSX/CSS sources that serve no purpose on
# a running container.
RUN rm -rf /app/frontend /app/node_modules /app/package-lock.json /app/vite.config.js \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app /home/appuser

USER appuser

# Overridden per service by railway.json / railway.collector.json / railway.news.json.
CMD ["python", "bot.py"]
