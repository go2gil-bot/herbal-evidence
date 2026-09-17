"""Permitted status transitions.

The list exists so that "which states can follow which" is one table a person can
read, rather than a condition scattered across handlers. Anything not listed here
is refused.

Note what is absent: nothing transitions to `published`. Publication is a side
effect of approval, inside the approval transaction, and cannot be reached by
setting a status.
"""

from __future__ import annotations

TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"needs_clarification", "queued", "researching", "closed_out_of_scope"},
    "needs_clarification": {"queued", "researching", "closed_out_of_scope", "submitted"},
    "queued": {"researching", "needs_clarification", "closed_out_of_scope"},
    "researching": {"draft_ready", "needs_clarification", "closed_out_of_scope"},
    "draft_ready": {"in_review", "researching", "needs_clarification"},
    "in_review": {"revision_required", "draft_ready", "researching"},
    "revision_required": {"researching", "draft_ready", "needs_clarification"},
    # A published request can be reopened for an update; withdrawal does this too.
    "published": {"in_review", "researching"},
    "closed_out_of_scope": set(),
}

# Transitions only an admin may perform.
ADMIN_ONLY: set[tuple[str, str]] = {
    ("published", "in_review"),
    ("published", "researching"),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def requires_admin(current: str, target: str) -> bool:
    return (current, target) in ADMIN_ONLY
