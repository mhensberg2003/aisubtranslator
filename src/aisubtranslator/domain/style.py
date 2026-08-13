"""Style Preferences - the conventions declared for the Target Language.

Distinct from the Bible, which describes the register *observed* in the source.
This file describes what the output should be like; the Bible describes what
the input is like.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field


class StylePreferences(BaseModel):
    """Target-language conventions. Edited once, applied everywhere.

    Defaults are tuned for Danish subtitles for personal viewing: modern
    du-form, profanity kept at the intensity the source used rather than
    softened the way broadcast subtitling traditionally does.
    """

    model_config = {"frozen": True}

    formality: str = Field(
        default="informal du-form throughout; De-form only if the source is "
        "explicitly period or ceremonial",
        description="How to handle second-person address and register.",
    )
    profanity: str = Field(
        default="preserve at equivalent intensity; do not soften or censor",
        description="Whether swearing is toned down.",
    )
    idioms: str = Field(
        default="domesticate to what a native speaker would actually say, "
        "rather than translating literally",
        description="Literal versus domesticated rendering of figurative language.",
    )
    proper_nouns: str = Field(
        default="leave names of people, places and brands unchanged",
        description="Whether to localise names.",
    )
    units: str = Field(
        default="leave measurements as spoken; do not convert",
        description="Whether to convert units of measurement.",
    )
    extra_notes: tuple[str, ...] = Field(
        default=(),
        description="Free-form instructions appended verbatim to the prompt.",
    )

    max_line_length: int = Field(
        default=42, description="Characters per line before re-wrapping."
    )
    max_lines: int = Field(default=2, description="Maximum lines shown per Cue.")
    max_cps: float = Field(
        default=17.0,
        description="Reading Budget in characters per second. Exceeding it is "
        "reported, never corrected by truncation.",
    )

    def to_prompt(self) -> str:
        """Render as instructions for the translation prompt."""
        lines = [
            f"- Formality: {self.formality}",
            f"- Profanity: {self.profanity}",
            f"- Idioms: {self.idioms}",
            f"- Proper nouns: {self.proper_nouns}",
            f"- Units: {self.units}",
            f"- Length: aim for at most {self.max_lines} lines of about "
            f"{self.max_line_length} characters. Prefer the shorter phrasing "
            f"when meaning survives; never drop meaning to hit the number.",
        ]
        lines.extend(f"- {note}" for note in self.extra_notes)
        return "\n".join(lines)

    @classmethod
    def load(cls, path: Path) -> StylePreferences:
        """Read preferences, falling back to defaults when absent."""
        if not path.is_file():
            return cls()
        with path.open("rb") as handle:
            return cls.model_validate(tomllib.load(handle))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="json")
        payload["extra_notes"] = list(self.extra_notes)
        with path.open("wb") as handle:
            tomli_w.dump(payload, handle)
