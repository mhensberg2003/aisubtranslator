"""Alignment checking and the Repair cycle.

These tests are the reason the adversarial fakes exist. Every failure mode
here is one a real model actually produces, and each one must degrade rather
than desynchronise the file.
"""

from __future__ import annotations

import pytest

from aisubtranslator.translate import alignment, chunking
from aisubtranslator.translate.provider import (
    Batch,
    ExplodingProvider,
    IdentityProvider,
    Line,
    UnreliableProvider,
)
from aisubtranslator.translate.repair import translate_with_repair


def make_batch(count: int = 5) -> Batch:
    return Batch(lines=tuple(Line(id=i, text=f"line {i}") for i in range(count)))


# --------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------


def test_exact_match_is_aligned() -> None:
    verdict = alignment.check([1, 2], {1: "en", 2: "to"})
    assert verdict.is_aligned
    assert verdict.accepted == {1: "en", 2: "to"}


def test_a_dropped_id_is_missing() -> None:
    verdict = alignment.check([1, 2], {1: "en"})
    assert not verdict.is_aligned
    assert verdict.missing == {2}


def test_blank_text_counts_as_missing() -> None:
    """A blank subtitle on screen is a failure, not a translation."""
    verdict = alignment.check([1, 2], {1: "en", 2: "   "})
    assert verdict.missing == {2}
    assert 2 not in verdict.accepted


def test_invented_ids_are_reported_and_discarded() -> None:
    verdict = alignment.check([1], {1: "en", 99: "nobody asked"})
    assert verdict.unexpected == {99}
    assert verdict.accepted == {1: "en"}
    assert not verdict.is_aligned


def test_a_merge_shows_up_as_a_missing_id() -> None:
    """Two Cues collapsed into one - the classic desync - is caught."""
    verdict = alignment.check([1, 2], {1: "en to"})
    assert verdict.missing == {2}


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------


def test_chunks_cover_every_line_exactly_once() -> None:
    lines = [Line(id=i, text=str(i)) for i in range(25)]
    result = chunking.windows(lines, size=10, context=3)
    covered = [line.id for window in result for line in window.chunk]
    assert covered == list(range(25))


def test_context_is_clipped_at_the_edges() -> None:
    lines = [Line(id=i, text=str(i)) for i in range(25)]
    result = chunking.windows(lines, size=10, context=3)

    assert result[0].before == ()
    assert [line.id for line in result[0].after] == [10, 11, 12]
    assert [line.id for line in result[1].before] == [7, 8, 9]
    assert result[-1].after == ()


def test_context_never_overlaps_the_chunk_itself() -> None:
    lines = [Line(id=i, text=str(i)) for i in range(25)]
    for window in chunking.windows(lines, size=10, context=3):
        chunk_ids = {line.id for line in window.chunk}
        context_ids = {line.id for line in window.before + window.after}
        assert not chunk_ids & context_ids


def test_zero_context_is_allowed() -> None:
    lines = [Line(id=i, text=str(i)) for i in range(5)]
    windows = chunking.windows(lines, size=2, context=0)
    assert all(w.before == () and w.after == () for w in windows)


def test_invalid_chunk_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        chunking.windows([], size=0, context=0)


# --------------------------------------------------------------------------
# Repair
# --------------------------------------------------------------------------


async def test_a_clean_provider_needs_no_repair() -> None:
    outcome = await translate_with_repair(IdentityProvider(), make_batch())
    assert outcome.attempts == 1
    assert not outcome.failed
    assert not outcome.was_repaired
    assert len(outcome.translated) == 5


@pytest.mark.parametrize("mode", ["drop", "empty", "merge", "invent", "everything"])
async def test_every_failure_mode_recovers(mode: str) -> None:
    provider = UnreliableProvider(mode=mode, fails_for=1)
    batch = make_batch()
    outcome = await translate_with_repair(provider, batch)

    assert not outcome.failed
    assert set(outcome.translated) == set(batch.ids)


async def test_repair_only_re_requests_what_broke() -> None:
    """The point of Repair: do not re-pay for lines that came back fine."""
    provider = UnreliableProvider(mode="drop", fails_for=1)
    batch = make_batch(10)
    await translate_with_repair(provider, batch)

    assert len(provider.calls) == 2
    assert len(provider.calls[0].lines) == 10
    assert len(provider.calls[1].lines) == 1


async def test_a_permanently_broken_line_is_reported_not_raised() -> None:
    provider = UnreliableProvider(mode="drop", fails_for=99)
    batch = make_batch()
    outcome = await translate_with_repair(provider, batch, max_attempts=2)

    assert outcome.failed
    assert len(outcome.translated) == len(batch.ids) - len(outcome.failed)


async def test_a_dead_provider_degrades_rather_than_crashing() -> None:
    """Fourteen hundred good lines must not be lost to one dead request."""
    outcome = await translate_with_repair(ExplodingProvider(), make_batch(), max_attempts=1)
    assert outcome.failed == frozenset(range(5))
    assert not outcome.translated


async def test_invented_ids_never_reach_the_output() -> None:
    provider = UnreliableProvider(mode="invent", fails_for=1)
    batch = make_batch()
    outcome = await translate_with_repair(provider, batch)
    assert set(outcome.translated) <= set(batch.ids)


async def test_repair_terminates_on_a_persistently_failing_provider() -> None:
    provider = UnreliableProvider(mode="everything", fails_for=999)
    outcome = await translate_with_repair(provider, make_batch(6), max_attempts=3)
    assert outcome.attempts <= 5
