"""Thin PostgREST client that runs as the service role.

The service role bypasses RLS. That is the point - and the danger. Nothing in this
module decides who may see what; callers pass explicit filters and the API layer
is responsible for authorization. Every function here is named so it is obvious
which scope it is operating in.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger("herbal_evidence.supabase")


class SupabaseError(RuntimeError):
    """PostgREST answered with an error. Carries status, not user content."""

    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class SupabaseClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not (self._settings.supabase_url and self._settings.supabase_secret_key):
            raise RuntimeError("Supabase URL and secret key are required")
        self._base = f"{self._settings.supabase_url.rstrip('/')}/rest/v1"
        self._key = self._settings.supabase_secret_key

    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        url = f"{self._base}/{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method, url, params=params, json=json, headers=self._headers(prefer)
            )

        if response.status_code >= 400:
            body: dict[str, Any] = {}
            try:
                body = response.json()
            except ValueError:
                pass
            # The message may quote a column name; it never quotes user content,
            # and it is not forwarded to the browser verbatim.
            logger.warning(
                "postgrest %s %s -> %s (%s)",
                method,
                path,
                response.status_code,
                body.get("code"),
            )
            raise SupabaseError(
                response.status_code, body.get("code"), body.get("message", "database error")
            )

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": columns}
        params.update(filters or {})
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        return await self._send("GET", table, params=params) or []

    async def insert(self, table: str, row: dict[str, Any], *, columns: str = "*") -> dict[str, Any]:
        rows = await self._send(
            "POST",
            table,
            params={"select": columns},
            json=row,
            prefer="return=representation",
        )
        return rows[0]

    async def update(
        self, table: str, *, filters: dict[str, str], values: dict[str, Any], columns: str = "*"
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": columns}
        params.update(filters)
        return await self._send(
            "PATCH", table, params=params, json=values, prefer="return=representation"
        ) or []

    async def rpc(self, function: str, args: dict[str, Any]) -> Any:
        return await self._send("POST", f"rpc/{function}", json=args)


def get_supabase() -> SupabaseClient:
    return SupabaseClient()
