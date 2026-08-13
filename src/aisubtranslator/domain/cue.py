"""Cue - the atomic unit of a Subtitle Track.

A Cue's timing and identity are immutable through translation; see
docs/adr/0001-cue-structure-is-immutable.md. Nothing in this package provides
a way to change them, which is deliberate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PassThrough(StrEnum):
    """Why a Cue's text was emitted verbatim instead of translated.

    Every value here appears in the Run Report, so the strings are written to
    be read by a person.
    """

    COMMENT = "authoring comment, never displayed"
    DRAWING = "vector drawing commands, not text"
    KARAOKE = "karaoke timing subdivides syllables"
    NO_LETTERS = "contains no letters to translate"
    CREDIT = "release-group credit line"
    TRANSLATION_FAILED = "translation failed after repair, source text kept"


@dataclass(frozen=True, slots=True)
class Cue:
    """One timed unit of subtitle.

    `text` is the raw payload in pysubs2's normalised form, which uses ASS
    override tags regardless of the source format. `plaintext` is the same
    content with markup removed - useful for classification and for the Bible
    pass, but lossy, so never a basis for writing the file back out. `id` is
    the Cue's position in the Track and is what the model echoes back to prove
    Alignment.
    """

    id: int
    start_ms: int
    end_ms: int
    text: str
    plaintext: str
    style: str
    is_comment: bool
    is_drawing: bool

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def timecode(self) -> str:
        """Human-readable start time, for jumping to a Cue in a player."""
        total_seconds, milliseconds = divmod(max(0, self.start_ms), 1000)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


@dataclass(frozen=True, slots=True)
class Track:
    """A time-ordered sequence of Cues in a single language.

    Holds the Cues only. The presentation data needed to write the file back
    out (script info, styles, per-event fields) stays with the loader, which
    owns the round-trip.
    """

    cues: tuple[Cue, ...]
    source_format: str
    language: str | None = None

    def __len__(self) -> int:
        return len(self.cues)

    def by_id(self) -> dict[int, Cue]:
        return {cue.id: cue for cue in self.cues}
