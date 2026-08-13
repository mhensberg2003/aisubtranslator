"""Prompt construction and the response schemas.

The system prompt is split into a static part and a per-Work part. The static
part is identical for every request in every Job and the per-Work part is
identical for every Chunk of a Work, so both are marked cacheable - which is
where the cost of carrying the Bible into every request goes away.

Input is sent as JSON rather than numbered lines because Payloads contain
newlines, and a numbered-line format cannot represent those unambiguously.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .provider import Batch, Line

#: The sentinel range used by tag masking, described so the model preserves it.
_SENTINEL_NOTE = (
    "Some texts contain placeholder characters in the Unicode Private Use Area "
    "(U+E000 and upward). Each one stands for formatting that must survive. "
    "Reproduce every placeholder exactly once, positioned where the target "
    "language needs it. Never invent, drop, or duplicate one."
)

SYSTEM_CORE = f"""\
You translate subtitles for viewers watching the film or programme.

The output is read in a few seconds while people are also watching a picture,
so it must be idiomatic, natural and compact. Translate what the line means to
someone watching, not what the words say individually.

Absolute rules:

1. Return exactly one entry for every id given to you, and no others. Never
   merge two lines into one, never split one into two, never drop a line,
   never renumber, never reorder. Line breaks and timings are fixed and are
   not yours to change.
2. If a sentence runs across several lines, translate it as a whole and then
   distribute it across those same lines, keeping each line's share roughly
   where the original had it.
3. Never leave a line empty. If a line is a single word, an interjection or a
   sound, translate it as such.
4. Do not add notes, explanations, romanisation, or bracketed glosses. Nothing
   goes on screen that was not on screen before.
5. Do not translate the context lines. They are there so you can see what is
   being said around the lines you are translating.

{_SENTINEL_NOTE}
"""

TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}

BIBLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "genre": {"type": "string"},
        "source_register": {"type": "string"},
        "summary": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["source", "target", "note"],
                "additionalProperties": False,
            },
        },
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["source", "target", "note"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["genre", "source_register", "summary", "characters", "terms", "notes"],
    "additionalProperties": False,
}

BIBLE_INSTRUCTIONS = """\
You are preparing to translate a film or episode into {target}. First, read the
subtitles below and build a short reference sheet, so that terminology stays
consistent across the whole thing and across later episodes.

Record:
- genre and tone, in a few words
- the register of the source: how formal, how modern, who is speaking to whom
- a one-sentence premise, enough to disambiguate words with several meanings
- every recurring character name, with the rendering to use in {target}
- recurring terms, titles, places, invented words and catchphrases that must be
  translated the same way every time
- notes on anything a translator would otherwise get wrong

Only include names and terms that actually recur or actually matter. A short,
accurate sheet is far more useful than an exhaustive one.
"""


@dataclass(frozen=True, slots=True)
class Block:
    """A piece of system prompt, optionally marked for caching."""

    text: str
    cache: bool = False


def system_blocks(batch: Batch) -> tuple[Block, ...]:
    """Build the system prompt, split so the stable parts can be cached.

    Both blocks are identical across every Chunk of a Work, which is what makes
    caching worth requesting - see
    docs/adr/0003-openrouter-routing-is-pinned.md for why the cache must not
    move between upstreams mid-Job.
    """
    guidance = [
        f"Translate from {batch.source_language} into {batch.target_language}.",
        "",
        "Target-language conventions:",
        batch.style.to_prompt(),
    ]
    bible = batch.bible.to_prompt()
    if bible:
        guidance += ["", "Reference sheet for this title:", bible]

    return (
        Block(SYSTEM_CORE, cache=True),
        Block("\n".join(guidance), cache=True),
    )


def user_message(batch: Batch) -> str:
    """The Chunk itself, as JSON, with the Alignment requirement restated."""
    payload = {
        "context_before": [_line(line) for line in batch.before],
        "translate": [_line(line) for line in batch.lines],
        "context_after": [_line(line) for line in batch.after],
    }
    ids = batch.ids
    requirement = (
        f"Return exactly {len(ids)} entries, one for each of these ids: "
        f"{list(ids)}. No others."
    )
    return f"{json.dumps(payload, ensure_ascii=False, indent=1)}\n\n{requirement}"


def bible_message(sample: tuple[Line, ...], *, target_language: str) -> str:
    lines = [line.text for line in sample]
    return (
        f"{BIBLE_INSTRUCTIONS.format(target=target_language)}\n\n"
        f"Subtitles:\n\n" + "\n".join(lines)
    )


def _line(line: Line) -> dict[str, Any]:
    return {"id": line.id, "text": line.text}
