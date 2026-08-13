"""The Run Report - everything that degraded during a Job.

This exists so the translated Track can stay clean. No markers, no annotations,
nothing on screen that was not meant to be read. Anything worth knowing about
goes here instead, keyed by timecode so it can be checked in a player.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path


class Degradation(StrEnum):
    """Kinds of thing that can go less than perfectly."""

    PASSED_THROUGH = "Passed through untranslated"
    REPAIR_EXHAUSTED = "Translation failed, source text kept"
    HARDER_THAN_SOURCE = "Harder to read than the source"
    TAG_FALLBACK = "Inline formatting simplified"


@dataclass(frozen=True, slots=True)
class Note:
    """One recorded degradation, anchored to a Cue."""

    cue_id: int
    timecode: str
    kind: Degradation
    detail: str
    text: str = ""


@dataclass(frozen=True, slots=True)
class Usage:
    """What the Job cost."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0
    cost_usd: float | None = None

    def plus(self, other: Usage) -> Usage:
        combined_cost: float | None
        if self.cost_usd is None and other.cost_usd is None:
            combined_cost = None
        else:
            combined_cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            requests=self.requests + other.requests,
            cost_usd=combined_cost,
        )


@dataclass(frozen=True, slots=True)
class RunReport:
    """The record of one Job. Built up immutably as the Job proceeds."""

    source: Path
    output: Path
    source_language: str
    target_language: str
    model: str
    total_cues: int = 0
    translated_cues: int = 0
    notes: tuple[Note, ...] = field(default_factory=tuple)
    usage: Usage = field(default_factory=Usage)

    cues_over_budget: int = 0
    """How many Cues exceed the Reading Budget at all. Most of these are
    inherited from a source that was already fast, so they are summarised
    rather than listed - only the ones we made worse become Notes."""

    reading_budget: float = 0.0

    def with_note(self, note: Note) -> RunReport:
        return replace(self, notes=self.notes + (note,))

    def with_notes(self, notes: tuple[Note, ...]) -> RunReport:
        return replace(self, notes=self.notes + notes)

    def with_budget(self, over_budget: int, budget: float) -> RunReport:
        return replace(self, cues_over_budget=over_budget, reading_budget=budget)

    def with_usage(self, usage: Usage) -> RunReport:
        return replace(self, usage=self.usage.plus(usage))

    def of_kind(self, kind: Degradation) -> tuple[Note, ...]:
        return tuple(n for n in self.notes if n.kind is kind)

    @property
    def is_clean(self) -> bool:
        return not self.notes

    def to_markdown(self) -> str:
        """Render the report. Grouped by kind, sorted by timecode within each."""
        lines = [
            f"# Translation report: {self.source.name}",
            "",
            f"- **Source:** `{self.source}`",
            f"- **Output:** `{self.output}`",
            f"- **Languages:** {self.source_language} to {self.target_language}",
            f"- **Model:** {self.model}",
            f"- **Cues:** {self.translated_cues} translated of {self.total_cues} total",
            f"- **Requests:** {self.usage.requests}",
            f"- **Tokens:** {self.usage.prompt_tokens:,} in, "
            f"{self.usage.completion_tokens:,} out",
        ]
        if self.usage.cost_usd is not None:
            lines.append(f"- **Cost:** ${self.usage.cost_usd:.4f}")
        if self.cues_over_budget:
            regressions = len(self.of_kind(Degradation.HARDER_THAN_SOURCE))
            lines.append(
                f"- **Reading speed:** {self.cues_over_budget} of "
                f"{self.total_cues} cues exceed {self.reading_budget:.0f} "
                f"chars/sec. {regressions} of those read slower than the "
                f"source did; the rest were already fast in the original. "
                f"Only the {regressions} are listed below."
            )
        lines.append("")

        if self.is_clean:
            lines += ["Nothing to report. Every Cue translated cleanly.", ""]
            return "\n".join(lines)

        for kind in Degradation:
            group = sorted(self.of_kind(kind), key=lambda n: n.cue_id)
            if not group:
                continue
            lines += [f"## {kind.value} ({len(group)})", ""]
            lines += [_format_note(note) for note in group]
            lines.append("")
        return "\n".join(lines)


def _format_note(note: Note) -> str:
    body = f"- `{note.timecode}` (cue {note.cue_id}) - {note.detail}"
    if note.text:
        body += f"\n  > {note.text.replace(chr(10), ' / ')}"
    return body
