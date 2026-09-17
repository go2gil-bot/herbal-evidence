"""List the models the configured account can actually use.

    python -m app.ai.models

Exists so `AI_MODEL` is filled from the provider's live catalogue rather than
from a name someone remembered. Model names go stale; this does not.
"""

from __future__ import annotations

import asyncio
import sys

from app.ai.provider import NotConfigured, ProviderError, get_provider


async def main() -> int:
    try:
        provider = get_provider()
    except NotConfigured as exc:
        print(f"not configured: {exc.what}")
        return 2

    try:
        models = await provider.list_models()
    except ProviderError as exc:
        print(f"could not list models: {exc}")
        return 1

    print(f"{len(models)} models available to this account:\n")
    for model in models:
        print(f"  {model}")
    print("\nPut one of these in AI_MODEL in backend/.env")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
