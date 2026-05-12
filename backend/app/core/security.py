import logging
import secrets

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

log = logging.getLogger(__name__)

_SESSION_SALT = "print-web.session.v1"


def _resolve_secret() -> str:
    if settings.secret_key:
        return settings.secret_key
    # Dev convenience: never block startup, but warn loudly so the operator
    # remembers to set SECRET_KEY before exposing the service.
    generated = secrets.token_urlsafe(32)
    log.warning(
        "SECRET_KEY is unset; generated an ephemeral key for this process. "
        "Set SECRET_KEY in .env so sessions survive restarts."
    )
    return generated


_serializer = URLSafeTimedSerializer(_resolve_secret(), salt=_SESSION_SALT)


def verify_admin_password(password: str) -> bool:
    if not settings.admin_password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), settings.admin_password_hash.encode("utf-8"))
    except ValueError:
        return False


def issue_session() -> str:
    return _serializer.dumps({"sub": "admin"})


def read_session(token: str | None) -> bool:
    if not token:
        return False
    try:
        payload = _serializer.loads(token, max_age=settings.session_max_age_seconds)
    except SignatureExpired:
        return False
    except BadSignature:
        return False
    return payload.get("sub") == "admin"
