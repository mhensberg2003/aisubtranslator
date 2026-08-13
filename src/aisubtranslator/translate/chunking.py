"""Splitting a Track into Chunks with surrounding Context Cues.

Context Cues are what let the translator see a sentence that spans a Chunk
boundary. They are sent as read-only material and are never translated as part
of that Chunk - the model returns text only for the Chunk's own ids, which is
what makes Alignment checkable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .provider import Line


@dataclass(frozen=True, slots=True)
class Window:
    """One Chunk and the read-only Cues on either side of it."""

    index: int
    before: tuple[Line, ...]
    chunk: tuple[Line, ...]
    after: tuple[Line, ...]

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(line.id for line in self.chunk)


def windows(lines: Sequence[Line], *, size: int, context: int) -> tuple[Window, ...]:
    """Split into Chunks of at most `size`, each carrying `context` Cues either side.

    Context is clipped at the ends of the Track rather than padded, so the
    first Chunk simply has nothing before it.
    """
    if size < 1:
        raise ValueError("chunk size must be at least 1")
    if context < 0:
        raise ValueError("context must not be negative")

    return tuple(
        Window(
            index=position,
            before=tuple(lines[max(0, start - context) : start]),
            chunk=tuple(lines[start : min(start + size, len(lines))]),
            after=tuple(
                lines[min(start + size, len(lines)) : min(start + size, len(lines)) + context]
            ),
        )
        for position, start in enumerate(range(0, len(lines), size))
    )
