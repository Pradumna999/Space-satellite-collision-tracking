# Deployment

## Local (development profile)

See README quick start. SQLite at `backend/data/astral.db`, object store at `backend/data/objects/`, worker thread inside the API process (`ASTRAL_WORKER_MODE=inprocess`). Resource use: ~250 MB RSS idle; screening memory ≈ 0.28 MB × objects × (window/step) / 1000. Use 1 hour of 30 s steps for every 1,000 objects as a rough guide.

## Staging / production (Docker Compose)

```bash
cp .env.example .env
# edit .env: ASTRAL_SECRET_KEY (random 32+ bytes), POSTGRES_PASSWORD, ASTRAL_ALLOWED_ORIGINS, ASTRAL_HTTP_PORT
docker compose up -d --build
docker compose exec -e ASTRAL_ADMIN_PASSWORD='…' api python -m astral.cli create-admin --email ops@example.org
```

Services: `db` (PostgreSQL 16, health-checked), `api` (runs `alembic upgrade head` on start, then uvicorn; serves the built SPA; Docker HEALTHCHECK on `/api/v1/health/live`), `worker` (`python -m astral.worker`, 2 CPU / 2 GB limits). The API binds to `127.0.0.1:${ASTRAL_HTTP_PORT}` only.

Verified in this build: image build, migrations on PostgreSQL, health checks, concurrent job processing.

### TLS termination

Put a reverse proxy (Caddy, nginx, Traefik) in front and keep `ASTRAL_COOKIE_SECURE=true`. Example (Caddy):

```
astral.example.org {
    reverse_proxy 127.0.0.1:8000
}
```

uvicorn runs with `--proxy-headers`, so the rate limiter sees client addresses. Restrict `forwarded-allow-ips` to the proxy address when the proxy is not on the same host.

### Production checks enforced at start-up

Start-up fails when the profile is `production` and any of these hold: the default secret key, SQLite, or `ASTRAL_COOKIE_SECURE=false`.

### Scaling notes

More workers: `docker compose up -d --scale worker=3`. Job claiming is safe (SKIP LOCKED). The rate limiter is per process; use the proxy's rate limiting for multiple API replicas.
