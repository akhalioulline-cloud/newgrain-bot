# NewGrain — Telegram bot (Г1)

Telegram bot for collecting field photos from the agronomist, plus the backend that stores them. Built per `tech_spec_v3`.

## What's here

| Folder / file        | What it is                                                        |
|----------------------|-------------------------------------------------------------------|
| `docker-compose.yml` | The on-switch — starts the whole stack with one command.          |
| `Dockerfile`         | Recipe for building the Python app image (shared by bot/api/worker). |
| `requirements.txt`   | Python libraries the project needs.                               |
| `.env.example`       | Template for secrets. Copy to `.env` and fill in.                 |
| `bot/`               | The Telegram bot (chats with the agronomist).                     |
| `api/`               | The FastAPI backend.                                              |
| `worker/`            | Background helper (photo download, thumbnails, S3 upload).        |
| `db/`                | Database migrations (added in a later phase).                     |

## First-time setup

1. Install **Docker Desktop**: https://www.docker.com/products/docker-desktop/
2. Copy the secrets template and fill it in:
   ```
   cp .env.example .env
   ```
   At minimum set strong values for the passwords. `BOT_TOKEN` can stay empty for now.
3. Start everything:
   ```
   docker compose up
   ```

## Checking it works

- API health check: open http://localhost:8000/health → should show `{"status":"ok"}`
- Storage console: open http://localhost:9001 (log in with the S3 keys from `.env`)
- The bot and worker will log "idling" until later phases wire them up.

Stop everything with `Ctrl+C`, then `docker compose down`.
