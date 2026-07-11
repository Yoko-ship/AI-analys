FROM node:20-slim AS frontend-builder

WORKDIR /app

COPY package.json vite.config.js /app/
COPY frontend /app/frontend

RUN npm install \
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

RUN mkdir -p /app/data \
    && chown -R appuser:appuser /app /home/appuser

USER appuser

CMD ["python", "bot.py"]
