"""Staff role checks.

Role is read from `user_roles` with the service role - never from a token claim.
A client that can craft its own claims must gain nothing by adding `role: admin`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import CurrentUser
from app.auth.jwt import AuthenticatedUser
from app.services.supabase_client import SupabaseClient, get_supabase

FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail={"code": "forbidden", "message": "אין הרשאה לפעולה הזו"},
)


@dataclass(frozen=True)
class StaffMember:
    user_id: str
    roles: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_researcher(self) -> bool:
        return "researcher" in self.roles


async def _roles_for(client: SupabaseClient, user_id: str) -> frozenset[str]:
    rows = await client.select(
        "user_roles", columns="role", filters={"user_id": f"eq.{user_id}"}
    )
    return frozenset(row["role"] for row in rows)


async def current_staff(
    user: CurrentUser,
    client: Annotated[SupabaseClient, Depends(get_supabase)],
) -> StaffMember:
    roles = await _roles_for(client, user.user_id)
    if not roles:
        raise FORBIDDEN
    return StaffMember(user_id=user.user_id, roles=roles)


async def current_admin(staff: Annotated[StaffMember, Depends(current_staff)]) -> StaffMember:
    if not staff.is_admin:
        raise FORBIDDEN
    return staff


CurrentStaff = Annotated[StaffMember, Depends(current_staff)]
CurrentAdmin = Annotated[StaffMember, Depends(current_admin)]


def scope_filter(staff: StaffMember) -> dict[str, str]:
    """Which requests this person may work on.

    Default for a researcher is what is assigned to them; an admin manages the
    whole queue. Widening a researcher's scope is a product decision, so it
    happens here and nowhere else.
    """
    if staff.is_admin:
        return {}
    return {"assigned_researcher_id": f"eq.{staff.user_id}"}


def ensure_in_scope(staff: StaffMember, request_row: dict) -> None:
    if staff.is_admin:
        return
    if request_row.get("assigned_researcher_id") != staff.user_id:
        raise FORBIDDEN


__all__ = [
    "AuthenticatedUser",
    "CurrentAdmin",
    "CurrentStaff",
    "FORBIDDEN",
    "StaffMember",
    "current_admin",
    "current_staff",
    "ensure_in_scope",
    "scope_filter",
]
