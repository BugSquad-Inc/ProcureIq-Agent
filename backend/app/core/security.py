"""
security.py — Authentication (HS256 JWT + API Key), RBAC, Multi-Tenancy, and Rate Limiting.

Roles (least -> most privileged):
  viewer     — read-only / RAG Q&A / inspect tools and history
  operator   — execute standard tools & upload tenant KB docs (PO approvals <= $25k)
  finance_vp — approve high-value purchase orders (> $25,000 per Vendor_Onboarding_Policy_v3.pdf)
  admin      — full access (delete tools/KB docs, reset circuit breakers, all tenants if needed)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Iterable, Optional

import structlog
from fastapi import Depends, Header, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings

logger = structlog.get_logger("procureiq.security")

VALID_ROLES = {"viewer", "operator", "finance_vp", "admin"}
_TENANT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$")
_AMOUNT_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class AuthContext:
    """Resolved request identity, tenant scope, and RBAC role."""
    user_id: str
    tenant_id: str
    role: str
    auth_method: str = "dev_header"


def sanitize_tenant_id(raw: Optional[str]) -> str:
    """Validate and normalize tenant identifier (defaults safely to 'default')."""
    val = (raw or "").strip()
    if not val:
        return get_settings().default_tenant_id
    if not _TENANT_RE.match(val):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Tenant-ID format (use 1-63 alphanumeric, '-', '_', '.' chars).",
        )
    return val


def validate_role(raw: Optional[str], default: str = "finance_vp") -> str:
    """Normalize and verify role name."""
    role = (raw or "").strip().lower() or default
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{role}'. Allowed roles: {sorted(VALID_ROLES)}",
        )
    return role


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + pad)


def create_access_token(
    user_id: str,
    tenant_id: str = "default",
    role: str = "operator",
    expires_minutes: Optional[int] = None,
) -> str:
    """Sign an HS256 JWT token using `settings.auth_secret_key`."""
    settings = get_settings()
    ttl_min = expires_minutes if expires_minutes is not None else settings.auth_token_expire_minutes
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "tenant_id": sanitize_tenant_id(tenant_id),
        "role": validate_role(role, default="operator"),
        "iat": now,
        "exp": now + max(1, int(ttl_min)) * 60,
    }
    h_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = hmac.new(settings.auth_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{h_b64}.{p_b64}.{_b64url_encode(sig)}"


def decode_access_token(token: str) -> Dict[str, Any]:
    """Verify HS256 JWT signature and expiry, returning decoded claims."""
    settings = get_settings()
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed Bearer token.")
    h_b64, p_b64, s_b64 = parts
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    expected_sig = hmac.new(
        settings.auth_secret_key.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    try:
        actual_sig = _b64url_decode(s_b64)
        payload = json.loads(_b64url_decode(p_b64).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Corrupted Bearer token.")

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature.")

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or time.time() > float(exp):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token expired.")

    return payload


def parse_api_keys(csv: str) -> Dict[str, AuthContext]:
    """Parse API_KEYS_CSV (`key:tenant:role:user_id,...`) into lookup dictionary."""
    entries: Dict[str, AuthContext] = {}
    for raw_item in (csv or "").split(","):
        item = raw_item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split(":")]
        key = parts[0]
        tenant_id = parts[1] if len(parts) > 1 and parts[1] else "default"
        role = parts[2] if len(parts) > 2 and parts[2] else "operator"
        user_id = parts[3] if len(parts) > 3 and parts[3] else f"apikey-{key[:6]}"
        if role in VALID_ROLES:
            entries[key] = AuthContext(
                user_id=user_id,
                tenant_id=tenant_id,
                role=role,
                auth_method="api_key",
            )
    return entries


async def get_auth_context(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    x_tenant_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> AuthContext:
    """
    Resolve authenticated identity, tenant, and role.
      1. If `Authorization: Bearer <token>` is supplied, ALWAYS validate cryptographically.
      2. If `X-API-Key` is supplied, ALWAYS validate against `API_KEYS_CSV`.
      3. When `effective_auth_enabled` (AUTH_ENABLED=true or ENVIRONMENT=production), reject
         unauthenticated requests with HTTP 401.
      4. Otherwise (dev/test mode), accept optional `X-Tenant-ID` / `X-User-Role` headers.
    """
    settings = get_settings()
    app_state_auth = getattr(request.app.state, "auth_enabled_override", None)
    auth_required = (
        bool(app_state_auth)
        if app_state_auth is not None
        else settings.effective_auth_enabled
    )

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header must use Bearer scheme.",
            )
        claims = decode_access_token(token.strip())
        return AuthContext(
            user_id=str(claims.get("sub") or "jwt-user"),
            tenant_id=sanitize_tenant_id(str(claims.get("tenant_id") or settings.default_tenant_id)),
            role=validate_role(str(claims.get("role") or "operator"), default="operator"),
            auth_method="jwt",
        )

    if x_api_key:
        key_map = parse_api_keys(settings.api_keys_csv)
        matched = key_map.get(x_api_key.strip())
        if not matched:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid X-API-Key.",
            )
        return matched

    if auth_required:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: supply Authorization Bearer JWT or X-API-Key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthContext(
        user_id="dev-operator",
        tenant_id=sanitize_tenant_id(x_tenant_id),
        role=validate_role(x_user_role, default="finance_vp"),
        auth_method="dev_header",
    )


def assert_roles(auth: AuthContext, allowed: Iterable[str], action: str) -> None:
    """Enforce RBAC role membership, raising HTTP 403 if insufficient."""
    allowed_set = set(allowed)
    if auth.role not in allowed_set:
        logger.warning(
            "rbac_forbidden",
            action=action,
            user=auth.user_id,
            role=auth.role,
            required=sorted(allowed_set),
            tenant_id=auth.tenant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"RBAC denied for action '{action}': role '{auth.role}' lacks permission; "
                f"requires one of {sorted(allowed_set)}."
            ),
        )


def require_roles(*allowed_roles: str):
    """FastAPI dependency enforcing that caller holds one of `allowed_roles`."""
    async def _dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        assert_roles(auth, allowed_roles, action=",".join(allowed_roles))
        return auth
    return _dependency


def extract_numeric_amount(params: Optional[Dict[str, Any]]) -> Optional[float]:
    """Extract first positive currency/numeric amount from tool parameters."""
    if not isinstance(params, dict):
        return None
    for key in ("amount", "total_amount", "po_amount", "value", "budget", "limit"):
        raw = params.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            m = _AMOUNT_RE.search(raw.replace("$", "").strip())
            if m:
                try:
                    return float(m.group(0).replace(",", ""))
                except ValueError:
                    continue
    return None


def enforce_tool_rbac(tool_name: Optional[str], params: Optional[Dict[str, Any]], auth: AuthContext) -> None:
    """
    Enforce domain/policy RBAC before executing state-changing tools:
      - `viewer` may not execute mutating tools
      - `approve_purchase_order` > `$25,000` (Vendor_Onboarding_Policy_v3.pdf) requires `finance_vp` or `admin`
    """
    if not tool_name:
        return

    from app.tools.paypal_adapter import is_write_tool

    if is_write_tool(tool_name) and auth.role == "viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"RBAC denied: role 'viewer' cannot execute write operation '{tool_name}'.",
        )

    if tool_name == "approve_purchase_order":
        threshold = float(get_settings().po_vp_approval_threshold)
        amount = extract_numeric_amount(params)
        if amount is not None and amount > threshold and auth.role not in ("finance_vp", "admin"):
            logger.warning(
                "po_vp_rbac_denied",
                tool=tool_name,
                amount=amount,
                threshold=threshold,
                role=auth.role,
                tenant_id=auth.tenant_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"RBAC policy violation (Vendor_Onboarding_Policy_v3.pdf): "
                    f"approving PO amount ${amount:,.2f} exceeds ${threshold:,.0f} and requires "
                    f"'finance_vp' or 'admin' role (current role: '{auth.role}')."
                ),
            )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client-IP sliding-window (60s) rate limiter returning HTTP 429."""

    EXEMPT_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/"}

    def __init__(self, app) -> None:
        super().__init__(app)
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        override = getattr(request.app.state, "rate_limit_rpm_override", None)
        limit = int(override) if override is not None else int(get_settings().rate_limit_rpm)
        if limit <= 0:
            return await call_next(request)

        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        client_ip = forwarded or (request.client.host if request.client else "unknown")

        now = time.monotonic()
        window_start = now - 60.0
        bucket = self._hits[client_ip]
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= limit:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": f"Rate limit exceeded ({limit} requests/min). Please retry shortly.",
                    "retry_after_seconds": 60,
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        bucket.append(now)
        remaining = max(0, limit - len(bucket))
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

