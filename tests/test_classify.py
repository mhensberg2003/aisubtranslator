"""Which Cues carry translatable Payload.

The bias is deliberate: skipping a real line is far worse than translating a
line that did not need it, so every rule here has to be conservative.
"""

from __future__ import annotations

import pytest

from aisubtranslator.domain.cue import Cue, PassThrough
from aisubtranslator.subtitles.classify import classify, is_credit, partition


def make_cue(
    text: str,
    *,
    cue_id: int = 0,
    plaintext: str | None = None,
    is_comment: bool = False,
    is_drawing: bool = False,
) -> Cue:
    return Cue(
        id=cue_id,
        start_ms=0,
        end_ms=2000,
        text=text,
        plaintext=plaintext if plaintext is not None else text,
        style="Default",
        is_comment=is_comment,
        is_drawing=is_drawing,
    )


def test_ordinary_dialogue_is_translated() -> None:
    assert classify(make_cue("Where are you going?")) is None


def test_authoring_comments_pass_through() -> None:
    cue = make_cue("TL note: check this", is_comment=True)
    assert classify(cue) is PassThrough.COMMENT


def test_drawings_pass_through() -> None:
    cue = make_cue(r"{\p1}m 0 0 l 100 0{\p0}", is_drawing=True)
    assert classify(cue) is PassThrough.DRAWING


def test_karaoke_passes_through() -> None:
    cue = make_cue(r"{\k20}Hel{\k15}lo", plaintext="Hello")
    assert classify(cue) is PassThrough.KARAOKE


@pytest.mark.parametrize("text", ["♪", "♪♪", "- -", "...", "123", "  "])
def test_letterless_cues_pass_through(text: str) -> None:
    assert classify(make_cue(text)) is PassThrough.NO_LETTERS


@pytest.mark.parametrize(
    "text",
    [
        "Subtitles by OpenSubtitles.org",
        "Sync by www.addic7ed.com",
        "Translated by explosiveskull",
        "Subs by: YIFY",
    ],
)
def test_release_credits_pass_through(text: str) -> None:
    assert is_credit(text)


@pytest.mark.parametrize(
    "text",
    [
        "He translated the letter for me.",
        "Turn on the subtitles, please.",
        "The sync is off by a second.",
        "She was corrected by her teacher.",
        "Subtitles are for people who can't hear.",
    ],
)
def test_ordinary_dialogue_is_not_mistaken_for_a_credit(text: str) -> None:
    """The expensive false positive: silently deleting a real line."""
    assert not is_credit(text)


def test_partition_separates_and_explains() -> None:
    cues = (
        make_cue("Real dialogue.", cue_id=0),
        make_cue("note", cue_id=1, is_comment=True),
        make_cue("♪", cue_id=2),
        make_cue("More dialogue.", cue_id=3),
    )
    translatable, skipped = partition(cues)

    assert [c.id for c in translatable] == [0, 3]
    assert skipped == {1: PassThrough.COMMENT, 2: PassThrough.NO_LETTERS}


def test_partition_accounts_for_every_cue() -> None:
    """Nothing may vanish between the two buckets."""
    cues = tuple(
        make_cue(t, cue_id=i)
        for i, t in enumerate(["Hello", "♪", "World", "Subs by www.x.com"])
    )
    translatable, skipped = partition(cues)
    assert len(translatable) + len(skipped) == len(cues)
