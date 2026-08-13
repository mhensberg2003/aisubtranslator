"""Resolving what the user dropped in into a Subtitle Track we can translate.

A subtitle file is used directly. A video is probed, its text Tracks ranked,
and the winner extracted - asking only when the ranking is genuinely close.
Anything else is refused with an explanation of what was actually found.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import work_state_dir
from .errors import InputError
from .media import extract, probe, ranking

Chooser = Callable[[tuple[ranking.Ranked, ...]], ranking.Ranked]


@dataclass(frozen=True, slots=True)
class ResolvedInput:
    """The subtitle file to translate, and where it came from."""

    subtitle_path: Path
    origin: Path
    candidate: probe.TrackCandidate | None = None
    was_extracted: bool = False
    ambiguous: bool = False

    @property
    def language_hint(self) -> str | None:
        return self.candidate.language if self.candidate else None


def resolve(
    path: Path,
    *,
    work_dir: Path,
    track_index: int | None = None,
    preferred_languages: tuple[str, ...] = (),
    choose: Chooser | None = None,
) -> ResolvedInput:
    """Turn a user-supplied path into a subtitle file on disk."""
    path = path.expanduser()
    if not path.exists():
        raise InputError(f"{path} does not exist.")
    if path.is_dir():
        raise InputError(
            f"{path} is a directory.",
            hint="Point at a single subtitle or video file.",
        )

    if not probe.is_video(path):
        return ResolvedInput(subtitle_path=path, origin=path)

    candidates = probe.probe(path)
    ranked = ranking.rank(candidates, preferred_languages=preferred_languages)
    if not ranked:
        raise extract.explain_absence(candidates, path)

    chosen, ambiguous = _select(ranked, track_index, choose, path)
    destination = (
        work_state_dir(work_dir)
        / "extracted"
        / f"{path.stem}.{chosen.language or 'und'}{chosen.extension}"
    )
    extract.extract(path, chosen, destination)
    return ResolvedInput(
        subtitle_path=destination,
        origin=path,
        candidate=chosen,
        was_extracted=True,
        ambiguous=ambiguous,
    )


def _select(
    ranked: tuple[ranking.Ranked, ...],
    track_index: int | None,
    choose: Chooser | None,
    path: Path,
) -> tuple[probe.TrackCandidate, bool]:
    """Pick a Track, asking only when the ranking does not settle it."""
    if track_index is not None:
        for entry in ranked:
            if entry.candidate.subtitle_index == track_index:
                return entry.candidate, False
        available = ", ".join(str(e.candidate.subtitle_index) for e in ranked)
        raise InputError(
            f"{path.name} has no text subtitle track {track_index}.",
            hint=f"Available text tracks: {available}.",
        )

    if ranking.is_decisive(ranked) or choose is None:
        return ranked[0].candidate, not ranking.is_decisive(ranked)
    return choose(ranked).candidate, False
