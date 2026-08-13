"""Re-wrapping and the Reading Budget.

The rule that matters most here is negative: nothing is ever shortened. A line
that will not fit is still emitted whole.
"""

from __future__ import annotations

import pytest

from aisubtranslator.subtitles.wrap import (
    characters_per_second,
    rewrap,
    visible_length,
)

LIMITS = {"max_line_length": 42, "max_lines": 2}


def test_short_text_stays_on_one_line() -> None:
    assert rewrap("Hej med dig.", **LIMITS) == "Hej med dig."


def test_source_line_breaks_are_discarded() -> None:
    """Breaks are re-derived, not mirrored - Danish breaks elsewhere."""
    assert rewrap("Hello\nthere", **LIMITS) == "Hello there"


def test_long_text_is_split_into_two_lines() -> None:
    text = (
        "Dette er en betydeligt længere replik som helt sikkert skal "
        "ombrydes over to linjer."
    )
    result = rewrap(text, **LIMITS)
    assert result.count("\n") == 1
    assert all(len(line) <= 42 for line in result.split("\n"))


def test_no_words_are_lost_when_wrapping() -> None:
    text = " ".join(f"ord{i}" for i in range(40))
    result = rewrap(text, **LIMITS)
    assert result.replace("\n", " ").split() == text.split()


def test_unwrappable_text_is_still_emitted_complete() -> None:
    """Too long for the budget is a reporting matter, never a truncation."""
    text = " ".join(["supercalifragilisticexpialidocious"] * 6)
    result = rewrap(text, **LIMITS)
    assert result.count("\n") <= 1
    assert result.replace("\n", " ").split() == text.split()


def test_a_single_unbreakable_word_is_returned_intact() -> None:
    word = "x" * 80
    assert rewrap(word, **LIMITS) == word


def test_breaks_prefer_punctuation() -> None:
    text = "Han gik hjem igen, og hun blev tilbage i huset ved søen."
    result = rewrap(text, **LIMITS)
    assert result.split("\n")[0].endswith(",")


def test_max_lines_of_one_never_breaks() -> None:
    text = "a much longer line than the limit allows for certain"
    assert "\n" not in rewrap(text, max_line_length=10, max_lines=1)


def test_empty_input_survives() -> None:
    assert rewrap("", **LIMITS) == ""
    assert rewrap("   ", **LIMITS) == ""


def test_two_speakers_keep_their_own_lines() -> None:
    """Merging two speakers reads as one person saying both halves."""
    assert rewrap("- Gjorde du?\n- Ja.", **LIMITS) == "- Gjorde du?\n- Ja."


def test_two_speakers_stay_split_even_when_short() -> None:
    """Short enough to fit on one line is exactly when the bug used to bite."""
    result = rewrap("- Ja.\n- Nej.", **LIMITS)
    assert result.count("\n") == 1


def test_two_speakers_stay_split_even_when_long() -> None:
    """Speaker separation outranks the line-length budget."""
    long_exchange = (
        "- Tror du virkelig at han er fuldstændig uskyldig i alt det her?\n"
        "- Det er der i hvert fald nogen der gør."
    )
    assert rewrap(long_exchange, **LIMITS).count("\n") == 1


def test_a_continuation_line_belongs_to_the_speaker_above_it() -> None:
    result = rewrap("- First speaker\n- Second speaker\nstill speaking", **LIMITS)
    assert result.split("\n") == ["- First speaker", "- Second speaker still speaking"]


def test_a_single_dash_is_not_two_speakers() -> None:
    """One dashed line wrapped over two lines is one person, and re-wraps."""
    assert rewrap("- Only one person\nspeaking here", **LIMITS) == (
        "- Only one person speaking here"
    )


def test_a_hyphen_mid_sentence_is_not_a_speaker_marker() -> None:
    assert "\n" not in rewrap("Well-known and much-loved", **LIMITS)


@pytest.mark.parametrize("dash", ["-", "–", "—"])
def test_all_dash_characters_mark_speakers(dash: str) -> None:
    assert rewrap(f"{dash} Ja.\n{dash} Nej.", **LIMITS).count("\n") == 1


def test_sentinels_do_not_count_toward_length() -> None:
    assert visible_length(f"ab{chr(0xE000)}cd") == 4


@pytest.mark.parametrize(
    ("text", "duration_ms", "expected"),
    [
        ("12345", 1000, 5.0),
        ("12345", 500, 10.0),
        ("", 1000, 0.0),
        ("abc", 0, 0.0),
    ],
)
def test_characters_per_second(text: str, duration_ms: int, expected: float) -> None:
    assert characters_per_second(text, duration_ms) == pytest.approx(expected)


def test_reading_budget_ignores_line_breaks() -> None:
    """A break is not a character the viewer reads."""
    assert characters_per_second("ab\ncd", 1000) == pytest.approx(5.0)
