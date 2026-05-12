from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.security import read_session


def is_admin(request: Request) -> bool:
    token = request.cookies.get(settings.session_cookie_name)
    return read_session(token)


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin login required",
        )
