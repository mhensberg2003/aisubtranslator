"""Preparing a Payload for translation, and finishing it afterwards.

This is the whole per-Cue lifecycle in one place: strip the markup the model
must not see, and on the way back re-break the lines, restore the markup, and
record anything that degraded. The pipeline and the round-trip test both go
through here, so the test exercises the real path rather than a parallel one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.cue import Cue
from ..domain.report import Degradation, Note
from ..domain.style import StylePreferences
from . import tags, wrap


#: When the source was already over budget, how much worse the translation must
#: be before it is worth reporting. Fast television is simply written that way,
#: and a Cue going from 18.5 to 19.5 chars/sec is not a finding - it is one
#: longer word. Only a clear further degradation earns a line in the report.
SIGNIFICANT_WORSENING = 0.15


@dataclass(frozen=True, slots=True)
class Finished:
    """A completed Payload, with what it earned along the way."""

    text: str
    notes: tuple[Note, ...]
    over_budget: bool
    """Whether the result exceeds the Reading Budget at all, regardless of
    whether the source did too. Counted for the report summary."""


@dataclass(frozen=True, slots=True)
class Prepared:
    """A Cue split into what the model sees and what it must not touch."""

    cue: Cue
    masked: tags.Masked

    @property
    def source_text(self) -> str:
        """What to send for translation."""
        return self.masked.text

    @property
    def is_positioned(self) -> bool:
        """Signs are pinned to a spot on screen; re-wrapping them is wrong."""
        return tags.has_positioning(self.cue.text)


def prepare(cue: Cue) -> Prepared:
    return Prepared(cue=cue, masked=tags.mask(cue.text))


def finalise(
    prepared: Prepared,
    translated: str,
    style: StylePreferences,
) -> Finished:
    """Turn a translated string back into a Payload, with any notes it earned."""
    cue = prepared.cue
    notes: list[Note] = []

    body = translated
    if not prepared.is_positioned:
        body = wrap.rewrap(
            body,
            max_line_length=style.max_line_length,
            max_lines=style.max_lines,
        )

    text, degraded = tags.restore(prepared.masked, body)
    if degraded:
        notes.append(
            Note(
                cue_id=cue.id,
                timecode=cue.timecode,
                kind=Degradation.TAG_FALLBACK,
                detail="inline formatting could not be placed and was dropped",
                text=body,
            )
        )

    translated_cps = wrap.characters_per_second(body, cue.duration_ms)
    source_cps = wrap.characters_per_second(cue.plaintext, cue.duration_ms)
    over_budget = translated_cps > style.max_cps

    if over_budget and _is_regression(translated_cps, source_cps, style.max_cps):
        notes.append(
            Note(
                cue_id=cue.id,
                timecode=cue.timecode,
                kind=Degradation.HARDER_THAN_SOURCE,
                detail=(
                    f"{translated_cps:.1f} chars/sec, up from {source_cps:.1f} "
                    f"in the source, against a budget of {style.max_cps:.0f}"
                ),
                text=body,
            )
        )

    return Finished(text=text, notes=tuple(notes), over_budget=over_budget)


def _is_regression(translated_cps: float, source_cps: float, budget: float) -> bool:
    """Whether this Cue is worth a human's attention.

    Two distinct cases qualify, and they need different thresholds:

    - The source read comfortably and the translation does not. We took a Cue
      that was fine and broke it, so any crossing counts.
    - The source was already over budget and the translation is clearly worse
      still. Here a small increase is inherited pacing plus one longer word,
      not a finding.
    """
    if source_cps <= budget:
        return True
    return translated_cps > source_cps * (1.0 + SIGNIFICANT_WORSENING)
