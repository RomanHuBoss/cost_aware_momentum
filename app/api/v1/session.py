from __future__ import annotations

import hmac
import secrets

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import MutatingOperatorDep, SettingsDep, sign_session
from app.api.schemas import LoginRequest

router = APIRouter(prefix="/api/v1/session", tags=["session"])


@router.post("/login")
async def login(payload: LoginRequest, response: Response, settings: SettingsDep) -> dict:
    if not hmac.compare_digest(payload.password, settings.operator_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    session_token = sign_session(settings)
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        "cam_session",
        session_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=12 * 3600,
        path="/",
    )
    response.set_cookie(
        "cam_csrf",
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=12 * 3600,
        path="/",
    )
    return {"ok": True, "csrf_token": csrf, "operator": "local-operator"}


@router.post("/logout")
async def logout(response: Response, _operator: MutatingOperatorDep) -> dict:
    response.delete_cookie("cam_session", path="/")
    response.delete_cookie("cam_csrf", path="/")
    return {"ok": True}
