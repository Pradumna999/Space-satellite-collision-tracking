from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AuthToken, Project, ProjectMember, User
from ..db.session import get_db
from ..services.auth import resolve_token

SESSION_COOKIE = "astral_session"
CSRF_HEADER = "X-CSRF-Token"
ROLE_RANK = {"viewer": 1, "analyst": 2, "owner": 3}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@dataclass
class Principal:
    user: User
    token: AuthToken


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("Authorization", "")
    via_cookie = False
    tok = None
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
    else:
        tok = request.cookies.get(SESSION_COOKIE)
        via_cookie = True
    if not tok:
        raise api_error(401, "UNAUTHENTICATED", "authentication required")
    found = resolve_token(db, tok)
    if found is None:
        raise api_error(401, "UNAUTHENTICATED", "session expired or invalid")
    user, row = found
    if via_cookie and request.method in UNSAFE:
        sent = request.headers.get(CSRF_HEADER, "")
        if not row.csrf_token or not hmac.compare_digest(sent, row.csrf_token):
            raise api_error(403, "CSRF", "missing or invalid CSRF token")
    request.state.user_id = user.id
    return Principal(user, row)


def current_user(p: Principal = Depends(current_principal)) -> User:
    return p.user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise api_error(403, "FORBIDDEN", "administrator role required")
    return user


class ProjectAccess:
    """Dependency enforcing project membership with a minimum role.
    Admins do NOT get implicit access to project data (data isolation); they
    manage accounts and system settings only."""

    def __init__(self, min_role: str):
        self.min_role = min_role

    def __call__(self, pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> tuple[Project, str]:
        project = db.get(Project, pid)
        m = db.scalar(select(ProjectMember).where(ProjectMember.project_id == pid, ProjectMember.user_id == user.id))
        if project is None or m is None:
            # identical response for missing and forbidden: no existence oracle
            raise api_error(404, "NOT_FOUND", "project not found")
        if ROLE_RANK[m.role] < ROLE_RANK[self.min_role]:
            raise api_error(403, "FORBIDDEN", f"{self.min_role} role required in this project")
        return project, m.role


viewer = ProjectAccess("viewer")
analyst = ProjectAccess("analyst")
owner = ProjectAccess("owner")


def paginate(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 500)), max(0, offset)
