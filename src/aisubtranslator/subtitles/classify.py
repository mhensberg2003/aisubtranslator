"""Deciding which Cues carry translatable Payload.

Not everything that is text is meant to be translated. Some of it is invisible
authoring data, some of it is timing machinery that translation would destroy,
and some of it is the release group's signature. Each rule here is conservative:
when in doubt, translate, because a needlessly translated line is a small cost
and a wrongly skipped line is a hole in the subtitles.

Every skip is recorded with its reason, so nothing disappears silently.
"""

from __future__ import annotations

import re

from ..domain.cue import Cue, PassThrough
from . import tags

#: Requires an explicit credit verb *and* a distribution marker, so ordinary
#: dialogue containing the word "subtitles" is not swallowed.
_CREDIT_VERB = re.compile(
    r"\b(?:subtitle[sd]?|subs?|sync(?:ed|hronized)?|translat(?:ed|ion)|"
    r"encoded|ripped|corrected|resync(?:ed)?|transcri(?:bed|pt))\b"
    r"\s*(?:by|:|-|—)",
    re.IGNORECASE,
)
_DISTRIBUTION = re.compile(
    r"(?:https?://|www\.|\.(?:com|org|net|info|tv)\b|opensubtitles|addic7ed|"
    r"subscene|yify|rarbg|explosiveskull)",
    re.IGNORECASE,
)

_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def classify(cue: Cue) -> PassThrough | None:
    """Why this Cue should pass through untranslated, or None to translate it."""
    if cue.is_comment:
        return PassThrough.COMMENT
    if cue.is_drawing:
        return PassThrough.DRAWING
    if tags.is_karaoke(cue.text):
        return PassThrough.KARAOKE
    if not _HAS_LETTER.search(cue.plaintext):
        return PassThrough.NO_LETTERS
    if is_credit(cue.plaintext):
        return PassThrough.CREDIT
    return None


def is_credit(plaintext: str) -> bool:
    """Whether a line is a release-group credit rather than content.

    Both a credit verb and a distribution marker are required. "Subtitles by
    OpenSubtitles.org" matches; "He translated the letter for me" does not.
    """
    return bool(_CREDIT_VERB.search(plaintext) and _DISTRIBUTION.search(plaintext))


def partition(cues: tuple[Cue, ...]) -> tuple[tuple[Cue, ...], dict[int, PassThrough]]:
    """Split Cues into those to translate and those to pass through."""
    translatable: list[Cue] = []
    skipped: dict[int, PassThrough] = {}
    for cue in cues:
        reason = classify(cue)
        if reason is None:
            translatable.append(cue)
        else:
            skipped[cue.id] = reason
    return tuple(translatable), skipped
