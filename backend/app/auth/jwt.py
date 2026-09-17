"""Supabase access-token verification.

Supabase signs user access tokens asymmetrically (ES256) and publishes the public
keys at `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. The backend verifies the
signature against that JWKS and checks issuer, audience and expiry explicitly -
an unverified `sub` is not an identity.

The publishable and service-role API keys are a different thing entirely: they are
HS256 project keys, not user tokens, and are rejected here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient

from app.config import Settings, get_settings

logger = logging.getLogger("herbal_evidence.auth")

# Supabase issues user tokens with this audience.
EXPECTED_AUDIENCE = "authenticated"
ALLOWED_ALGORITHMS = ["ES256", "RS256"]


class InvalidToken(Exception):
    """The token is missing, malformed, expired, or not ours."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str | None
    session_id: str | None

    def __repr__(self) -> str:  # keep ids out of accidental log lines
        return f"AuthenticatedUser(user_id={self.user_id[:8]}...)"


def issuer_for(settings: Settings) -> str:
    if settings.supabase_jwt_issuer:
        return settings.supabase_jwt_issuer.rstrip("/")
    if not settings.supabase_url:
        raise InvalidToken("no Supabase URL configured")
    return f"{settings.supabase_url.rstrip('/')}/auth/v1"


@lru_cache(maxsize=4)
def _jwk_client(jwks_url: str) -> PyJWKClient:
    # PyJWKClient caches keys and refetches on an unknown kid, so key rotation
    # does not need a redeploy.
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=600)


def verify_access_token(token: str, settings: Settings | None = None) -> AuthenticatedUser:
    settings = settings or get_settings()
    issuer = issuer_for(settings)

    if not token:
        raise InvalidToken("empty token")

    try:
        signing_key = _jwk_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token)
    except Exception as exc:  # network failure or unknown kid
        raise InvalidToken("could not resolve a signing key") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALLOWED_ALGORITHMS,
            audience=EXPECTED_AUDIENCE,
            issuer=issuer,
            options={"require": ["exp", "sub", "aud", "iss"], "verify_exp": True},
        )
    except jwt.PyJWTError as exc:
        # The reason is useful to us and useless to an attacker, so it is logged
        # without the token itself.
        logger.info("rejected access token: %s", type(exc).__name__)
        raise InvalidToken(str(exc)) from exc

    subject = claims.get("sub")
    if not subject:
        raise InvalidToken("token has no subject")

    return AuthenticatedUser(
        user_id=subject,
        email=claims.get("email"),
        session_id=claims.get("session_id"),
    )
