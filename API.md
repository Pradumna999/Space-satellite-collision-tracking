# API

Base path `/api/v1`. OpenAPI: `/api/v1/openapi.json`; interactive docs: `/docs`.

## Authentication

* **Browser:** `POST /auth/login {email, password}` sets an httpOnly `astral_session` cookie and returns `csrf_token`. Send it as `X-CSRF-Token` on every POST/PATCH/DELETE.
* **Scripts:** create a token (`POST /auth/tokens {label, days}`, shown once) and send `Authorization: Bearer <token>`. No CSRF header is needed.

## Errors

```json
{"error": {"code": "INVALID_CONFIG", "message": "step must be within [0.5, 600] s", "request_id": "5f2c…"}}
```
Codes: `UNAUTHENTICATED` 401 · `INVALID_CREDENTIALS` 401 · `CSRF` 403 · `FORBIDDEN` 403 · `NOT_FOUND` 404 (also for resources in projects you cannot access) · `CONFLICT` 409 · `NOT_READY` 409 · `NOT_EXPORTABLE` 409/422 · `PAYLOAD_TOO_LARGE` 413 · `UPLOAD_REJECTED` 422 · `INVALID_CONFIG` 422 · `VALIDATION` 422 · `QUOTA` 429 · `RATE_LIMITED` 429 · `PROVIDER_ERROR` 502 · `INTERNAL` 500.

Pagination: `limit` (≤ 500) and `offset`; responses are `{total, items}`. Idempotency: `Idempotency-Key` header on `POST /projects/{pid}/jobs`; repeats return the original job with `created: false`.

## Main endpoints

| Method | Path | Role |
|---|---|---|
| GET/POST | `/projects` | any / creates as owner |
| POST | `/projects/{pid}/members` | owner |
| GET/POST | `/projects/{pid}/datasets` (multipart `file`, `name?`, `dataset_id?`, `fmt?`) | viewer / analyst |
| GET | `/projects/{pid}/dataset-versions/{vid}` · `/findings` · `/validation-report.csv` · `/raw` · `/covariances` | viewer |
| POST | `/projects/{pid}/dataset-versions/{vid}/approve` · `/transformations/{tid}/approve` · `/reject` | analyst |
| GET | `/projects/{pid}/catalogue?vid=&q=&sort=` | viewer |
| POST | `/projects/{pid}/provider-fetch {provider:"celestrak", group}` | analyst |
| POST | `/projects/{pid}/jobs {dataset_version_id, config}` | analyst |
| GET | `/projects/{pid}/jobs` · `/jobs/{id}` · `/jobs/{a}/compare/{b}` | viewer |
| POST | `/projects/{pid}/jobs/{id}/cancel` · `/rerun` | analyst |
| GET | `/projects/{pid}/encounters?job_id=&max_miss_km=&object_id=&sort=` · `/encounters/{id}` · `/relative-motion` | viewer |
| GET | `/projects/{pid}/viz/positions?vid=&at=` · `/viz/trajectory?vid=&object_id=&start=` | viewer |
| POST/GET | `/projects/{pid}/encounters/{id}/scenarios` | analyst / viewer |
| POST | `/projects/{pid}/jobs/{id}/reports?fmt=pdf\|csv\|json` | viewer |
| GET | `/projects/{pid}/reports` · `/reports/{rid}/download` · `/encounters/{id}/export/cdm` · `/dataset-versions/{vid}/export/oem` | viewer |
| GET | `/ml/models`; POST `/ml/train`, `/ml/models/{id}/activate` · `/deactivate` | any / admin |
| GET | `/health/live` · `/health/ready` (no auth); `/system/info` | any |
| GET/POST/PATCH | `/admin/users`, `/admin/audit` | admin |

Job configs:

```json
{"kind": "screening", "start_utc": "2026-10-10T00:00:00Z", "duration_hours": 72, "step_s": 30, "threshold_km": 5, "primary_ids": null}
{"kind": "cdm_assessment", "hbr_m": 20, "monte_carlo_samples": 500000, "seed": 0}
```

## Example (curl, bearer token)

```bash
T=…   # API token
curl -H "Authorization: Bearer $T" -F file=@examples/sample-catalogue.tle -F name=demo http://localhost:8000/api/v1/projects/1/datasets
curl -H "Authorization: Bearer $T" -H "Content-Type: application/json" -H "Idempotency-Key: run-1" \
  -d '{"dataset_version_id": 7, "config": {"kind":"screening","start_utc":"2026-10-10T00:00:00Z","duration_hours":24}}' \
  http://localhost:8000/api/v1/projects/1/jobs
curl -H "Authorization: Bearer $T" "http://localhost:8000/api/v1/projects/1/encounters?job_id=8&sort=miss"
```
