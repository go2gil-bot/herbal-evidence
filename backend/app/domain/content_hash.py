"""Canonical hash of a draft body.

Approval binds to one exact version of the content. That only works if the same
content always hashes the same way, so the body is serialised canonically: keys
sorted, no insignificant whitespace, UTF-8 as itself rather than escaped.

Two bodies that differ only in key order are the same draft. Two bodies that
differ in a single character are not, and approving the stale one fails.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(body: Any) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(body: Any) -> str:
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
