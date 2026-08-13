"""The OpenRouter client, against a mock transport.

No network and no API key. What is being checked is the request we build - the
routing pin and the cache breakpoints are the two things that quietly stop
working without anything failing - and that malformed responses become clear
errors rather than corrupt output.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from aisubtranslator.errors import ProviderError
from aisubtranslator.translate.openrouter import OpenRouterProvider, first_party_slug
from aisubtranslator.translate.provider import Batch, Line

MODEL = "anthropic/claude-sonnet-4.5"


def make_batch() -> Batch:
    return Batch(lines=(Line(id=0, text="Hello"), Line(id=1, text="Goodbye")))


def completion(payload: dict[str, Any], usage: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": usage
        or {"prompt_tokens": 120, "completion_tokens": 30, "cost": 0.0021},
    }


def provider_with(handler) -> tuple[OpenRouterProvider, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    return (
        OpenRouterProvider(api_key="test-key", model=MODEL, client=client),
        seen,
    )


async def test_a_translation_is_parsed_into_lines() -> None:
    provider, _ = provider_with(
        lambda _: httpx.Response(
            200, json=completion({"lines": [{"id": 0, "text": "Hej"}, {"id": 1, "text": "Farvel"}]})
        )
    )
    response = await provider.translate(make_batch())

    assert response.lines == {0: "Hej", 1: "Farvel"}
    assert response.usage.prompt_tokens == 120
    assert response.usage.cost_usd == pytest.approx(0.0021)
    assert response.usage.requests == 1


async def test_routing_is_pinned() -> None:
    """The whole point of ADR 0003; easy to lose without noticing."""
    provider, seen = provider_with(
        lambda _: httpx.Response(200, json=completion({"lines": []}))
    )
    await provider.translate(make_batch())

    routing = seen[0]["provider"]
    assert routing["require_parameters"] is True
    assert routing["only"] == ["anthropic"]
    assert routing["allow_fallbacks"] is False


async def test_routing_can_be_widened() -> None:
    provider, seen = provider_with(
        lambda _: httpx.Response(200, json=completion({"lines": []}))
    )
    provider.pin_routing = False
    await provider.translate(make_batch())
    assert "provider" not in seen[0]


async def test_the_stable_prompt_is_marked_cacheable() -> None:
    """Cache breakpoints are what make carrying the Bible per-Chunk affordable."""
    provider, seen = provider_with(
        lambda _: httpx.Response(200, json=completion({"lines": []}))
    )
    await provider.translate(make_batch())

    system = seen[0]["messages"][0]["content"]
    assert all(block["cache_control"] == {"type": "ephemeral"} for block in system)


async def test_the_schema_is_requested_strictly() -> None:
    provider, seen = provider_with(
        lambda _: httpx.Response(200, json=completion({"lines": []}))
    )
    await provider.translate(make_batch())

    schema = seen[0]["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert "lines" in schema["schema"]["properties"]


async def test_the_chunk_ids_are_stated_explicitly() -> None:
    provider, seen = provider_with(
        lambda _: httpx.Response(200, json=completion({"lines": []}))
    )
    await provider.translate(make_batch())
    assert "[0, 1]" in seen[0]["messages"][1]["content"]


async def test_context_cues_are_labelled_separately() -> None:
    provider, seen = provider_with(
        lambda _: httpx.Response(200, json=completion({"lines": []}))
    )
    batch = Batch(lines=(Line(id=5, text="mid"),), before=(Line(id=4, text="prev"),))
    await provider.translate(batch)

    content = json.loads(seen[0]["messages"][1]["content"].split("\n\nReturn")[0])
    assert content["context_before"] == [{"id": 4, "text": "prev"}]
    assert content["translate"] == [{"id": 5, "text": "mid"}]


async def test_content_returned_as_parts_is_handled() -> None:
    payload = {"lines": [{"id": 0, "text": "Hej"}]}
    provider, _ = provider_with(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
                ],
                "usage": {},
            },
        )
    )
    assert (await provider.translate(make_batch())).lines == {0: "Hej"}


async def test_non_json_content_is_a_clear_error() -> None:
    provider, _ = provider_with(
        lambda _: httpx.Response(
            200, json={"choices": [{"message": {"content": "sorry, I can't"}}]}
        )
    )
    with pytest.raises(ProviderError, match="not JSON"):
        await provider.translate(make_batch())


async def test_an_unexpected_response_shape_is_a_clear_error() -> None:
    provider, _ = provider_with(lambda _: httpx.Response(200, json={"nope": True}))
    with pytest.raises(ProviderError, match="Unexpected response shape"):
        await provider.translate(make_batch())


async def test_a_bad_key_says_so() -> None:
    provider, _ = provider_with(lambda _: httpx.Response(401, text="no"))
    with pytest.raises(ProviderError) as caught:
        await provider.translate(make_batch())
    assert caught.value.hint is not None
    assert "OPENROUTER_API_KEY" in caught.value.hint


async def test_an_exhausted_balance_mentions_resuming() -> None:
    """The user needs to know the run is not lost."""
    provider, _ = provider_with(lambda _: httpx.Response(402, text="no credit"))
    with pytest.raises(ProviderError) as caught:
        await provider.translate(make_batch())
    assert caught.value.hint is not None
    assert "resumes" in caught.value.hint


async def test_rate_limits_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    attempts = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json=completion({"lines": [{"id": 0, "text": "Hej"}]}))

    provider, _ = provider_with(handler)
    assert (await provider.translate(make_batch())).lines == {0: "Hej"}
    assert attempts["n"] == 3


async def test_persistent_failure_gives_up_rather_than_looping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    provider, seen = provider_with(lambda _: httpx.Response(503, text="down"))
    with pytest.raises(ProviderError, match="did not respond successfully"):
        await provider.translate(make_batch())
    assert len(seen) == provider.max_retries


async def test_a_bible_is_parsed() -> None:
    payload = {
        "genre": "noir",
        "source_register": "clipped",
        "summary": "A caper.",
        "characters": [{"source": "Anya", "target": "Anja", "note": ""}],
        "terms": [{"source": "The Order", "target": "Ordenen", "note": "keep"}],
        "notes": ["Narration is past tense.", "  "],
    }
    provider, _ = provider_with(lambda _: httpx.Response(200, json=completion(payload)))
    bible, usage = await provider.derive_bible(
        [Line(id=0, text="Hello")], source_language="English", target_language="Danish"
    )

    assert bible.genre == "noir"
    assert bible.characters[0].target == "Anja"
    assert bible.notes == ("Narration is past tense.",)
    assert usage.requests == 1


async def test_entries_without_a_source_are_discarded() -> None:
    payload = {
        "genre": "", "source_register": "", "summary": "",
        "characters": [{"source": "  ", "target": "x", "note": ""}],
        "terms": [], "notes": [],
    }
    provider, _ = provider_with(lambda _: httpx.Response(200, json=completion(payload)))
    bible, _ = await provider.derive_bible(
        [], source_language="English", target_language="Danish"
    )
    assert bible.characters == ()


@pytest.mark.parametrize(
    ("model", "slug"),
    [
        ("anthropic/claude-sonnet-4.5", "anthropic"),
        ("openai/gpt-5", "openai"),
        ("google/gemini-2.5-flash", "google-ai-studio"),
        ("meta-llama/llama-4", "meta"),
    ],
)
def test_first_party_slugs(model: str, slug: str) -> None:
    assert first_party_slug(model) == slug


async def _no_sleep(_seconds: float) -> None:
    return None
