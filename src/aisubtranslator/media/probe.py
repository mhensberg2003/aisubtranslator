"""Discovering the Subtitle Tracks inside a video container.

Only text Tracks can be extracted. Image-based Tracks - Blu-ray PGS, DVD
VobSub - are recognised and reported by name rather than ignored, because
"this file only has picture subtitles" is a far more useful thing to be told
than "no subtitles found".
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import ExtractionError

TEXT_CODECS = frozenset(
    {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text", "subviewer", "microdvd"}
)
IMAGE_CODECS = frozenset(
    {"hdmv_pgs_subtitle", "dvd_subtitle", "dvbsub", "dvb_subtitle", "xsub"}
)

VIDEO_SUFFIXES = frozenset(
    {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts", ".m2ts", ".mpg", ".mpeg", ".wmv"}
)

#: File extension to extract each text codec into.
_CODEC_EXTENSION = {
    "ass": ".ass",
    "ssa": ".ass",
    "subrip": ".srt",
    "srt": ".srt",
    "mov_text": ".srt",
    "text": ".srt",
    "subviewer": ".srt",
    "microdvd": ".srt",
    "webvtt": ".vtt",
}


@dataclass(frozen=True, slots=True)
class TrackCandidate:
    """One subtitle stream, as ffprobe describes it."""

    stream_index: int
    subtitle_index: int
    codec: str
    language: str | None
    title: str | None
    is_default: bool
    is_forced: bool
    is_hearing_impaired: bool
    frames: int | None

    @property
    def is_text(self) -> bool:
        return self.codec in TEXT_CODECS

    @property
    def is_image(self) -> bool:
        return self.codec in IMAGE_CODECS

    @property
    def extension(self) -> str:
        return _CODEC_EXTENSION.get(self.codec, ".srt")

    def describe(self) -> str:
        parts = [self.language or "und", self.codec]
        if self.title:
            parts.append(f'"{self.title}"')
        flags = [
            name
            for name, on in (
                ("default", self.is_default),
                ("forced", self.is_forced),
                ("sdh", self.is_hearing_impaired),
            )
            if on
        ]
        if flags:
            parts.append("[" + ", ".join(flags) + "]")
        if self.frames:
            parts.append(f"{self.frames} cues")
        return " · ".join(parts)


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_SUFFIXES


def probe(path: Path) -> tuple[TrackCandidate, ...]:
    """List every subtitle stream in a container."""
    executable = shutil.which("ffprobe")
    if executable is None:
        raise ExtractionError(
            "ffprobe is not installed, so subtitles cannot be read out of video files.",
            hint="Install ffmpeg (it provides ffprobe), or pass a subtitle file directly.",
        )

    try:
        completed = subprocess.run(
            [
                executable, "-v", "error",
                "-print_format", "json",
                "-show_streams", "-select_streams", "s",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError(f"ffprobe timed out reading {path.name}.") from exc

    if completed.returncode != 0:
        raise ExtractionError(
            f"ffprobe could not read {path.name}.",
            hint=completed.stderr.strip()[:300] or None,
        )

    try:
        streams = json.loads(completed.stdout or "{}").get("streams", [])
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"ffprobe returned unreadable output for {path.name}.") from exc

    return tuple(
        _candidate(stream, position) for position, stream in enumerate(streams)
    )


def _candidate(stream: dict, subtitle_index: int) -> TrackCandidate:
    tags = {k.lower(): v for k, v in (stream.get("tags") or {}).items()}
    disposition = stream.get("disposition") or {}
    return TrackCandidate(
        stream_index=int(stream.get("index", subtitle_index)),
        subtitle_index=subtitle_index,
        codec=str(stream.get("codec_name", "unknown")).lower(),
        language=tags.get("language"),
        title=tags.get("title"),
        is_default=bool(disposition.get("default")),
        is_forced=bool(disposition.get("forced")),
        is_hearing_impaired=bool(disposition.get("hearing_impaired")),
        frames=_int_or_none(tags.get("number_of_frames")),
    )


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
