from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.schemas import AdminLoginRequest, AdminMe
from app.core.config import settings
from app.core.deps import is_admin, require_admin
from app.core.security import issue_session, verify_admin_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=AdminMe)
def login(payload: AdminLoginRequest, response: Response) -> AdminMe:
    if not verify_admin_password(payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password")

    response.set_cookie(
        key=settings.session_cookie_name,
        value=issue_session(),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_secure,
        path="/",
    )
    return AdminMe(authenticated=True)


@router.post("/logout", response_model=AdminMe)
def logout(response: Response) -> AdminMe:
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return AdminMe(authenticated=False)


@router.get("/me", response_model=AdminMe)
def me(request: Request) -> AdminMe:
    return AdminMe(authenticated=is_admin(request))


@router.get("/_probe", dependencies=[Depends(require_admin)])
def probe() -> dict[str, str]:
    return {"ok": "true"}
