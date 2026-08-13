"""The OpenRouter client.

Routing is pinned rather than left to fail over; see
docs/adr/0003-openrouter-routing-is-pinned.md. Concretely that means
`require_parameters` so we only reach upstreams that honour the response
schema, `only` plus `allow_fallbacks: false` so the prompt cache and the schema
guarantees stay put for the whole Job.

Schema enforcement here is belt, not braces. The response is still validated
against the requested ids by the Alignment check, because enforcement varies
between upstreams and a returned id is not the same thing as a correct one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from ..domain.bible import Bible, Entry
from ..domain.report import Usage
from ..errors import ProviderError
from . import prompts
from .provider import Batch, Line, Response

#: OpenRouter provider slugs for model authors whose slug differs from the
#: prefix in the model id. Anything not listed falls back to the prefix.
_FIRST_PARTY_SLUG = {
    "google": "google-ai-studio",
    "meta-llama": "meta",
    "qwen": "alibaba",
}

_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


def first_party_slug(model: str) -> str:
    """The upstream slug to pin to, derived from the model id."""
    author = model.split("/", 1)[0].lower()
    return _FIRST_PARTY_SLUG.get(author, author)


@dataclass
class OpenRouterProvider:
    """Translates Batches through OpenRouter."""

    api_key: str
    model: str
    client: httpx.AsyncClient
    base_url: str = "https://openrouter.ai/api/v1"
    provider_slug: str | None = None
    pin_routing: bool = True
    max_retries: int = 3

    @property
    def name(self) -> str:
        return f"openrouter:{self.model}"

    async def translate(self, batch: Batch) -> Response:
        blocks = prompts.system_blocks(batch)
        content = await self._complete(
            system=blocks,
            user=prompts.user_message(batch),
            schema=prompts.TRANSLATION_SCHEMA,
            schema_name="subtitle_translation",
        )
        payload, usage = content
        lines = {
            int(item["id"]): str(item["text"])
            for item in payload.get("lines", [])
            if isinstance(item, dict) and "id" in item and "text" in item
        }
        return Response(lines=lines, usage=usage)

    async def derive_bible(
        self,
        sample: Sequence[Line],
        *,
        source_language: str,
        target_language: str,
    ) -> tuple[Bible, Usage]:
        payload, usage = await self._complete(
            system=(prompts.Block(prompts.SYSTEM_CORE, cache=True),),
            user=prompts.bible_message(tuple(sample), target_language=target_language),
            schema=prompts.BIBLE_SCHEMA,
            schema_name="translation_bible",
        )
        bible = Bible(
            target_language=target_language,
            genre=str(payload.get("genre", "")),
            source_register=str(payload.get("source_register", "")),
            summary=str(payload.get("summary", "")),
            characters=_entries(payload.get("characters")),
            terms=_entries(payload.get("terms")),
            notes=tuple(str(n) for n in payload.get("notes", []) if str(n).strip()),
        )
        return bible, usage

    # ----------------------------------------------------------------------

    async def _complete(
        self,
        *,
        system: Sequence[prompts.Block],
        user: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> tuple[dict[str, Any], Usage]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": [_block(b) for b in system]},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        if self.pin_routing:
            slug = self.provider_slug or first_party_slug(self.model)
            body["provider"] = {
                "require_parameters": True,
                "only": [slug],
                "allow_fallbacks": False,
            }

        data = await self._post(body)
        return _parse_content(data), _usage(data)

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST with bounded retries on transient failures only."""
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "HTTP-Referer": "https://github.com/local/aisubtranslator",
                        "X-Title": "aisubtranslator",
                    },
                    json=body,
                )
            except httpx.HTTPError as exc:
                last = exc
                await asyncio.sleep(_backoff(attempt))
                continue

            if response.status_code in _RETRYABLE_STATUS:
                last = ProviderError(
                    f"OpenRouter returned {response.status_code}: {response.text[:300]}"
                )
                await asyncio.sleep(_retry_after(response, attempt))
                continue
            if response.status_code >= 400:
                raise ProviderError(
                    f"OpenRouter rejected the request "
                    f"({response.status_code}): {response.text[:500]}",
                    hint=_hint_for(response.status_code),
                )
            return response.json()

        raise ProviderError(
            f"OpenRouter did not respond successfully after {self.max_retries} "
            f"attempts: {last}"
        )


def _block(block: prompts.Block) -> dict[str, Any]:
    part: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        part["cache_control"] = {"type": "ephemeral"}
    return part


def _parse_content(data: dict[str, Any]) -> dict[str, Any]:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"Unexpected response shape from OpenRouter: {data}") from exc

    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            f"OpenRouter returned content that is not JSON: {str(content)[:300]}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ProviderError("Expected a JSON object from the model.")
    return parsed


def _usage(data: dict[str, Any]) -> Usage:
    raw = data.get("usage") or {}
    return Usage(
        prompt_tokens=int(raw.get("prompt_tokens", 0) or 0),
        completion_tokens=int(raw.get("completion_tokens", 0) or 0),
        requests=1,
        cost_usd=float(raw["cost"]) if raw.get("cost") is not None else None,
    )


def _entries(raw: Any) -> tuple[Entry, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(
        Entry(
            source=str(item.get("source", "")),
            target=str(item.get("target", "")),
            note=str(item.get("note", "")),
        )
        for item in raw
        if isinstance(item, dict) and str(item.get("source", "")).strip()
    )


def _backoff(attempt: int) -> float:
    return min(8.0, 1.5 * (2**attempt))


def _retry_after(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(30.0, float(header))
        except ValueError:
            pass
    return _backoff(attempt)


def _hint_for(status: int) -> str | None:
    if status == 401:
        return "Check OPENROUTER_API_KEY."
    if status == 402:
        return "Your OpenRouter balance is exhausted. Rerunning resumes where it stopped."
    if status == 404:
        return (
            "That model id was not found, or no pinned upstream serves it with "
            "structured outputs. Try --no-pin-routing to widen routing."
        )
    return None
