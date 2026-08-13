"""Override Tag masking must be exactly reversible.

If it is not, the file we write is corrupt in a way that only shows up while
watching. These are the tightest tests in the suite for that reason.

Sentinels are written as explicit codepoints rather than literals throughout -
a Private Use Area character pasted into source is invisible and unreviewable.
"""

from __future__ import annotations

import pytest

from aisubtranslator.subtitles import tags

SENTINEL_0 = chr(0xE000)

PAYLOADS = [
    "Plain text with no markup at all.",
    r"{\i1}Fully italic line{\i0}",
    r"{\i1}Hello{\i0} there,\Nmy friend!",
    r"{\an8\pos(960,120)}CLOSED FOR WINTER",
    r"{\an8}\h\hA sign with leading markup only",
    r"Text then a tag{\i1} then more text{\i0} then an end.",
    r"Line one\NLine two\NLine three",
    r"{\b1}Bold{\b0} and {\i1}italic{\i0} together",
    r"\h\hIndented without any braces",
    "",
]


def has_sentinel(text: str) -> bool:
    return any(0xE000 <= ord(c) < 0xE080 for c in text)


@pytest.mark.parametrize("raw", PAYLOADS)
def test_identity_masking_is_lossless(raw: str) -> None:
    """Masking then restoring unchanged text must return the original exactly."""
    masked = tags.mask(raw)
    restored, degraded = tags.restore(masked, masked.text)
    assert restored == raw
    assert not degraded


def test_leading_tags_are_never_shown_to_the_model() -> None:
    masked = tags.mask(r"{\an8\pos(960,120)}CLOSED")
    assert masked.text == "CLOSED"
    assert masked.leading == r"{\an8\pos(960,120)}"
    assert masked.is_riskless


def test_a_fully_wrapped_line_needs_no_sentinels() -> None:
    """The commonest ASS case - one tag each side - carries zero risk."""
    masked = tags.mask(r"{\i1}Fully italic{\i0}")
    assert masked.text == "Fully italic"
    assert masked.is_riskless


def test_line_breaks_become_real_newlines_for_the_model() -> None:
    masked = tags.mask(r"First line\NSecond line")
    assert masked.text == "First line\nSecond line"


def test_translation_can_move_inline_tags() -> None:
    """Word order changes between languages; sentinels move with the words."""
    masked = tags.mask(r"the {\i1}red{\i0} car")
    translated = (
        masked.text.replace("the ", "den ").replace("red", "røde").replace("car", "bil")
    )
    restored, degraded = tags.restore(masked, translated)
    assert restored == r"den {\i1}røde{\i0} bil"
    assert not degraded


def test_dropped_sentinel_degrades_instead_of_corrupting() -> None:
    """A model that eats a sentinel loses the italics, not the line."""
    masked = tags.mask(r"a {\i1}b{\i0} c")
    stripped = "".join(c for c in masked.text if not has_sentinel(c))
    restored, degraded = tags.restore(masked, stripped)
    assert degraded
    assert restored == "a b c"
    assert not has_sentinel(restored)


def test_invented_sentinels_never_reach_the_file() -> None:
    """A model hallucinating a sentinel into untagged text is contained."""
    masked = tags.mask("plain")
    restored, _ = tags.restore(masked, f"pl{SENTINEL_0}ain")
    assert restored == "plain"
    assert not has_sentinel(restored)


def test_duplicated_sentinel_is_treated_as_corruption() -> None:
    masked = tags.mask(r"a {\i1}b{\i0} c")
    restored, degraded = tags.restore(masked, masked.text + SENTINEL_0)
    assert degraded
    assert not has_sentinel(restored)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"{\k20}Hel{\k15}lo", True),
        (r"{\kf30}Hello", True),
        (r"{\K40}Hello", True),
        (r"{\i1}Hello", False),
        ("Hello", False),
    ],
)
def test_karaoke_detection(raw: str, expected: bool) -> None:
    assert tags.is_karaoke(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"{\an8}Sign", True),
        (r"{\pos(10,10)}Sign", True),
        (r"{\move(0,0,10,10)}Sign", True),
        (r"{\i1}Dialogue", False),
        ("Dialogue", False),
    ],
)
def test_positioning_detection(raw: str, expected: bool) -> None:
    assert tags.has_positioning(raw) is expected
