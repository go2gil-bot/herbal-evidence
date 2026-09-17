"""OpenAI adapter.

Talks to the Chat Completions endpoint over plain HTTP - no vendor SDK, so the
seam in `provider.py` stays the only place that knows a vendor exists.

The model is not hardcoded. `AI_MODEL` decides, and `list_models()` exists so the
account's actual catalogue can be read instead of a name being guessed from
memory and going stale.
"""

from __future__ import annotations

import json
import logging

import httpx
from pydantic import ValidationError

from app.ai.prompts import PROMPT_VERSION, SYSTEM, build_user_message
from app.ai.provider import AIProvider, DraftRequest, DraftResult, NotConfigured, ProviderError
from app.ai.schema import DraftBody, RESPONSE_JSON_SCHEMA, validate_claims_cite_supplied_sources
from app.config import Settings

logger = logging.getLogger("herbal_evidence.ai.openai")

BASE_URL = "https://api.openai.com/v1"
TIMEOUT_SECONDS = 120.0


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if not settings.ai_api_key:
            raise NotConfigured("AI_API_KEY is empty")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.ai_api_key}",
            "Content-Type": "application/json",
        }

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{BASE_URL}/models", headers=self._headers())
        if response.status_code >= 400:
            raise ProviderError(f"models request returned {response.status_code}")
        return sorted(item["id"] for item in response.json().get("data", []))

    async def generate_draft(self, request: DraftRequest) -> DraftResult:
        model = self._settings.ai_model
        if not model:
            raise NotConfigured("AI_MODEL is empty; run `python -m app.ai.models` to see the options")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": build_user_message(request)},
            ],
            # The model is told the shape; it does not have to infer it.
            "response_format": {"type": "json_schema", "json_schema": RESPONSE_JSON_SCHEMA},
        }

        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(
                    f"{BASE_URL}/chat/completions", headers=self._headers(), json=payload
                )
            except httpx.HTTPError as exc:
                raise ProviderError(f"{type(exc).__name__}: {exc}") from exc

        if response.status_code >= 400:
            # The body can quote the prompt, so only the status and the error
            # type are logged - never the request content.
            detail = ""
            try:
                detail = (response.json().get("error") or {}).get("type", "")
            except ValueError:
                pass
            raise ProviderError(f"provider returned {response.status_code} {detail}".strip())

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError("provider returned an unexpected envelope") from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError("provider did not return JSON") from exc

        try:
            body = DraftBody.model_validate(parsed)
        except ValidationError as exc:
            # A draft that breaks the contract is discarded. It is never saved
            # "for a researcher to fix", because a plausible wrong draft is the
            # expensive kind of wrong.
            raise ProviderError(f"draft failed validation: {exc.error_count()} problems") from exc

        allowed_ids = {str(source.get("id")) for source in request.sources if source.get("id")}
        try:
            validate_claims_cite_supplied_sources(body, allowed_ids)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

        return DraftResult(
            body=body.model_dump(),
            provider=self.name,
            model=model,
            prompt_version=PROMPT_VERSION,
            raw_usage=data.get("usage"),
        )
