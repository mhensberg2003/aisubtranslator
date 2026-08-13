"""Choosing which Subtitle Track to translate.

A release commonly carries "English", "English (SDH)", "English (Forced)" and
"Signs & Songs" in one file, and they are not interchangeable. Translating the
Forced track yields forty lines; translating the Signs track yields no dialogue
at all.

Dispositions are the strongest signal but are frequently unset, so titles and
cue counts are weighed too. When the top two candidates score closely the
answer is genuinely ambiguous and the caller should ask rather than guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .probe import TrackCandidate

#: Below this margin the choice is a judgement call, not a deduction.
DECISIVE_MARGIN = 20.0

_FORCED_TITLE = re.compile(r"\bforced\b", re.IGNORECASE)
_SIGNS_TITLE = re.compile(r"\bsigns?\b|\bsongs?\b|\btypeset", re.IGNORECASE)
_SDH_TITLE = re.compile(r"\bsdh\b|\bhearing[- ]impaired\b|\bcc\b|\bclosed caption", re.IGNORECASE)
_FULL_TITLE = re.compile(r"\bfull\b|\bdialogue\b|\bcomplete\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Ranked:
    """A candidate with its score and the reasoning behind it."""

    candidate: TrackCandidate
    score: float
    reasons: tuple[str, ...]


def rank(
    candidates: tuple[TrackCandidate, ...],
    *,
    preferred_languages: tuple[str, ...] = (),
) -> tuple[Ranked, ...]:
    """Score text Tracks, best first. Image Tracks are excluded, not ranked."""
    scored = [_score(c, preferred_languages) for c in candidates if c.is_text]
    return tuple(sorted(scored, key=lambda r: r.score, reverse=True))


def is_decisive(ranked: tuple[Ranked, ...]) -> bool:
    """Whether the top candidate wins clearly enough to pick without asking."""
    if not ranked:
        return False
    if len(ranked) == 1:
        return True
    return (ranked[0].score - ranked[1].score) >= DECISIVE_MARGIN


def _score(
    candidate: TrackCandidate, preferred_languages: tuple[str, ...]
) -> Ranked:
    score = 50.0
    reasons: list[str] = []

    if preferred_languages:
        language = (candidate.language or "").lower()
        if any(language.startswith(p.lower()[:2]) for p in preferred_languages if p):
            score += 40
            reasons.append("matches the requested source language")
        elif language:
            score -= 30
            reasons.append(f"language is {language}, not what was asked for")

    if candidate.is_forced:
        score -= 45
        reasons.append("flagged forced")
    if candidate.is_hearing_impaired:
        score -= 12
        reasons.append("flagged hearing-impaired")
    if candidate.is_default:
        score += 6
        reasons.append("flagged default")

    title = candidate.title or ""
    if _FORCED_TITLE.search(title):
        score -= 45
        reasons.append("title says forced")
    if _SIGNS_TITLE.search(title):
        score -= 50
        reasons.append("title says signs or songs")
    if _SDH_TITLE.search(title):
        score -= 12
        reasons.append("title says SDH")
    if _FULL_TITLE.search(title):
        score += 10
        reasons.append("title says full dialogue")

    # A very short track on a feature-length file is forced, whatever it claims.
    if candidate.frames is not None:
        if candidate.frames < 120:
            score -= 35
            reasons.append(f"only {candidate.frames} cues")
        elif candidate.frames > 400:
            score += 10
            reasons.append(f"{candidate.frames} cues, a full track")

    return Ranked(candidate=candidate, score=score, reasons=tuple(reasons))
