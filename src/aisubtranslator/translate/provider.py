"""The translation provider interface, and fakes that implement it.

The protocol is translation-shaped rather than chat-shaped. That keeps the
Alignment machinery testable: a fake can misbehave in exactly the way a real
model misbehaves - dropping a line, inventing an id, returning an empty string -
without any HTTP, any API key, or any non-determinism.

The adversarial fakes here are not decoration. They are how we know the Repair
path works, and they run on every test invocation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ..domain.bible import Bible
from ..domain.report import Usage
from ..domain.style import StylePreferences


@dataclass(frozen=True, slots=True)
class Line:
    """One Cue reduced to what the model needs: an identity and some text."""

    id: int
    text: str


@dataclass(frozen=True, slots=True)
class Batch:
    """One Chunk plus everything needed to translate it well."""

    lines: tuple[Line, ...]
    before: tuple[Line, ...] = ()
    after: tuple[Line, ...] = ()
    bible: Bible = field(default_factory=Bible)
    style: StylePreferences = field(default_factory=StylePreferences)
    source_language: str = "auto"
    target_language: str = "Danish"

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(line.id for line in self.lines)

    def subset(self, ids: Sequence[int]) -> Batch:
        """A Batch covering only `ids`, keeping the same context and Bible.

        Used by Repair, which re-asks for the lines that came back wrong
        without re-paying for the ones that came back fine.
        """
        wanted = set(ids)
        return Batch(
            lines=tuple(line for line in self.lines if line.id in wanted),
            before=self.before,
            after=self.after,
            bible=self.bible,
            style=self.style,
            source_language=self.source_language,
            target_language=self.target_language,
        )


@dataclass(frozen=True, slots=True)
class Response:
    """What came back. `lines` is keyed by Cue id and is not yet trusted."""

    lines: Mapping[int, str]
    usage: Usage = field(default_factory=Usage)


class Provider(Protocol):
    """Anything that can translate a Batch and derive a Bible."""

    name: str

    async def translate(self, batch: Batch) -> Response: ...

    async def derive_bible(
        self,
        sample: Sequence[Line],
        *,
        source_language: str,
        target_language: str,
    ) -> tuple[Bible, Usage]: ...


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


@dataclass
class IdentityProvider:
    """Returns every line unchanged. The basis of the round-trip invariant."""

    name: str = "fake:identity"
    calls: list[Batch] = field(default_factory=list)

    async def translate(self, batch: Batch) -> Response:
        self.calls.append(batch)
        return Response(
            lines={line.id: line.text for line in batch.lines},
            usage=Usage(requests=1),
        )

    async def derive_bible(
        self,
        sample: Sequence[Line],
        *,
        source_language: str,
        target_language: str,
    ) -> tuple[Bible, Usage]:
        return Bible(target_language=target_language), Usage(requests=1)


@dataclass
class PrefixProvider(IdentityProvider):
    """Marks every line, so it is visible which text came from translation."""

    name: str = "fake:prefix"
    prefix: str = "DA:"

    async def translate(self, batch: Batch) -> Response:
        self.calls.append(batch)
        return Response(
            lines={line.id: f"{self.prefix}{line.text}" for line in batch.lines},
            usage=Usage(requests=1),
        )


@dataclass
class UnreliableProvider(IdentityProvider):
    """Breaks Alignment in a chosen way, then behaves on later attempts.

    `fails_for` counts down per call, so Repair can be observed succeeding
    rather than only failing.
    """

    name: str = "fake:unreliable"
    mode: str = "drop"
    fails_for: int = 1

    async def translate(self, batch: Batch) -> Response:
        self.calls.append(batch)
        usage = Usage(requests=1)
        lines = {line.id: line.text for line in batch.lines}

        if self.fails_for <= 0 or not lines:
            return Response(lines=lines, usage=usage)
        self.fails_for -= 1

        ids = sorted(lines)
        match self.mode:
            case "drop":
                lines.pop(ids[0])
            case "empty":
                lines[ids[0]] = "   "
            case "invent":
                lines[max(ids) + 9_999] = "a line nobody asked for"
            case "merge":
                # The classic desync: two Cues collapsed into one.
                if len(ids) >= 2:
                    lines[ids[0]] = f"{lines[ids[0]]} {lines[ids[1]]}"
                    lines.pop(ids[1])
            case "everything":
                lines.pop(ids[0])
                lines[max(ids) + 9_999] = "noise"
                if len(ids) >= 2:
                    lines[ids[1]] = ""
        return Response(lines=lines, usage=usage)


@dataclass
class ExplodingProvider(IdentityProvider):
    """Always raises. Used to prove a Job degrades rather than crashes."""

    name: str = "fake:exploding"

    async def translate(self, batch: Batch) -> Response:
        self.calls.append(batch)
        raise RuntimeError("provider is down")
