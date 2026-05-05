# Deploy

## 1. Prepare server

Install Docker and Docker Compose plugin on the VPS.

Clone the repository and enter the project directory.

## 2. Configure environment

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Set at least:

```env
TELEGRAM_TOKEN=...
ANTHROPIC_API_KEY=...
FEEDBACK_USERNAME=@your_username
```

## 3. Start bot

```bash
docker compose up -d --build
```

## 4. Check logs

```bash
docker compose logs -f
```

## 5. Update deployment

```bash
git pull
docker compose up -d --build
```

## Storage

No separate DB server is required.

The bot stores runtime files in `./data`:
- `users.db`
- `analysis_cache.db`
- `org_cache.json`
- `report.html`

## Recommended VPS

Minimum:
- 1 vCPU
- 1-2 GB RAM
- 10+ GB SSD

Comfortable:
- 2 vCPU
- 2-4 GB RAM

## Notes

- The image is prepared for production use on a simple VPS.
- `.env` is not committed to Git.
- The bot runs as a non-root user inside Docker.
