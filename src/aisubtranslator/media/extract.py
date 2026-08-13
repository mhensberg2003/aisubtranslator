"""Pulling a text Subtitle Track out of a video container.

This is the documented edge of scope. Image-based Tracks and containers with no
Track at all are reported precisely, naming what was actually found, rather
than failing with a generic message - see NoTextTrackError.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..errors import ExtractionError, NoTextTrackError
from .probe import TrackCandidate


def extract(source: Path, candidate: TrackCandidate, destination: Path) -> Path:
    """Write one subtitle stream out to a file."""
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise ExtractionError(
            "ffmpeg is not installed, so subtitles cannot be extracted from video.",
            hint="Install ffmpeg, or pass a subtitle file directly.",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                executable, "-v", "error", "-y",
                "-i", str(source),
                "-map", f"0:s:{candidate.subtitle_index}",
                str(destination),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError(f"ffmpeg timed out extracting from {source.name}.") from exc

    if completed.returncode != 0 or not destination.is_file():
        raise ExtractionError(
            f"ffmpeg could not extract track {candidate.subtitle_index} "
            f"from {source.name}.",
            hint=completed.stderr.strip()[:300] or None,
        )
    return destination


def explain_absence(candidates: tuple[TrackCandidate, ...], source: Path) -> NoTextTrackError:
    """Build the error for a container with no usable text Track.

    Says what was actually found, because "it has picture subtitles" and "it has
    no subtitles" call for completely different next steps from the user.
    """
    if not candidates:
        return NoTextTrackError(
            f"{source.name} contains no subtitle tracks at all.",
            hint="Find a subtitle file for it and pass that instead. "
            "Transcribing the audio is not something this tool does.",
        )

    image = [c for c in candidates if c.is_image]
    if image:
        kinds = ", ".join(sorted({c.codec for c in image}))
        return NoTextTrackError(
            f"{source.name} has {len(image)} subtitle track(s), but they are "
            f"image-based ({kinds}) rather than text.",
            hint="These are pictures of text and would need OCR, which is out "
            "of scope. Look for an .srt or .ass file for this release instead.",
        )

    kinds = ", ".join(sorted({c.codec for c in candidates}))
    return NoTextTrackError(
        f"{source.name} has subtitle tracks, but none in a format that can be "
        f"read as text (found: {kinds}).",
        hint="Pass a subtitle file directly instead.",
    )
