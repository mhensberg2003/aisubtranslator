"""Domain models: the Bible, the Run Report, Job checkpointing, languages.

The Bible merge rule carries the most weight here. If freshly derived entries
could overwrite existing ones, hand-editing would be pointless and the whole
reason for persisting a Bible across a Work would evaporate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aisubtranslator import languages
from aisubtranslator.domain.bible import Bible, Entry
from aisubtranslator.domain.cue import Cue
from aisubtranslator.domain.report import Degradation, Note, RunReport, Usage
from aisubtranslator.domain.style import StylePreferences
from aisubtranslator.jobs import checkpoint as ckpt


# --------------------------------------------------------------------------
# Bible
# --------------------------------------------------------------------------


def test_existing_entries_survive_a_merge() -> None:
    """A hand-corrected name must not be overwritten by the next episode."""
    existing = Bible(characters=(Entry(source="Anya", target="Anja", note="corrected"),))
    discovered = Bible(characters=(Entry(source="Anya", target="Anya"),))

    merged = existing.merged_with(discovered)
    assert len(merged.characters) == 1
    assert merged.characters[0].target == "Anja"
    assert merged.characters[0].note == "corrected"


def test_new_entries_are_appended() -> None:
    existing = Bible(characters=(Entry(source="Anya", target="Anja"),))
    discovered = Bible(characters=(Entry(source="Boris", target="Boris"),))

    merged = existing.merged_with(discovered)
    assert {c.source for c in merged.characters} == {"Anya", "Boris"}


def test_matching_ignores_case_and_padding() -> None:
    existing = Bible(terms=(Entry(source="The Order", target="Ordenen"),))
    discovered = Bible(terms=(Entry(source="  the order ", target="Ordren"),))
    assert len(existing.merged_with(discovered).terms) == 1


def test_merging_never_mutates_the_original() -> None:
    existing = Bible(characters=(Entry(source="Anya", target="Anja"),))
    existing.merged_with(Bible(characters=(Entry(source="Boris", target="Boris"),)))
    assert len(existing.characters) == 1


def test_prose_fields_fill_in_only_where_empty() -> None:
    existing = Bible(genre="noir")
    merged = existing.merged_with(Bible(genre="comedy", summary="A caper."))
    assert merged.genre == "noir"
    assert merged.summary == "A caper."


def test_a_bible_survives_a_save_and_load(tmp_path: Path) -> None:
    original = Bible(
        target_language="Danish",
        genre="noir",
        source_register="clipped, 1940s",
        characters=(Entry(source="Anya", target="Anja", note="uses De-form"),),
        terms=(Entry(source="The Order", target="Ordenen"),),
        notes=("Narration is past tense.",),
    )
    original.save(tmp_path)
    assert Bible.load(tmp_path) == original


def test_an_absent_bible_loads_as_empty(tmp_path: Path) -> None:
    assert Bible.load(tmp_path).is_empty()


def test_the_bible_prompt_names_the_renderings() -> None:
    rendered = Bible(characters=(Entry(source="Anya", target="Anja"),)).to_prompt()
    assert "Anya -> Anja" in rendered


# --------------------------------------------------------------------------
# Style Preferences
# --------------------------------------------------------------------------


def test_style_defaults_suit_danish_personal_viewing() -> None:
    rendered = StylePreferences().to_prompt()
    assert "du-form" in rendered
    assert "preserve at equivalent intensity" in rendered


def test_style_survives_a_save_and_load(tmp_path: Path) -> None:
    original = StylePreferences(max_cps=20.0, extra_notes=("Keep song lyrics rhyming.",))
    path = tmp_path / "style.toml"
    original.save(path)
    assert StylePreferences.load(path) == original


def test_absent_style_falls_back_to_defaults(tmp_path: Path) -> None:
    assert StylePreferences.load(tmp_path / "nothing.toml") == StylePreferences()


def test_style_preferences_are_immutable() -> None:
    with pytest.raises(Exception):
        StylePreferences().max_cps = 99.0  # type: ignore[misc]


# --------------------------------------------------------------------------
# Run Report
# --------------------------------------------------------------------------


def make_report() -> RunReport:
    return RunReport(
        source=Path("Film.srt"),
        output=Path("Film.da.srt"),
        source_language="English",
        target_language="Danish",
        model="fake",
        total_cues=3,
    )


def test_a_clean_report_says_so() -> None:
    assert make_report().is_clean
    assert "Nothing to report" in make_report().to_markdown()


def test_notes_are_grouped_and_timecoded() -> None:
    report = make_report().with_note(
        Note(
            cue_id=4,
            timecode="00:01:02.500",
            kind=Degradation.HARDER_THAN_SOURCE,
            detail="24.0 chars/sec, up from 12.1 in the source",
        )
    )
    markdown = report.to_markdown()
    assert not report.is_clean
    assert "Harder to read than the source" in markdown
    assert "00:01:02.500" in markdown


def test_the_budget_summary_separates_ours_from_inherited() -> None:
    """The whole point: 200 inherited warnings must not bury the 3 that are ours."""
    report = (
        make_report()
        .with_note(
            Note(
                cue_id=4,
                timecode="00:01:02.500",
                kind=Degradation.HARDER_THAN_SOURCE,
                detail="24.0 chars/sec, up from 12.1 in the source",
            )
        )
        .with_budget(209, 17.0)
    )
    markdown = report.to_markdown()
    assert "209 of 3 cues exceed 17 chars/sec" in markdown
    assert "1 of those read slower than the source" in markdown


def test_an_all_inherited_run_lists_nothing() -> None:
    report = make_report().with_budget(209, 17.0)
    assert report.is_clean
    assert "209 of 3 cues exceed" in report.to_markdown()


def test_adding_a_note_returns_a_new_report() -> None:
    original = make_report()
    original.with_note(
        Note(cue_id=1, timecode="00:00:01.000", kind=Degradation.PASSED_THROUGH, detail="x")
    )
    assert original.is_clean


def test_usage_adds_up_and_tolerates_unknown_cost() -> None:
    combined = Usage(prompt_tokens=10, requests=1).plus(
        Usage(prompt_tokens=5, requests=1, cost_usd=0.25)
    )
    assert combined.prompt_tokens == 15
    assert combined.requests == 2
    assert combined.cost_usd == 0.25

    assert Usage().plus(Usage()).cost_usd is None


# --------------------------------------------------------------------------
# Checkpointing
# --------------------------------------------------------------------------


def test_a_checkpoint_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "job.json"
    original = ckpt.Checkpoint(
        fingerprint="abc",
        translations={1: "en", 2: "to"},
        failed=frozenset({3}),
        usage=Usage(prompt_tokens=100, requests=2, cost_usd=0.01),
    )
    ckpt.save(path, original)
    assert ckpt.load(path, "abc") == original


def test_a_stale_fingerprint_discards_the_checkpoint(tmp_path: Path) -> None:
    """Changing anything that affects output must retranslate, not resume."""
    path = tmp_path / "job.json"
    ckpt.save(path, ckpt.Checkpoint(fingerprint="abc", translations={1: "en"}))
    assert ckpt.load(path, "different").translations == {}


def test_a_corrupt_checkpoint_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    path = tmp_path / "job.json"
    path.write_text("{not json", encoding="utf-8")
    assert ckpt.load(path, "abc").translations == {}


def test_fingerprints_track_every_input() -> None:
    assert ckpt.fingerprint("a", "b") == ckpt.fingerprint("a", "b")
    assert ckpt.fingerprint("a", "b") != ckpt.fingerprint("ab", "")


def test_merging_a_checkpoint_returns_a_new_one() -> None:
    original = ckpt.Checkpoint(fingerprint="x", translations={1: "en"})
    merged = original.merged({2: "to"}, frozenset({3}), Usage(requests=1))
    assert original.translations == {1: "en"}
    assert merged.translations == {1: "en", 2: "to"}


# --------------------------------------------------------------------------
# Cue and languages
# --------------------------------------------------------------------------


def test_cue_timecodes_are_player_friendly() -> None:
    cue = Cue(
        id=0, start_ms=3_723_450, end_ms=3_725_000, text="x", plaintext="x",
        style="Default", is_comment=False, is_drawing=False,
    )
    assert cue.timecode == "01:02:03.450"
    assert cue.duration_ms == 1550


def test_a_cue_cannot_be_mutated() -> None:
    """Timing immutability is enforced by the type, not by convention."""
    cue = Cue(
        id=0, start_ms=0, end_ms=1, text="x", plaintext="x",
        style="Default", is_comment=False, is_drawing=False,
    )
    with pytest.raises(Exception):
        cue.start_ms = 5  # type: ignore[misc]


@pytest.mark.parametrize(
    ("value", "code"),
    [("da", "da"), ("dan", "da"), ("Danish", "da"), ("en-US", "en"), ("eng", "en")],
)
def test_language_codes_normalise(value: str, code: str) -> None:
    assert languages.to_code(value) == code


def test_language_names_are_used_in_prompts() -> None:
    assert languages.to_name("da") == "Danish"
    assert languages.to_name("auto") == "the source language"
    assert languages.to_name("Klingon") == "Klingon"
