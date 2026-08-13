"""Masking and restoring Override Tags.

Override Tags carry presentation, not meaning, so the model should never see
them - it has no reason to translate `{\\pos(320,50)}` and every opportunity to
corrupt it. We strip them out, translate what remains, and put them back.

Two cases are handled without any risk at all, because they cover most real
subtitles: tags that sit entirely before the text, and a single tag closing the
line at the end. Only genuinely interleaved tags need sentinels in the text the
model sees, and if those come back wrong we fall back to dropping the inline
formatting rather than emitting a corrupt file.

Sentinels are single Unicode Private Use Area codepoints. Single characters
cannot be split apart mid-token, and PUA codepoints do not occur in real
subtitle text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PUA_START = 0xE000
_MAX_INLINE_TAGS = 128

#: Override blocks, and the bare escapes ASS allows outside braces.
_TOKEN = re.compile(r"(\{[^}]*\}|\\N|\\n|\\h)")

#: Tags that place a Cue somewhere specific on screen. Re-wrapping these is
#: usually wrong - they are signs, not dialogue.
_POSITIONING = re.compile(r"\\(?:pos|move|an|a\d|org|clip|iclip)\b|\\an\d")

_LINE_BREAKS = {"\\N", "\\n"}


@dataclass(frozen=True, slots=True)
class Masked:
    """A Payload split into what the model sees and what it must not touch."""

    text: str
    """Translatable text. Real newlines for line breaks, sentinels for inline tags."""

    leading: str
    """Tags preceding all text. Re-applied verbatim; never sent to the model."""

    trailing: str
    """A single tag closing the line. Re-applied verbatim; never sent."""

    inline: tuple[str, ...]
    """Interleaved tags, indexed by sentinel offset."""

    @property
    def sentinels(self) -> frozenset[str]:
        return frozenset(_sentinel(i) for i in range(len(self.inline)))

    @property
    def is_riskless(self) -> bool:
        """True when restoration cannot fail, because nothing is interleaved."""
        return not self.inline


def _sentinel(index: int) -> str:
    return chr(_PUA_START + index)


def has_positioning(raw: str) -> bool:
    """Whether the Payload pins itself to a screen position."""
    return bool(_POSITIONING.search(raw))


def is_karaoke(raw: str) -> bool:
    """Whether the Payload uses karaoke timing, which subdivides syllables.

    Translating these destroys the syllable alignment, so they pass through.
    """
    return bool(re.search(r"\\[kK][fof]?\d", raw))


def mask(raw: str) -> Masked:
    """Split a raw Payload into translatable text and untouchable markup."""
    tokens = [t for t in _TOKEN.split(raw) if t]

    leading_parts: list[str] = []
    body: list[str] = []
    seen_text = False
    for token in tokens:
        is_markup = token.startswith("{") or token == "\\h"
        if not seen_text and is_markup:
            leading_parts.append(token)
            continue
        if token.strip() and token not in _LINE_BREAKS:
            seen_text = True
        body.append(token)

    trailing = ""
    if body and body[-1].startswith("{"):
        trailing = body.pop()

    inline: list[str] = []
    rendered: list[str] = []
    for token in body:
        if token in _LINE_BREAKS:
            rendered.append("\n")
        elif token.startswith("{") or token == "\\h":
            if len(inline) >= _MAX_INLINE_TAGS:
                # Pathological input. Drop the tag rather than run out of
                # sentinels; the fallback path reports it.
                continue
            rendered.append(_sentinel(len(inline)))
            inline.append(token)
        else:
            rendered.append(token)

    return Masked(
        text="".join(rendered),
        leading="".join(leading_parts),
        trailing=trailing,
        inline=tuple(inline),
    )


def restore(masked: Masked, translated: str) -> tuple[str, bool]:
    """Reassemble a Payload from translated text.

    Returns the Payload and whether inline formatting had to be dropped. A
    dropped tag is a reported degradation, never a corrupt file.
    """
    expected = masked.sentinels
    degraded = False

    if expected:
        found = [c for c in translated if _is_sentinel(c)]
        if sorted(found) != sorted(expected):
            translated = "".join(c for c in translated if not _is_sentinel(c))
            degraded = True
        else:
            for index, tag in enumerate(masked.inline):
                translated = translated.replace(_sentinel(index), tag)

    # Any stray sentinel the model invented must not reach the file.
    translated = "".join(c for c in translated if not _is_sentinel(c))
    body = translated.replace("\n", "\\N")
    return f"{masked.leading}{body}{masked.trailing}", degraded


def _is_sentinel(char: str) -> bool:
    return _PUA_START <= ord(char) < _PUA_START + _MAX_INLINE_TAGS
