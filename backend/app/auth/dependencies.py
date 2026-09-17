"""FastAPI dependencies for identity and role.

Role is read from the database with the service role, never from a token claim -
a client that can edit its own claims must not be able to promote itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.auth.jwt import AuthenticatedUser, InvalidToken, verify_access_token

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def current_user(authorization: Annotated[str | None, Header()] = None) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UNAUTHORIZED

    token = authorization.split(" ", 1)[1].strip()
    try:
        return verify_access_token(token)
    except InvalidToken:
        raise UNAUTHORIZED from None


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]
