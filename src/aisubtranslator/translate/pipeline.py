"""The translation pipeline.

Classify, prepare, derive or load the Bible, translate in Chunks with bounded
concurrency, repair what comes back wrong, finish each Payload, and account for
every Cue in the Run Report.

The closing assertion is the point of the whole design: every Cue in the Track
is either translated, deliberately passed through, or recorded as failed.
Nothing falls between.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from ..domain.bible import Bible
from ..domain.cue import PassThrough
from ..domain.report import Degradation, Note, RunReport, Usage
from ..domain.style import StylePreferences
from ..jobs import checkpoint as ckpt
from ..subtitles import classify, document, payload
from . import chunking
from .provider import Batch, Line, Provider
from .repair import translate_with_repair

#: Cues sampled for the Bible pass. Spread across the Track rather than taken
#: from the front, so a slow opening does not define the whole reference sheet.
BIBLE_SAMPLE_SIZE = 400

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class Result:
    """Everything a completed Job produced."""

    translations: dict[int, str]
    report: RunReport
    bible: Bible
    notes: tuple[Note, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Plan:
    """The inputs to a Job, resolved and ready."""

    document: document.Document
    style: StylePreferences
    source_language: str
    target_language: str
    settings: Settings
    work_dir: Path
    output: Path
    refresh_bible: bool = False
    resume: bool = True
    origin: Path | None = None
    """The file the user named. Differs from the Document when a Track was
    extracted from a video, and is what the Run Report should cite."""

    @property
    def source(self) -> Path:
        return self.origin or self.document.path


async def run(
    plan: Plan,
    provider: Provider,
    *,
    on_progress: ProgressCallback | None = None,
) -> Result:
    """Translate a Document end to end."""
    cues = plan.document.track.cues
    translatable, skipped = classify.partition(cues)
    prepared = {cue.id: payload.prepare(cue) for cue in translatable}
    lines = tuple(Line(id=cue.id, text=prepared[cue.id].source_text) for cue in translatable)

    bible, bible_usage = await _resolve_bible(plan, provider, lines)

    state_dir = plan.work_dir / ".aisubtranslator"
    path = ckpt.checkpoint_path(state_dir, plan.document.path.name, plan.target_language)
    expected = _fingerprint(plan, lines, bible)
    checkpoint = ckpt.load(path, expected) if plan.resume else ckpt.Checkpoint(expected)

    outstanding = tuple(line for line in lines if line.id not in checkpoint.done_ids)
    checkpoint = await _translate_all(
        plan, provider, outstanding, bible, checkpoint, path, on_progress
    )

    translations, notes, over_budget = _finalise(plan, prepared, checkpoint)
    notes += _skip_notes(plan, skipped)
    notes += _failure_notes(plan, checkpoint)

    report = RunReport(
        source=plan.source,
        output=plan.output,
        source_language=plan.source_language,
        target_language=plan.target_language,
        model=provider.name,
        total_cues=len(cues),
        translated_cues=len(checkpoint.translations),
        usage=checkpoint.usage.plus(bible_usage),
    ).with_notes(notes).with_budget(over_budget, plan.style.max_cps)

    accounted = (
        len(checkpoint.translations) + len(skipped) + len(checkpoint.failed - checkpoint.done_ids)
    )
    assert accounted == len(cues), f"unaccounted cues: {accounted} of {len(cues)}"

    return Result(translations=translations, report=report, bible=bible)


# --------------------------------------------------------------------------


async def _resolve_bible(
    plan: Plan, provider: Provider, lines: tuple[Line, ...]
) -> tuple[Bible, Usage]:
    """Load the Work's Bible, deriving and extending it when needed.

    Existing entries always win, which is what makes hand-editing stick.
    """
    existing = Bible.load(plan.work_dir)
    if existing.characters and not plan.refresh_bible:
        return existing, Usage()
    if not lines:
        return existing, Usage()

    sample = _sample(lines, BIBLE_SAMPLE_SIZE)
    try:
        discovered, usage = await provider.derive_bible(
            sample,
            source_language=plan.source_language,
            target_language=plan.target_language,
        )
    except Exception:
        # A Bible is an optimisation, not a prerequisite. Losing it costs
        # consistency, not correctness, so it must never fail the Job.
        return existing, Usage()

    merged = existing.merged_with(discovered)
    try:
        merged.save(plan.work_dir)
    except OSError:
        pass  # Read-only media location; the Bible still applies to this run.
    return merged, usage


async def _translate_all(
    plan: Plan,
    provider: Provider,
    lines: tuple[Line, ...],
    bible: Bible,
    checkpoint: ckpt.Checkpoint,
    path: Path,
    on_progress: ProgressCallback | None,
) -> ckpt.Checkpoint:
    """Translate outstanding Chunks concurrently, checkpointing as each lands."""
    if not lines:
        return checkpoint

    settings = plan.settings
    windows = chunking.windows(
        lines, size=settings.chunk_size, context=settings.context_cues
    )
    limit = asyncio.Semaphore(max(1, settings.max_concurrency))
    lock = asyncio.Lock()
    completed = 0
    state = checkpoint

    async def handle(window: chunking.Window) -> None:
        nonlocal completed, state
        batch = Batch(
            lines=window.chunk,
            before=window.before,
            after=window.after,
            bible=bible,
            style=plan.style,
            source_language=plan.source_language,
            target_language=plan.target_language,
        )
        async with limit:
            outcome = await translate_with_repair(
                provider, batch, max_attempts=settings.max_repair_attempts
            )
        async with lock:
            state = state.merged(dict(outcome.translated), outcome.failed, outcome.usage)
            ckpt.save(path, state)
            completed += 1
            if on_progress:
                on_progress(completed, len(windows))

    await asyncio.gather(*(handle(window) for window in windows))
    return state


def _finalise(
    plan: Plan,
    prepared: dict[int, payload.Prepared],
    checkpoint: ckpt.Checkpoint,
) -> tuple[dict[int, str], tuple[Note, ...], int]:
    """Restore markup, re-wrap, and collect whatever degraded."""
    translations: dict[int, str] = {}
    notes: list[Note] = []
    over_budget = 0
    for cue_id, translated in checkpoint.translations.items():
        item = prepared.get(cue_id)
        if item is None:
            continue
        finished = payload.finalise(item, translated, plan.style)
        translations[cue_id] = finished.text
        notes.extend(finished.notes)
        over_budget += finished.over_budget
    return translations, tuple(notes), over_budget


def _skip_notes(plan: Plan, skipped: dict[int, PassThrough]) -> tuple[Note, ...]:
    cues = plan.document.track.by_id()
    return tuple(
        Note(
            cue_id=cue_id,
            timecode=cues[cue_id].timecode,
            kind=Degradation.PASSED_THROUGH,
            detail=reason.value,
            text=cues[cue_id].plaintext,
        )
        for cue_id, reason in sorted(skipped.items())
    )


def _failure_notes(plan: Plan, checkpoint: ckpt.Checkpoint) -> tuple[Note, ...]:
    cues = plan.document.track.by_id()
    unresolved = sorted(checkpoint.failed - checkpoint.done_ids)
    return tuple(
        Note(
            cue_id=cue_id,
            timecode=cues[cue_id].timecode,
            kind=Degradation.REPAIR_EXHAUSTED,
            detail=PassThrough.TRANSLATION_FAILED.value,
            text=cues[cue_id].plaintext,
        )
        for cue_id in unresolved
    )


def _fingerprint(plan: Plan, lines: tuple[Line, ...], bible: Bible) -> str:
    return ckpt.fingerprint(
        plan.settings.aisubtranslator_model,
        plan.source_language,
        plan.target_language,
        plan.style.model_dump_json(),
        str(plan.settings.chunk_size),
        str(plan.settings.context_cues),
        bible.model_dump_json(),
        "\n".join(f"{line.id}\x1f{line.text}" for line in lines),
    )


def _sample(lines: tuple[Line, ...], limit: int) -> tuple[Line, ...]:
    """Evenly spread sample across the Track, not just the opening."""
    if len(lines) <= limit:
        return lines
    step = len(lines) / limit
    return tuple(lines[int(index * step)] for index in range(limit))
