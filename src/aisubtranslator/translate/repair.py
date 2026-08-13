"""Repair - the bounded recovery cycle when Alignment breaks.

The escalation is deliberate and always terminates:

1. Ask again for only the ids that came back wrong.
2. Failing that, translate each remaining id on its own, where there is no
   opportunity to merge or drop anything.
3. Failing that, keep the source text and record it.

Step 3 is what makes this safe to run unattended. One stubborn line never costs
you the other fourteen hundred.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..domain.report import Usage
from . import alignment
from .provider import Batch, Provider


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a Chunk finally produced, after however many attempts it took."""

    translated: Mapping[int, str]
    failed: frozenset[int]
    usage: Usage
    attempts: int
    invented: frozenset[int] = field(default_factory=frozenset)

    @property
    def was_repaired(self) -> bool:
        return self.attempts > 1


async def translate_with_repair(
    provider: Provider,
    batch: Batch,
    *,
    max_attempts: int = 2,
) -> Outcome:
    """Translate a Batch, repairing Alignment breaks until bounded exhaustion."""
    translated: dict[int, str] = {}
    invented: set[int] = set()
    usage = Usage()
    outstanding = list(batch.ids)
    attempts = 0

    while outstanding and attempts <= max_attempts:
        attempts += 1
        attempt_batch = batch.subset(outstanding)
        try:
            response = await provider.translate(attempt_batch)
        except Exception:
            if attempts > max_attempts:
                break
            continue

        usage = usage.plus(response.usage)
        verdict = alignment.check(outstanding, response.lines)
        translated.update(verdict.accepted)
        invented.update(verdict.unexpected)
        outstanding = sorted(verdict.missing)

    # Last resort: each remaining line alone, where nothing can be merged away.
    if outstanding:
        translated, usage, outstanding = await _translate_individually(
            provider, batch, outstanding, translated, usage
        )
        attempts += 1

    return Outcome(
        translated=translated,
        failed=frozenset(outstanding),
        usage=usage,
        attempts=attempts,
        invented=frozenset(invented),
    )


async def _translate_individually(
    provider: Provider,
    batch: Batch,
    outstanding: list[int],
    translated: dict[int, str],
    usage: Usage,
) -> tuple[dict[int, str], Usage, list[int]]:
    """Translate stubborn ids one at a time. Failures are returned, not raised."""
    still_failing: list[int] = []
    for cue_id in outstanding:
        single = batch.subset([cue_id])
        try:
            response = await provider.translate(single)
        except Exception:
            still_failing.append(cue_id)
            continue
        usage = usage.plus(response.usage)
        verdict = alignment.check([cue_id], response.lines)
        if verdict.is_usable:
            translated.update(verdict.accepted)
        else:
            still_failing.append(cue_id)
    return translated, usage, still_failing
