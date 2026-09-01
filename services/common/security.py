"""OAuth 2.0 client-credentials issuance and validation.

Local mode runs a *mock* authorization server so the full token flow can be
exercised offline.  In cloud mode the platform is configured against Anypoint
Access Management (or the enterprise IdP) and this module only validates -
issuance is never done by an application.

Scope model (``docs/security-architecture.md`` - least privilege):
    customer:read   read the Customer 360 profile
    insights:read   read derived analytics and churn scores
    ai:invoke       trigger a generative call (chargeable, audited)
    ai:write        persist generated content and audit rows - platform only
    pii:read        see unmasked direct identifiers - granted to very few clients
    admin:write     administrative operations - not granted to client apps
"""
from __future__ import annotations

import hmac
import time
from collections.abc import Iterable

import jwt
from fastapi import Header, Request

from .config import get_settings
from .errors import ForbiddenError, UnauthorizedError

_settings = get_settings()
ALGORITHM = "HS256"          # local mock only; production uses RS256 + JWKS
ISSUER = "https://auth.acme-retail.example.com"

# Registered clients for the local mock authorization server.  Secrets here are
# local-only placeholders; cloud mode reads them from the secrets manager.
_CLIENTS: dict[str, dict] = {
    "acme-portal-client": {
        "secret": _settings.oauth_client_secret,
        "scopes": ["customer:read", "insights:read", "ai:invoke"],
        "sla": "gold",
    },
    "acme-batch-client": {
        "secret": _settings.oauth_client_secret,
        "scopes": ["customer:read", "insights:read"],
        "sla": "silver",
    },
    "acme-readonly-client": {
        "secret": _settings.oauth_client_secret,
        "scopes": ["customer:read"],
        "sla": "bronze",
    },
    # The service-desk application used by agents who speak to customers. It is
    # the only client entitled to unmasked identifiers, because an agent has to
    # be able to read back an e-mail address to confirm it. Entitlement is per
    # client application, not per endpoint - which is what makes it auditable.
    "acme-servicedesk-client": {
        "secret": _settings.oauth_client_secret,
        "scopes": ["customer:read", "insights:read", "ai:invoke", "pii:read"],
        "sla": "gold",
    },
    # Platform component, not a customer-facing client.  It is the only identity
    # holding ai:write, and it holds no pii:read.
    "acme-ai-service": {
        "secret": _settings.oauth_client_secret,
        "scopes": ["customer:read", "insights:read", "ai:invoke", "ai:write"],
        "sla": "internal",
    },
}


def issue_token(client_id: str, client_secret: str, requested_scope: str | None = None) -> dict:
    client = _CLIENTS.get(client_id)
    if client is None or not hmac.compare_digest(client["secret"], client_secret or ""):
        # Identical response for unknown client and bad secret - no user enumeration.
        raise UnauthorizedError("invalid_client")
    granted = client["scopes"]
    if requested_scope:
        asked = requested_scope.split()
        granted = [s for s in asked if s in client["scopes"]]
        if not granted:
            raise ForbiddenError("The client is not entitled to any of the requested scopes.")
    now = int(time.time())
    payload = {
        "iss": ISSUER, "aud": _settings.oauth_audience, "sub": client_id,
        "client_id": client_id, "scope": " ".join(granted), "sla": client["sla"],
        "iat": now, "exp": now + _settings.oauth_token_ttl_seconds,
    }
    token = jwt.encode(payload, _settings.jwt_signing_key, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "Bearer",
            "expires_in": _settings.oauth_token_ttl_seconds, "scope": " ".join(granted)}


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _settings.jwt_signing_key, algorithms=[ALGORITHM],
                          audience=_settings.oauth_audience, issuer=ISSUER)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("The access token is not valid.") from exc


def require_scopes(*required: str):
    """FastAPI dependency factory enforcing least-privilege scope checks."""

    async def _dependency(request: Request, authorization: str | None = Header(default=None)) -> dict:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise UnauthorizedError("A Bearer access token is required.")
        claims = decode_token(authorization.split(" ", 1)[1].strip())
        held = set(claims.get("scope", "").split())
        missing = [s for s in required if s not in held]
        if missing:
            raise ForbiddenError(f"Missing required scope(s): {', '.join(missing)}")
        request.state.claims = claims
        return claims

    return _dependency


def scopes_of(claims: dict) -> Iterable[str]:
    return claims.get("scope", "").split()
