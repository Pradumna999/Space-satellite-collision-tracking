from __future__ import annotations

import contextvars
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import AuditEvent

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
client_ip_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("client_ip", default=None)

_SENSITIVE = ("password", "token", "secret", "credential")


def _scrub(d: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[redacted]" if any(s in k.lower() for s in _SENSITIVE) else v) for k, v in d.items()}


def record(db: Session, action: str, user_id: int | None = None, project_id: int | None = None, target: str | None = None,
           details: dict[str, Any] | None = None, outcome: str = "ok") -> None:
    db.add(AuditEvent(action=action, user_id=user_id, project_id=project_id, target=target, details=_scrub(details or {}),
                      request_id=request_id_var.get(), ip=client_ip_var.get(), outcome=outcome))
