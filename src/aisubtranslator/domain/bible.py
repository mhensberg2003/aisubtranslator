"""The Bible - a Work's persistent reference sheet.

Derived from a Track before translation begins, then carried forward. Because a
Work is a directory (docs/adr/0002-a-work-is-a-directory.md), the Bible simply
lives in that directory and needs no identity resolution.

The merge rule matters: entries already in the Bible win over freshly derived
ones. That is what makes hand-editing meaningful - correct a name once and it
holds for every later episode instead of being overwritten by the next run.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field

BIBLE_FILENAME = "bible.toml"


class Entry(BaseModel):
    """One source term and the rendering that has been settled on for it."""

    model_config = {"frozen": True}

    source: str
    target: str
    note: str = ""

    @property
    def key(self) -> str:
        return self.source.strip().casefold()


class Bible(BaseModel):
    """What a Work has learned about itself."""

    model_config = {"frozen": True}

    target_language: str = ""
    genre: str = ""
    source_register: str = Field(
        default="",
        description="The register observed in the source, not the register "
        "desired in the output - that is Style Preferences' job.",
    )
    summary: str = ""
    characters: tuple[Entry, ...] = ()
    terms: tuple[Entry, ...] = ()
    notes: tuple[str, ...] = ()

    def merged_with(self, discovered: Bible) -> Bible:
        """Return a new Bible extended with anything genuinely new.

        Existing entries are preserved verbatim, including hand-edits. Only
        sources not already known are appended. Descriptive prose fields are
        filled in only where currently empty, for the same reason.
        """
        return Bible(
            target_language=self.target_language or discovered.target_language,
            genre=self.genre or discovered.genre,
            source_register=self.source_register or discovered.source_register,
            summary=self.summary or discovered.summary,
            characters=_extend(self.characters, discovered.characters),
            terms=_extend(self.terms, discovered.terms),
            notes=self.notes + tuple(n for n in discovered.notes if n not in self.notes),
        )

    def is_empty(self) -> bool:
        return not (
            self.characters or self.terms or self.genre or self.source_register
        )

    def to_prompt(self) -> str:
        """Render for inclusion in a translation request."""
        sections: list[str] = []
        if self.genre:
            sections.append(f"Genre: {self.genre}")
        if self.source_register:
            sections.append(f"Register of the source: {self.source_register}")
        if self.summary:
            sections.append(f"Premise: {self.summary}")
        if self.characters:
            sections.append(
                "Characters (use these renderings exactly):\n"
                + "\n".join(_format_entry(e) for e in self.characters)
            )
        if self.terms:
            sections.append(
                "Recurring terms (use these renderings exactly):\n"
                + "\n".join(_format_entry(e) for e in self.terms)
            )
        if self.notes:
            sections.append("Notes:\n" + "\n".join(f"  - {n}" for n in self.notes))
        return "\n\n".join(sections)

    @classmethod
    def load(cls, work_dir: Path) -> Bible:
        """Read a Work's Bible, returning an empty one when absent."""
        path = bible_path(work_dir)
        if not path.is_file():
            return cls()
        with path.open("rb") as handle:
            return cls.model_validate(tomllib.load(handle))

    def save(self, work_dir: Path) -> None:
        path = bible_path(work_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            tomli_w.dump(self.model_dump(mode="json"), handle)


def bible_path(work_dir: Path) -> Path:
    return work_dir / ".aisubtranslator" / BIBLE_FILENAME


def _extend(existing: tuple[Entry, ...], discovered: tuple[Entry, ...]) -> tuple[Entry, ...]:
    known = {entry.key for entry in existing}
    additions = tuple(e for e in discovered if e.key not in known and e.source.strip())
    return existing + additions


def _format_entry(entry: Entry) -> str:
    suffix = f"  ({entry.note})" if entry.note else ""
    return f"  - {entry.source} -> {entry.target}{suffix}"


__all__ = ["BIBLE_FILENAME", "Bible", "Entry", "bible_path"]
