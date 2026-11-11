"""
auth_api.py — Authentication & RBAC identity endpoints (`POST /api/auth/token`, `GET /api/auth/me`).
"""
from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.security import (
    AuthContext,
    create_access_token,
    get_auth_context,
    parse_api_keys,
    sanitize_tenant_id,
    validate_role,
)

router = APIRouter(prefix="/api/auth", tags=["Auth & RBAC"])


class TokenRequest(BaseModel):
    user_id: str = Field(default="operator-1", min_length=1, max_length=128)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)
    role: str = Field(default="operator", min_length=1, max_length=32)
    secret: Optional[str] = None
    api_key: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    tenant_id: str
    role: str
    expires_in_seconds: int


@router.post("/token", response_model=TokenResponse)
async def issue_token(req: TokenRequest, request: Request) -> TokenResponse:
    """
    Issue a signed HS256 JWT token.
      - In production (`AUTH_ENABLED=true` or `ENVIRONMENT=production`), caller must prove
        authorization via valid `api_key` OR matching `secret` (`AUTH_SECRET_KEY`).
      - In dev mode (`AUTH_ENABLED=false`), permits issuing scoped demo tokens for testing.
    """
    settings = get_settings()
    app_state_auth = getattr(request.app.state, "auth_enabled_override", None)
    auth_required = (
        bool(app_state_auth)
        if app_state_auth is not None
        else settings.effective_auth_enabled
    )

    if auth_required:
        valid_secret = bool(
            req.secret and hmac.compare_digest(req.secret, settings.auth_secret_key)
        )
        key_map = parse_api_keys(settings.api_keys_csv)
        valid_key = bool(req.api_key and req.api_key in key_map)
        if not (valid_secret or valid_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid secret or api_key required to issue tokens when AUTH_ENABLED is true.",
            )

    tenant_id = sanitize_tenant_id(req.tenant_id)
    role = validate_role(req.role, default="operator")
    token = create_access_token(
        user_id=req.user_id.strip(),
        tenant_id=tenant_id,
        role=role,
        expires_minutes=settings.auth_token_expire_minutes,
    )
    return TokenResponse(
        access_token=token,
        user_id=req.user_id.strip(),
        tenant_id=tenant_id,
        role=role,
        expires_in_seconds=settings.auth_token_expire_minutes * 60,
    )


@router.get("/me")
async def get_current_identity(auth: AuthContext = Depends(get_auth_context)):
    """Return resolved tenant, role, and authentication method for the current request."""
    settings = get_settings()
    return {
        "user_id": auth.user_id,
        "tenant_id": auth.tenant_id,
        "role": auth.role,
        "auth_method": auth.auth_method,
        "auth_required": settings.effective_auth_enabled,
        "po_vp_threshold": settings.po_vp_approval_threshold,
    }

