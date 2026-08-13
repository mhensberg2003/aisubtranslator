"""Reading and writing subtitle files.

pysubs2 normalises every format into ASS-style markup on load and converts back
on save, so SRT's `<i>` and ASS's `{\\i1}` are the same thing internally. That
is why one masking implementation serves all formats.

Writing never mutates the loaded document. A fresh SSAFile is built, carrying
over script info, styles, embedded fonts and graphics, and every per-event field
except the text that was translated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pysubs2

from ..domain.cue import Cue, Track
from ..errors import OutputExistsError, UnsupportedFormatError

#: Formats we will write back out. Others load fine but are converted to SRT,
#: since round-tripping them faithfully is not something we have verified.
ROUND_TRIP_FORMATS = frozenset({"srt", "ass", "ssa", "vtt", "webvtt"})

_EXTENSION = {"ass": ".ass", "ssa": ".ssa", "srt": ".srt", "vtt": ".vtt", "webvtt": ".vtt"}


@dataclass(frozen=True, slots=True)
class Document:
    """A loaded subtitle file: its Cues, plus everything needed to write it back."""

    path: Path
    format: str
    source: pysubs2.SSAFile
    track: Track

    @property
    def output_format(self) -> str:
        return self.format if self.format in ROUND_TRIP_FORMATS else "srt"

    @property
    def output_extension(self) -> str:
        return _EXTENSION.get(self.output_format, ".srt")


def load(path: Path) -> Document:
    """Read a subtitle file into Cues."""
    try:
        subs = pysubs2.load(str(path))
    except (pysubs2.exceptions.UnknownFormatIdentifierError, pysubs2.exceptions.FormatAutodetectionError) as exc:
        raise UnsupportedFormatError(
            f"Cannot read {path.name}: unrecognised subtitle format.",
            hint="Supported: .srt, .ass, .ssa, .vtt, .sub, .ttml.",
        ) from exc
    except UnicodeDecodeError as exc:
        raise UnsupportedFormatError(
            f"Cannot read {path.name}: the file is not valid UTF-8.",
            hint="Re-save it as UTF-8, or convert it with `iconv`.",
        ) from exc
    return from_ssafile(path, subs)


def from_ssafile(path: Path, subs: pysubs2.SSAFile) -> Document:
    """Build a Document from an already-parsed file."""
    cues = tuple(
        Cue(
            id=index,
            start_ms=event.start,
            end_ms=event.end,
            text=event.text,
            plaintext=event.plaintext,
            style=event.style,
            is_comment=event.is_comment,
            is_drawing=event.is_drawing,
        )
        for index, event in enumerate(subs.events)
    )
    fmt = (subs.format or path.suffix.lstrip(".")).lower()
    return Document(
        path=path,
        format=fmt,
        source=subs,
        track=Track(cues=cues, source_format=fmt),
    )


def render(document: Document, translations: Mapping[int, str]) -> pysubs2.SSAFile:
    """Build a new SSAFile with translated Payloads substituted in.

    Cues absent from `translations` keep their source text. Timings, styles,
    layers, margins and effects are copied unchanged - see
    docs/adr/0001-cue-structure-is-immutable.md.
    """
    out = pysubs2.SSAFile()
    out.info = dict(document.source.info)
    out.styles = dict(document.source.styles)
    out.aegisub_project = dict(document.source.aegisub_project)
    out.fonts_opaque = dict(document.source.fonts_opaque)
    out.graphics_opaque = dict(document.source.graphics_opaque)
    out.fps = document.source.fps

    for index, event in enumerate(document.source.events):
        clone = event.copy()
        if index in translations:
            clone.text = translations[index]
        out.append(clone)
    return out


def write(
    subs: pysubs2.SSAFile,
    destination: Path,
    *,
    format_: str,
    overwrite: bool = False,
) -> Path:
    """Save to disk, refusing to clobber unless told otherwise."""
    if destination.exists() and not overwrite:
        raise OutputExistsError(
            f"{destination} already exists.",
            hint="Pass --overwrite to replace it, or -o to choose another path.",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(destination), format_=format_, encoding="utf-8")
    return destination


def sidecar_path(source: Path, language: str, extension: str) -> Path:
    """`Film.2019.mkv` plus `da` gives `Film.2019.da.srt`, beside the source.

    This is the naming media players look for, which is why output lands here
    by default rather than in a tidy separate directory.
    """
    stem = source.stem
    # Strip an existing language suffix so `Film.en.srt` becomes `Film.da.srt`
    # rather than `Film.en.da.srt`.
    parts = stem.rsplit(".", 1)
    if len(parts) == 2 and 2 <= len(parts[1]) <= 3 and parts[1].isalpha():
        stem = parts[0]
    return source.with_name(f"{stem}.{language}{extension}")
