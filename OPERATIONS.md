# Operations

## Monitoring

* `GET /api/v1/health/live` — process up.
* `GET /api/v1/health/ready` — database, object store, worker (in-process heartbeat, or job heartbeats for external workers), leap-second table validity. Returns 503 when degraded.
* `GET /api/v1/system/info` (authenticated) — versions, queue counts by status, process CPU/RSS, limits, provider fetch status, latest benchmark.
* Logs: one JSON line per request (`request_id`, method, path, status, ms, user). Jobs log `job <id> claimed by <worker>`. Each failed job stores `error_category` (DATA_ERROR, CONFIG_ERROR, NUMERICAL_ERROR, TRANSIENT_INFRA, INTERNAL) and a message; no secrets are included.

## Failure handling

* Deterministic scientific/data/config errors are **not** retried.
* Transient database errors: retried up to 3 attempts with exponential back-off (`started_at` used as not-before).
* Lost worker: running jobs whose heartbeat is older than 10 min are re-queued (or failed after 3 attempts) by the next claiming worker.
* Cancellation: `POST /jobs/{id}/cancel`; queued jobs stop immediately, running jobs stop at the next safe point.

## Procedures

**Restart workers:** `docker compose restart worker`. In-flight jobs are recovered by the heartbeat rule.

**Recover a failed job:** inspect it with `GET /api/v1/projects/{pid}/jobs/{id}`; fix the input or config; `POST …/jobs/{id}/rerun` (same snapshot and config, new job id).

**Backup:**
```bash
docker compose exec -T db pg_dump -U astral -Fc astral > astral-$(date +%F).dump
docker run --rm -v astral_objects:/data -v "$PWD":/b alpine tar czf /b/objects-$(date +%F).tgz -C /data .
```
Back up both together. Snapshots referenced by the database must exist in the object store, and hashes are verified on use.

**Restore:**
```bash
docker compose down
docker volume rm astral_pgdata astral_objects
docker compose up -d db
docker compose exec -T db pg_restore -U astral -d astral --clean --if-exists < astral-YYYY-MM-DD.dump
docker run --rm -v astral_objects:/data -v "$PWD":/b alpine tar xzf /b/objects-YYYY-MM-DD.tgz -C /data
docker compose up -d
```

**Upgrade:** back up; `git pull`; `docker compose up -d --build`. The API runs `alembic upgrade head` at start. Check `/health/ready`. To roll back, restore the backup and redeploy the previous image.

**Retention:** uploads carry `retain_until` (`ASTRAL_RETENTION_DAYS_UPLOADS`, default 365 days). Automated purge is not yet implemented (ROADMAP R9). Deleting a project cascades its database rows; its object-store files must be removed manually.

**Leap-second / EOP tables:** both are bundled with astropy. Upgrade astropy (or `astropy-iers-data`) before the leap-second table expires (2027-06-28 in this build), then rebuild.

## Incident response (runbook)

1. **Triage.** Note request ids and job ids from logs and the audit log (`/admin/audit`).
2. **Contain.** Deactivate affected accounts (`PATCH /admin/users/{id}`; this revokes tokens on password reset), revoke API tokens, block at the proxy.
3. **Preserve.** Take a database dump, an object-store archive and the logs.
4. **Assess.** Use audit events for exports/uploads in the window to determine data exposure.
5. **Recover.** Rotate `ASTRAL_SECRET_KEY` and database credentials, patch, redeploy, then verify with `pytest tests/security`.
6. **Report.** Inform data owners and record lessons learned.
