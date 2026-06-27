from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_session(settings: Settings, user_id: str = "local-operator", hours: int = 12) -> str:
    payload = {
        "sub": user_id,
        "exp": int((datetime.now(UTC) + timedelta(hours=hours)).timestamp()),
        "nonce": secrets.token_hex(8),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_session(settings: Settings, token: str) -> str | None:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64decode(body))
        if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            return None
        return str(payload["sub"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


async def current_operator(
    request: Request,
    settings: SettingsDep,
    cam_session: str | None = Cookie(default=None),
    x_operator_token: str | None = Header(default=None),
) -> str:
    if (
        settings.operator_api_token
        and x_operator_token
        and hmac.compare_digest(x_operator_token, settings.operator_api_token)
    ):
        request.state.auth_mode = "api_token"
        return "api-operator"
    if cam_session:
        user_id = verify_session(settings, cam_session)
        if user_id:
            request.state.auth_mode = "session"
            return user_id
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Operator authentication required")


OperatorDep = Annotated[str, Depends(current_operator)]


async def require_csrf(
    request: Request,
    operator: OperatorDep,
    cam_csrf: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None),
) -> str:
    if getattr(request.state, "auth_mode", None) == "api_token":
        return operator
    if not cam_csrf or not x_csrf_token or not hmac.compare_digest(cam_csrf, x_csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token is missing or invalid")
    return operator


MutatingOperatorDep = Annotated[str, Depends(require_csrf)]
