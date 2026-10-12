from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AuthToken, User
from ..db.session import get_db
from ..services import audit
from ..services.auth import AuthError, authenticate, create_user, hash_password, issue_token, revoke
from ..settings import get_settings
from .deps import SESSION_COOKIE, Principal, api_error, current_principal, current_user, require_admin

router = APIRouter(prefix="/api/v1", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=500)


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool
    is_active: bool


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, display_name=u.display_name, is_admin=u.is_admin, is_active=u.is_active)


@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    try:
        user = authenticate(db, body.email, body.password)
    except AuthError as exc:
        audit.record(db, "auth.login", None, details={"email": body.email[:100]}, outcome="denied")
        db.commit()
        raise api_error(401, "INVALID_CREDENTIALS", str(exc)) from None
    tok, row = issue_token(db, user, "session")
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, tok, httponly=True, secure=s.cookie_secure, samesite="lax", max_age=s.session_hours * 3600, path="/")
    audit.record(db, "auth.login", user.id)
    db.commit()
    return {"user": _out(user), "csrf_token": row.csrf_token}


@router.post("/auth/logout")
def logout(response: Response, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    row = db.get(AuthToken, p.token.id)
    revoke(db, row)
    response.delete_cookie(SESSION_COOKIE, path="/")
    audit.record(db, "auth.logout", p.user.id)
    db.commit()
    return {"ok": True}


@router.get("/auth/me")
def me(p: Principal = Depends(current_principal)):
    return {"user": _out(p.user), "csrf_token": p.token.csrf_token}


class TokenIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    days: float = Field(30, gt=0, le=365)


@router.post("/auth/tokens", status_code=201)
def create_api_token(body: TokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    tok, row = issue_token(db, user, "api", body.label, body.days)
    audit.record(db, "auth.api_token.create", user.id, target=f"token:{row.id}", details={"label": body.label})
    db.commit()
    return {"id": row.id, "token": tok, "expires_at": row.expires_at, "note": "shown once; store it securely"}


@router.get("/auth/tokens")
def list_tokens(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuthToken).where(AuthToken.user_id == user.id, AuthToken.kind == "api", AuthToken.revoked.is_(False)))
    return {"items": [{"id": r.id, "label": r.label, "expires_at": r.expires_at, "created_at": r.created_at} for r in rows]}


@router.delete("/auth/tokens/{tid}")
def revoke_token(tid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(AuthToken, tid)
    if row is None or row.user_id != user.id:
        raise api_error(404, "NOT_FOUND", "token not found")
    revoke(db, row)
    audit.record(db, "auth.api_token.revoke", user.id, target=f"token:{tid}")
    db.commit()
    return {"ok": True}


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=500)
    is_admin: bool = False


@router.get("/admin/users")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": [_out(u) for u in db.scalars(select(User).order_by(User.id))]}


@router.post("/admin/users", status_code=201)
def admin_create_user(body: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        u = create_user(db, body.email, body.password, body.display_name, body.is_admin)
    except AuthError as exc:
        raise api_error(409, "CONFLICT", str(exc)) from None
    audit.record(db, "admin.user.create", admin.id, target=f"user:{u.id}", details={"email": u.email, "is_admin": u.is_admin})
    db.commit()
    return _out(u)


class UserPatch(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None
    password: str | None = Field(None, min_length=12, max_length=500)


@router.patch("/admin/users/{uid}")
def admin_patch_user(uid: int, body: UserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise api_error(404, "NOT_FOUND", "user not found")
    if u.id == admin.id and (body.is_admin is False or body.is_active is False):
        raise api_error(400, "SELF_LOCKOUT", "administrators cannot remove their own admin role or deactivate themselves")
    changes = {}
    if body.is_active is not None:
        u.is_active = body.is_active
        changes["is_active"] = body.is_active
    if body.is_admin is not None:
        u.is_admin = body.is_admin
        changes["is_admin"] = body.is_admin
    if body.password:
        u.password_hash = hash_password(body.password)
        changes["password"] = "reset"
        for t in db.scalars(select(AuthToken).where(AuthToken.user_id == u.id)):
            t.revoked = True
    audit.record(db, "admin.user.update", admin.id, target=f"user:{u.id}", details=changes)
    db.commit()
    return _out(u)
