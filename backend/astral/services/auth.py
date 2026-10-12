"""Local authentication: Argon2id password hashes, opaque session/API tokens.

Tokens are 256-bit random values; only their SHA-256 is stored. Sessions
use an httpOnly cookie plus a per-session CSRF token that must be echoed in
the ``X-CSRF-Token`` header on unsafe methods. API tokens are sent as
``Authorization: Bearer`` and are not subject to CSRF (no ambient credential).

This is a basic local identity system. It is not equivalent to a reviewed
agency identity-management system; see SECURITY.md for the OIDC path.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AuthToken, User
from ..settings import get_settings

_ph = PasswordHasher()  # argon2id, library defaults (RFC 9106 second recommended profile)
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15
MIN_PASSWORD_LEN = 12


class AuthError(Exception):
    pass


def hash_password(pw: str) -> str:
    if len(pw) < MIN_PASSWORD_LEN:
        raise AuthError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    return _ph.hash(pw)


def _token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    now = datetime.now(UTC)
    if user is None or not user.is_active or not user.password_hash:
        # constant-ish time: still run a hash verification
        try:
            _ph.verify(_ph.hash("x" * 16), "y" * 16)
        except VerificationError:
            pass
        raise AuthError("invalid credentials")
    if user.locked_until and _aware(user.locked_until) > now:
        raise AuthError("account temporarily locked")
    try:
        _ph.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError):
        user.failed_logins += 1
        if user.failed_logins >= LOCKOUT_THRESHOLD:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_logins = 0
        db.commit()
        raise AuthError("invalid credentials") from None
    user.failed_logins = 0
    user.locked_until = None
    if _ph.check_needs_rehash(user.password_hash):
        user.password_hash = _ph.hash(password)
    db.commit()
    return user


def issue_token(db: Session, user: User, kind: str = "session", label: str | None = None, days: float | None = None) -> tuple[str, AuthToken]:
    tok = secrets.token_urlsafe(32)
    hours = get_settings().session_hours if kind == "session" else 24 * (days or 90)
    row = AuthToken(user_id=user.id, token_hash=_token_hash(tok), kind=kind, label=label,
                    csrf_token=secrets.token_urlsafe(24) if kind == "session" else None,
                    expires_at=datetime.now(UTC) + timedelta(hours=hours))
    db.add(row)
    db.commit()
    return tok, row


def resolve_token(db: Session, tok: str) -> tuple[User, AuthToken] | None:
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == _token_hash(tok)))
    if row is None or row.revoked or _aware(row.expires_at) < datetime.now(UTC):
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user, row


def revoke(db: Session, row: AuthToken) -> None:
    row.revoked = True
    db.commit()


def create_user(db: Session, email: str, password: str, display_name: str, is_admin: bool = False) -> User:
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("email already registered")
    u = User(email=email, display_name=display_name, password_hash=hash_password(password), is_admin=is_admin)
    db.add(u)
    db.commit()
    return u
