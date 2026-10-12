# syntax=docker/dockerfile:1
# Multi-stage build: frontend assets, then a slim Python runtime serving API + SPA.

FROM node:22-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ASTRAL_PROFILE=production ASTRAL_STORAGE_DIR=/data/objects ASTRAL_MODEL_DIR=/data/models
RUN useradd --create-home --uid 10001 astral
WORKDIR /app/backend
COPY backend/requirements.lock.txt ./
RUN pip install --no-deps -r requirements.lock.txt
COPY backend/ ./
COPY --from=web /src/frontend/dist /app/frontend/dist
RUN mkdir -p /data && chown -R astral:astral /data
USER astral
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status==200 else 1)"
CMD ["sh", "-c", "python -m astral.cli migrate && exec uvicorn astral.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
