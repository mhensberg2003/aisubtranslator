"""Checking Alignment on every response.

Alignment is the invariant that the set of Cue identities coming back is
exactly the set that went in. It is checked, never assumed - see
docs/adr/0001-cue-structure-is-immutable.md.

A response that breaks it is not an error yet. It is an input to Repair.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Alignment:
    """The verdict on one response."""

    accepted: Mapping[int, str]
    """Ids that came back with usable text."""

    missing: frozenset[int]
    """Ids we asked for that came back absent, empty, or blank."""

    unexpected: frozenset[int]
    """Ids the model invented. Discarded, but worth reporting."""

    @property
    def is_aligned(self) -> bool:
        return not self.missing and not self.unexpected

    @property
    def is_usable(self) -> bool:
        """Whether anything at all came back that we can keep."""
        return bool(self.accepted)


def check(expected: Iterable[int], returned: Mapping[int, str]) -> Alignment:
    """Compare a response against the ids that were requested.

    Whitespace-only text counts as missing. A model that returns `"   "` for a
    line has not translated it, and treating that as success would put a blank
    subtitle on screen.
    """
    wanted = set(expected)
    accepted: dict[int, str] = {}
    missing: set[int] = set()

    for cue_id in wanted:
        text = returned.get(cue_id)
        if text is None or not text.strip():
            missing.add(cue_id)
        else:
            accepted[cue_id] = text

    unexpected = frozenset(set(returned) - wanted)
    return Alignment(
        accepted=accepted,
        missing=frozenset(missing),
        unexpected=unexpected,
    )
