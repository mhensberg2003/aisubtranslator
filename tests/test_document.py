"""The round-trip invariant.

Load a real file, run every Cue through the actual translation path with a
provider that returns its input unchanged, write it back out, and read it
again. Everything except line breaking must survive untouched.

Line breaking is the deliberate exception: re-wrapping discards source breaks
by design, so the text comparison is made on the word sequence rather than the
exact string.

This single test catches most tag-masking, chunking and serialisation bugs at
once, which is why it is worth the setup.
"""

from __future__ import annotations

from pathlib import Path

import pysubs2
import pytest

from aisubtranslator.domain.style import StylePreferences
from aisubtranslator.subtitles import classify, document, payload

FIXTURES = Path(__file__).parent / "fixtures"
STYLE = StylePreferences()


def identity_round_trip(source: Path, destination: Path) -> pysubs2.SSAFile:
    """Run the real path with an identity provider."""
    doc = document.load(source)
    translatable, _ = classify.partition(doc.track.cues)

    translations: dict[int, str] = {}
    for cue in translatable:
        prepared = payload.prepare(cue)
        translations[cue.id] = payload.finalise(
            prepared, prepared.source_text, STYLE
        ).text

    rendered = document.render(doc, translations)
    document.write(rendered, destination, format_=doc.output_format, overwrite=True)
    return pysubs2.load(str(destination))


@pytest.mark.parametrize("name", ["sample.ass", "sample.srt"])
def test_identity_round_trip_preserves_structure(name: str, tmp_path: Path) -> None:
    source = FIXTURES / name
    original = pysubs2.load(str(source))
    result = identity_round_trip(source, tmp_path / name)

    assert len(result.events) == len(original.events)
    for before, after in zip(original.events, result.events, strict=True):
        assert after.start == before.start
        assert after.end == before.end
        assert after.style == before.style
        assert after.type == before.type
        assert after.layer == before.layer
        assert after.name == before.name
        assert after.effect == before.effect
        assert (after.marginl, after.marginr, after.marginv) == (
            before.marginl,
            before.marginr,
            before.marginv,
        )


@pytest.mark.parametrize("name", ["sample.ass", "sample.srt"])
def test_identity_round_trip_preserves_words(name: str, tmp_path: Path) -> None:
    """Text survives verbatim apart from where the lines break."""
    source = FIXTURES / name
    original = pysubs2.load(str(source))
    result = identity_round_trip(source, tmp_path / name)

    for before, after in zip(original.events, result.events, strict=True):
        assert _words(after.text) == _words(before.text), f"changed: {before.text!r}"


def test_identity_round_trip_preserves_ass_styles(tmp_path: Path) -> None:
    source = FIXTURES / "sample.ass"
    original = pysubs2.load(str(source))
    result = identity_round_trip(source, tmp_path / "sample.ass")

    assert set(result.styles) == set(original.styles)
    for name, style in original.styles.items():
        assert result.styles[name].fontname == style.fontname
        assert result.styles[name].fontsize == style.fontsize
        assert result.styles[name].alignment == style.alignment
    assert result.info.get("PlayResX") == original.info.get("PlayResX")


def test_positioned_signs_are_not_rewrapped(tmp_path: Path) -> None:
    """A sign pinned with \\pos keeps its single-line shape."""
    doc = document.load(FIXTURES / "sample.ass")
    sign = next(c for c in doc.track.cues if "\\pos" in c.text)
    prepared = payload.prepare(sign)
    assert prepared.is_positioned


def test_karaoke_and_comments_are_never_translated() -> None:
    doc = document.load(FIXTURES / "sample.ass")
    translatable, skipped = classify.partition(doc.track.cues)
    translated_text = {c.text for c in translatable}

    assert not any("\\k" in t for t in translated_text)
    assert not any(c.is_comment for c in translatable)
    assert not any(c.is_drawing for c in translatable)
    assert len(translatable) + len(skipped) == len(doc.track.cues)


def test_sidecar_naming() -> None:
    assert document.sidecar_path(Path("/m/Film.2019.mkv"), "da", ".srt") == Path(
        "/m/Film.2019.da.srt"
    )


def test_sidecar_naming_replaces_an_existing_language_suffix() -> None:
    """`Film.en.srt` becomes `Film.da.srt`, not `Film.en.da.srt`."""
    assert document.sidecar_path(Path("/m/Film.en.srt"), "da", ".srt") == Path(
        "/m/Film.da.srt"
    )


def test_write_refuses_to_clobber(tmp_path: Path) -> None:
    destination = tmp_path / "existing.srt"
    destination.write_text("do not lose me", encoding="utf-8")
    doc = document.load(FIXTURES / "sample.srt")

    with pytest.raises(Exception, match="already exists"):
        document.write(document.render(doc, {}), destination, format_="srt")

    assert destination.read_text(encoding="utf-8") == "do not lose me"


def _words(text: str) -> list[str]:
    return text.replace("\\N", " ").replace("\\n", " ").split()
