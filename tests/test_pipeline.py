"""End-to-end Job behaviour with fake providers.

The property that matters most is total accounting: every Cue in the Track is
either translated, deliberately passed through, or recorded as failed. A Cue
that is none of those is a hole in the subtitles.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aisubtranslator.config import Settings
from aisubtranslator.domain.report import Degradation
from aisubtranslator.domain.style import StylePreferences
from aisubtranslator.subtitles import document
from aisubtranslator.translate import pipeline
from aisubtranslator.translate.provider import (
    ExplodingProvider,
    IdentityProvider,
    PrefixProvider,
    UnreliableProvider,
)

FIXTURES = Path(__file__).parent / "fixtures"


def make_plan(tmp_path: Path, name: str = "sample.ass", **overrides) -> pipeline.Plan:
    source = tmp_path / name
    shutil.copy(FIXTURES / name, source)
    doc = document.load(source)
    settings = Settings(
        openrouter_api_key="test",
        chunk_size=overrides.pop("chunk_size", 3),
        context_cues=overrides.pop("context_cues", 1),
        max_concurrency=2,
    )
    return pipeline.Plan(
        document=doc,
        style=overrides.pop("style", StylePreferences()),
        source_language="English",
        target_language="Danish",
        settings=settings,
        work_dir=tmp_path,
        output=tmp_path / "out.ass",
        **overrides,
    )


async def test_every_cue_is_accounted_for(tmp_path: Path) -> None:
    plan = make_plan(tmp_path)
    result = await pipeline.run(plan, IdentityProvider())

    total = plan.document.track.cues
    passed = result.report.of_kind(Degradation.PASSED_THROUGH)
    failed = result.report.of_kind(Degradation.REPAIR_EXHAUSTED)
    assert len(result.translations) + len(passed) + len(failed) == len(total)


async def test_translations_reach_the_output_file(tmp_path: Path) -> None:
    plan = make_plan(tmp_path)
    result = await pipeline.run(plan, PrefixProvider())

    rendered = document.render(plan.document, result.translations)
    texts = [event.text for event in rendered.events]

    assert any("DA:" in t for t in texts)
    # Passed-through Cues keep their source text exactly.
    assert any(t.startswith("{\\k") for t in texts)
    assert any(event.is_comment for event in rendered.events)


async def test_passed_through_cues_are_explained(tmp_path: Path) -> None:
    plan = make_plan(tmp_path)
    result = await pipeline.run(plan, IdentityProvider())

    reasons = {n.detail for n in result.report.of_kind(Degradation.PASSED_THROUGH)}
    assert any("karaoke" in r for r in reasons)
    assert any("comment" in r for r in reasons)
    assert any("no letters" in r for r in reasons)


async def test_a_dead_provider_still_produces_a_usable_file(tmp_path: Path) -> None:
    """Nothing translated, nothing lost, and the report says exactly why."""
    plan = make_plan(tmp_path)
    result = await pipeline.run(plan, ExplodingProvider())

    assert not result.translations
    failures = result.report.of_kind(Degradation.REPAIR_EXHAUSTED)
    assert failures

    rendered = document.render(plan.document, result.translations)
    original = plan.document.source
    assert [e.text for e in rendered.events] == [e.text for e in original.events]


async def test_alignment_breaks_are_repaired_end_to_end(tmp_path: Path) -> None:
    plan = make_plan(tmp_path)
    result = await pipeline.run(plan, UnreliableProvider(mode="merge", fails_for=1))
    assert not result.report.of_kind(Degradation.REPAIR_EXHAUSTED)


async def test_resuming_re_pays_for_nothing(tmp_path: Path) -> None:
    plan = make_plan(tmp_path)
    first = IdentityProvider()
    await pipeline.run(plan, first)
    assert first.calls

    second = IdentityProvider()
    result = await pipeline.run(plan, second)
    assert second.calls == []
    assert result.translations


async def test_changing_style_invalidates_the_checkpoint(tmp_path: Path) -> None:
    """A different Style Preference means a different translation, not a cached one."""
    plan = make_plan(tmp_path)
    await pipeline.run(plan, IdentityProvider())

    changed = make_plan(
        tmp_path, style=StylePreferences(max_line_length=30, formality="De-form")
    )
    provider = IdentityProvider()
    await pipeline.run(changed, provider)
    assert provider.calls


async def test_resume_can_be_switched_off(tmp_path: Path) -> None:
    plan = make_plan(tmp_path)
    await pipeline.run(plan, IdentityProvider())

    fresh = make_plan(tmp_path, resume=False)
    provider = IdentityProvider()
    await pipeline.run(fresh, provider)
    assert provider.calls


async def test_the_bible_is_written_into_the_work_directory(tmp_path: Path) -> None:
    plan = make_plan(tmp_path)
    await pipeline.run(plan, IdentityProvider())
    assert (tmp_path / ".aisubtranslator" / "bible.toml").is_file()


async def test_chunks_carry_context_cues(tmp_path: Path) -> None:
    provider = IdentityProvider()
    await pipeline.run(make_plan(tmp_path, chunk_size=2, context_cues=2), provider)

    assert len(provider.calls) > 1
    assert any(call.before or call.after for call in provider.calls)


async def test_context_cues_are_never_translated(tmp_path: Path) -> None:
    """Context is reference material; returning it would break Alignment."""
    plan = make_plan(tmp_path, chunk_size=2, context_cues=2)
    provider = IdentityProvider()
    result = await pipeline.run(plan, provider)

    for call in provider.calls:
        context_ids = {line.id for line in call.before + call.after}
        assert not context_ids & set(call.ids)

    # Only Cues that were actually asked for may appear in the output.
    requested = {cue_id for call in provider.calls for cue_id in call.ids}
    assert set(result.translations) == requested


async def test_srt_files_work_too(tmp_path: Path) -> None:
    plan = make_plan(tmp_path, name="sample.srt")
    result = await pipeline.run(plan, PrefixProvider())
    assert result.translations


@pytest.mark.parametrize("mode", ["drop", "empty", "invent", "merge"])
async def test_no_failure_mode_produces_a_blank_subtitle(
    mode: str, tmp_path: Path
) -> None:
    plan = make_plan(tmp_path)
    result = await pipeline.run(plan, UnreliableProvider(mode=mode, fails_for=2))
    assert all(text.strip() for text in result.translations.values())
