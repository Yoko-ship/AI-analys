FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Tashkent \
    APP_DATA_DIR=/app/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && groupadd --system appuser \
    && useradd --system --gid appuser --create-home --home-dir /home/appuser appuser \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-server.txt /app/
RUN pip install --upgrade pip \
    && pip install -r requirements-server.txt

COPY . /app

RUN mkdir -p /app/data \
    && chown -R appuser:appuser /app /home/appuser

USER appuser

CMD ["python", "bot.py"]
