"""Probing and extraction against a real container.

Everything else in the suite is deterministic and offline. This file builds an
actual MKV with ffmpeg and reads it back, because ffprobe's JSON shape and
ffmpeg's stream mapping are exactly the sort of thing a hand-written fake would
get subtly wrong.

Skipped when ffmpeg is unavailable rather than failing the suite.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aisubtranslator import inputs
from aisubtranslator.errors import InputError, NoTextTrackError
from aisubtranslator.media import probe, ranking
from aisubtranslator.subtitles import document

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required for container tests",
)


def _srt(count: int) -> str:
    blocks = []
    for index in range(count):
        start = 1 + index * 2
        blocks.append(
            f"{index + 1}\n"
            f"00:00:{start:02d},000 --> 00:00:{start + 1:02d},000\n"
            f"Line {index + 1} of dialogue.\n"
        )
    return "\n".join(blocks)


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An MKV with full, forced and signs tracks - a typical release layout."""
    directory = tmp_path_factory.mktemp("media")
    for name, count in (("full", 15), ("forced", 2), ("signs", 3)):
        (directory / f"{name}.srt").write_text(_srt(count), encoding="utf-8")

    destination = directory / "Some.Film.2019.mkv"
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=35",
            "-i", str(directory / "full.srt"),
            "-i", str(directory / "forced.srt"),
            "-i", str(directory / "signs.srt"),
            "-map", "0:v", "-map", "1", "-map", "2", "-map", "3",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:s", "srt",
            "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=English",
            "-metadata:s:s:1", "language=eng",
            "-metadata:s:s:1", "title=English (Forced)", "-disposition:s:1", "forced",
            "-metadata:s:s:2", "language=eng", "-metadata:s:s:2", "title=Signs & Songs",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not build the fixture: {result.stderr[:200]}")
    return destination


def test_probe_finds_every_subtitle_stream(video: Path) -> None:
    candidates = probe.probe(video)
    assert len(candidates) == 3
    assert all(c.is_text for c in candidates)
    assert {c.title for c in candidates} == {"English", "English (Forced)", "Signs & Songs"}


def test_dispositions_are_read_from_the_container(video: Path) -> None:
    forced = next(c for c in probe.probe(video) if c.title == "English (Forced)")
    assert forced.is_forced


def test_the_full_track_is_chosen_over_forced_and_signs(video: Path) -> None:
    ranked = ranking.rank(probe.probe(video), preferred_languages=("en",))
    assert ranked[0].candidate.title == "English"
    assert ranking.is_decisive(ranked)


def test_resolve_extracts_the_chosen_track(video: Path, tmp_path: Path) -> None:
    resolved = inputs.resolve(video, work_dir=tmp_path, preferred_languages=("en",))

    assert resolved.was_extracted
    assert resolved.subtitle_path.is_file()
    assert resolved.origin == video

    doc = document.load(resolved.subtitle_path)
    assert len(doc.track.cues) == 15


def test_an_explicit_track_index_overrides_the_ranking(video: Path, tmp_path: Path) -> None:
    resolved = inputs.resolve(video, work_dir=tmp_path, track_index=1)
    assert len(document.load(resolved.subtitle_path).track.cues) == 2


def test_an_unknown_track_index_is_rejected_with_the_options(
    video: Path, tmp_path: Path
) -> None:
    with pytest.raises(InputError, match="no text subtitle track 9") as caught:
        inputs.resolve(video, work_dir=tmp_path, track_index=9)
    assert caught.value.hint is not None
    assert "Available text tracks" in caught.value.hint


def test_a_video_with_no_subtitles_is_explained(tmp_path: Path) -> None:
    """The tool says what it found, not just that it failed."""
    bare = tmp_path / "silent.mkv"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
            "-c:v", "libx264", "-preset", "ultrafast", str(bare),
        ],
        capture_output=True,
        check=False,
    )
    if not bare.is_file():
        pytest.skip("ffmpeg could not build the fixture")

    with pytest.raises(NoTextTrackError, match="no subtitle tracks at all"):
        inputs.resolve(bare, work_dir=tmp_path)


def test_a_subtitle_file_is_used_directly(tmp_path: Path) -> None:
    sidecar = tmp_path / "plain.srt"
    sidecar.write_text(_srt(3), encoding="utf-8")

    resolved = inputs.resolve(sidecar, work_dir=tmp_path)
    assert not resolved.was_extracted
    assert resolved.subtitle_path == sidecar


def test_a_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="directory"):
        inputs.resolve(tmp_path, work_dir=tmp_path)


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="does not exist"):
        inputs.resolve(tmp_path / "nope.mkv", work_dir=tmp_path)
