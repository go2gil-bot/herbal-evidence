"""The AI provider seam.

One interface, chosen by `AI_PROVIDER`. Swapping vendors is a configuration
change, not a rewrite, and the rest of the codebase never imports a vendor SDK.

When no provider is configured, `get_provider()` raises `NotConfigured`. It does
not fall back to anything. There is no mock draft, because a mock draft that
reads like a finding is the one failure mode this product cannot afford.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings


class NotConfigured(Exception):
    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


class ProviderError(Exception):
    """The provider was called and did not return usable output."""


@dataclass
class DraftRequest:
    """Everything the model is allowed to see.

    Note what is absent: no name, no email, no account id, no request id. The
    provider gets the research material and nothing that identifies a person.
    """

    question: str
    herb_scientific_name: str | None
    preparation: str | None
    population: str | None
    treatment_context: str | None
    sources: list[dict] = field(default_factory=list)


@dataclass
class DraftResult:
    body: dict
    provider: str
    model: str
    prompt_version: str
    raw_usage: dict[str, Any] | None = None


class AIProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    async def generate_draft(self, request: DraftRequest) -> DraftResult: ...

    @abc.abstractmethod
    async def list_models(self) -> list[str]: ...


def get_provider(settings: Settings | None = None) -> AIProvider:
    settings = settings or get_settings()

    if settings.ai_provider in ("", "none"):
        raise NotConfigured("no AI provider configured (AI_PROVIDER)")
    if not settings.ai_api_key:
        raise NotConfigured(f"no API key for provider {settings.ai_provider!r} (AI_API_KEY)")

    if settings.ai_provider == "openai":
        from app.ai.openai_provider import OpenAIProvider

        return OpenAIProvider(settings)

    raise NotConfigured(f"unknown AI provider {settings.ai_provider!r}")
