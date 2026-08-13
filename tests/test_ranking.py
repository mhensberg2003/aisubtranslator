"""Track selection.

Every case here is a real release layout. The costly mistakes are picking the
Forced track (you get forty lines) and picking Signs & Songs (you get no
dialogue), so those are what the scoring is built to avoid.
"""

from __future__ import annotations

from pathlib import Path

from aisubtranslator.media.extract import explain_absence
from aisubtranslator.media.probe import TrackCandidate
from aisubtranslator.media.ranking import is_decisive, rank


def track(
    subtitle_index: int = 0,
    *,
    codec: str = "subrip",
    language: str | None = "eng",
    title: str | None = None,
    default: bool = False,
    forced: bool = False,
    sdh: bool = False,
    frames: int | None = None,
) -> TrackCandidate:
    return TrackCandidate(
        stream_index=subtitle_index + 2,
        subtitle_index=subtitle_index,
        codec=codec,
        language=language,
        title=title,
        is_default=default,
        is_forced=forced,
        is_hearing_impaired=sdh,
        frames=frames,
    )


def test_full_dialogue_beats_forced() -> None:
    ranked = rank((track(0, forced=True, frames=38), track(1, frames=1400)))
    assert ranked[0].candidate.subtitle_index == 1
    assert is_decisive(ranked)


def test_full_dialogue_beats_signs_and_songs() -> None:
    ranked = rank((track(0, title="Signs & Songs"), track(1, title="Full Dialogue")))
    assert ranked[0].candidate.subtitle_index == 1
    assert is_decisive(ranked)


def test_a_short_track_is_distrusted_even_without_the_forced_flag() -> None:
    """Release groups often omit the disposition; cue count gives it away."""
    ranked = rank((track(0, frames=40), track(1, frames=1200)))
    assert ranked[0].candidate.subtitle_index == 1


def test_sdh_loses_to_a_plain_track_but_stays_usable() -> None:
    ranked = rank((track(0, sdh=True, title="English (SDH)"), track(1)))
    assert ranked[0].candidate.subtitle_index == 1
    assert len(ranked) == 2


def test_sdh_wins_when_it_is_the_only_option() -> None:
    ranked = rank((track(0, sdh=True, title="English SDH"),))
    assert ranked[0].candidate.subtitle_index == 0
    assert is_decisive(ranked)


def test_requested_language_dominates() -> None:
    ranked = rank(
        (track(0, language="fre"), track(1, language="eng")),
        preferred_languages=("en",),
    )
    assert ranked[0].candidate.language == "eng"


def test_image_tracks_are_excluded_entirely() -> None:
    ranked = rank((track(0, codec="hdmv_pgs_subtitle"), track(1, codec="subrip")))
    assert len(ranked) == 1
    assert ranked[0].candidate.codec == "subrip"


def test_two_similar_tracks_are_not_decisive() -> None:
    """When it is genuinely a toss-up, the caller must ask."""
    ranked = rank((track(0, frames=1200), track(1, frames=1180)))
    assert not is_decisive(ranked)


def test_nothing_at_all_is_not_decisive() -> None:
    assert not is_decisive(rank(()))


def test_absence_of_any_track_is_explained() -> None:
    error = explain_absence((), Path("Film.mkv"))
    assert "no subtitle tracks at all" in error.message
    assert error.hint is not None


def test_image_only_tracks_are_named_as_such() -> None:
    """'It has picture subtitles' needs a different response than 'it has none'."""
    error = explain_absence((track(0, codec="hdmv_pgs_subtitle"),), Path("Film.mkv"))
    assert "image-based" in error.message
    assert "hdmv_pgs_subtitle" in error.message
    assert error.hint is not None and "OCR" in error.hint


def test_extension_follows_the_codec() -> None:
    assert track(0, codec="ass").extension == ".ass"
    assert track(0, codec="subrip").extension == ".srt"
    assert track(0, codec="mov_text").extension == ".srt"


def test_description_is_readable() -> None:
    described = track(0, title="English (SDH)", sdh=True, frames=900).describe()
    assert "eng" in described
    assert "SDH" in described
    assert "900 cues" in described
