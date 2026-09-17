"""Token verification tests.

These run offline: the test mints its own EC keypair and serves its own JWKS, so
the checks exercise our validation rules rather than Supabase's availability.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import jwt as auth_jwt
from app.auth.jwt import InvalidToken, verify_access_token
from app.config import Settings

ISSUER = "https://project.supabase.co/auth/v1"


@pytest.fixture
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def settings():
    return Settings(supabase_url="https://project.supabase.co", app_env="dev")


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch, signing_key):
    """Serve the test's own public key instead of fetching Supabase's JWKS."""

    class _Key:
        key = signing_key.public_key()

    class _Client:
        def get_signing_key_from_jwt(self, token):
            return _Key()

    # Clear the real lru_cache before swapping it out; monkeypatch restores the
    # original afterwards, so there is nothing to clean up on the way back.
    auth_jwt._jwk_client.cache_clear()
    monkeypatch.setattr(auth_jwt, "_jwk_client", lambda url: _Client())


def make_token(signing_key, **overrides) -> str:
    claims = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 600,
        "iat": int(time.time()),
        "email": "person@example.test",
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="ES256")


def test_accepts_a_well_formed_token(signing_key, settings):
    user = verify_access_token(make_token(signing_key), settings)
    assert user.user_id == "11111111-2222-3333-4444-555555555555"
    assert user.email == "person@example.test"


def test_rejects_an_expired_token(signing_key, settings):
    token = make_token(signing_key, exp=int(time.time()) - 60)
    with pytest.raises(InvalidToken):
        verify_access_token(token, settings)


def test_rejects_a_foreign_issuer(signing_key, settings):
    token = make_token(signing_key, iss="https://attacker.example/auth/v1")
    with pytest.raises(InvalidToken):
        verify_access_token(token, settings)


def test_rejects_a_wrong_audience(signing_key, settings):
    token = make_token(signing_key, aud="anon")
    with pytest.raises(InvalidToken):
        verify_access_token(token, settings)


def test_rejects_a_token_signed_by_another_key(settings):
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(InvalidToken):
        verify_access_token(make_token(other), settings)


def test_rejects_an_unsigned_token(settings):
    token = jwt.encode(
        {"sub": "x", "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60},
        key="",
        algorithm="none",
    )
    with pytest.raises(InvalidToken):
        verify_access_token(token, settings)


def test_repr_does_not_leak_the_whole_user_id(signing_key, settings):
    user = verify_access_token(make_token(signing_key), settings)
    assert user.user_id not in repr(user)
