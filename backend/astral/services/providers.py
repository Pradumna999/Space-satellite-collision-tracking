"""Orbital-data providers.

CelesTrak GP (public): documented query interface
``gp.php?GROUP=<group>&FORMAT=<tle|json|csv|xml>`` or ``CATNR=<n>``.
Fetches are optional, rate-limited by a local cache window, retried with
exponential backoff on transient failures, and stored as ordinary uploads
with ``origin=provider`` and full fetch provenance. Downloaded data is NOT
treated as operationally authoritative.

Space-Track: requires credentials supplied via ASTRAL_SPACETRACK_USERNAME /
ASTRAL_SPACETRACK_PASSWORD and acceptance of Space-Track's user agreement by
the operator. ASTRAL never stores those credentials in the database. The
implementation follows Space-Track's documented ajaxauth login + basicspacedata
query flow, but it has NOT been exercised against the live service in this
build (no credentials available); it is marked UNVERIFIED.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ProviderFetch
from ..settings import get_settings

_GROUP = re.compile(r"^[a-z0-9-]{1,40}$")
USER_AGENT = "ASTRAL/0.1 (research software; contact: operator)"


class ProviderError(Exception):
    pass


def _get_with_retry(url: str, params: dict, attempts: int = 3, auth_client: httpx.Client | None = None) -> httpx.Response:
    delay = 2.0
    last: Exception | None = None
    client = auth_client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    try:
        for i in range(attempts):
            try:
                r = client.get(url, params=params)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise ProviderError(f"HTTP {r.status_code}")
                return r
            except (httpx.TransportError, ProviderError) as exc:
                last = exc
                if i < attempts - 1:
                    time.sleep(delay)
                    delay *= 2
        raise ProviderError(f"provider unavailable after {attempts} attempts: {last}")
    finally:
        if auth_client is None:
            client.close()


def celestrak_fetch(db: Session, group: str | None = None, catnr: int | None = None, fmt: str = "tle") -> tuple[bytes, dict]:
    s = get_settings()
    if not s.celestrak_enabled:
        raise ProviderError("CelesTrak provider disabled by configuration")
    params: dict = {"FORMAT": fmt}
    if group:
        if not _GROUP.match(group):
            raise ProviderError("invalid group name")
        params["GROUP"] = group
    elif catnr:
        params["CATNR"] = int(catnr)
    else:
        raise ProviderError("group or catnr required")
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    recent = db.scalar(select(ProviderFetch).where(ProviderFetch.provider == "celestrak", ProviderFetch.query == query,
                                                   ProviderFetch.status == "ok").order_by(ProviderFetch.fetched_at.desc()))
    if recent is not None:
        fa = recent.fetched_at if recent.fetched_at.tzinfo else recent.fetched_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - fa < timedelta(hours=s.provider_cache_hours):
            raise ProviderError(f"cached: the same query was fetched at {fa.isoformat()}; CelesTrak asks clients not to re-download "
                                f"unchanged data more often than every {s.provider_cache_hours} h. Use the existing dataset.")
    row = ProviderFetch(provider="celestrak", query=query, status="error")
    db.add(row)
    try:
        r = _get_with_retry(s.celestrak_base_url, params)
    except ProviderError as exc:
        row.message = str(exc)
        db.commit()
        raise
    row.http_status = r.status_code
    body = r.content
    if r.status_code != 200 or not body.strip() or body.strip().lower().startswith(b"no gp data"):
        row.message = body[:200].decode(errors="replace")
        db.commit()
        raise ProviderError(f"CelesTrak returned {r.status_code}: {row.message}")
    row.status = "ok"
    db.commit()
    prov = {"provider": "CelesTrak", "url": s.celestrak_base_url, "query": query, "fetched_utc": datetime.now(UTC).isoformat(),
            "http_status": r.status_code, "fetch_id": row.id, "authority": "public GP data; not operationally authoritative"}
    return body, prov


def spacetrack_configured() -> bool:
    s = get_settings()
    return bool(s.spacetrack_username and s.spacetrack_password)


def spacetrack_fetch_gp(norad_ids: list[int]) -> tuple[bytes, dict]:  # pragma: no cover - requires live credentials
    s = get_settings()
    if not spacetrack_configured():
        raise ProviderError("Space-Track credentials not configured (ASTRAL_SPACETRACK_USERNAME/PASSWORD)")
    ids = ",".join(str(int(i)) for i in norad_ids[:500])
    base = "https://www.space-track.org"
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}) as c:
        lr = c.post(f"{base}/ajaxauth/login", data={"identity": s.spacetrack_username, "password": s.spacetrack_password})
        if lr.status_code != 200:
            raise ProviderError(f"Space-Track login failed (HTTP {lr.status_code})")
        url = f"{base}/basicspacedata/query/class/gp/NORAD_CAT_ID/{ids}/orderby/NORAD_CAT_ID/format/json"
        r = _get_with_retry(url, {}, auth_client=c)
        c.get(f"{base}/ajaxauth/logout")
    if r.status_code != 200:
        raise ProviderError(f"Space-Track query failed (HTTP {r.status_code})")
    return r.content, {"provider": "Space-Track", "query": f"gp NORAD_CAT_ID {ids}", "fetched_utc": datetime.now(UTC).isoformat(),
                       "status": "UNVERIFIED integration"}
