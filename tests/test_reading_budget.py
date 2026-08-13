"""Reading Budget reporting.

Source subtitles are frequently over budget already - fast television is simply
written that way. Repeating that back as hundreds of warnings buries the
handful of cues the translation actually made worse, so only regressions are
reported and the rest are summarised.

The numbers in these tests come from a real episode: 228 of 535 source cues
were already over 17 chars/sec.
"""

from __future__ import annotations

from aisubtranslator.domain.cue import Cue
from aisubtranslator.domain.report import Degradation
from aisubtranslator.domain.style import StylePreferences
from aisubtranslator.subtitles import payload

STYLE = StylePreferences(max_cps=17.0)


def finish(source: str, translated: str, duration_ms: int) -> payload.Finished:
    cue = Cue(
        id=0,
        start_ms=0,
        end_ms=duration_ms,
        text=source,
        plaintext=source,
        style="Default",
        is_comment=False,
        is_drawing=False,
    )
    return payload.finalise(payload.prepare(cue), translated, STYLE)


def is_reported(finished: payload.Finished) -> bool:
    return any(n.kind is Degradation.HARDER_THAN_SOURCE for n in finished.notes)


def test_a_comfortable_cue_is_not_reported() -> None:
    finished = finish("Hello there", "Hej med dig", 3000)
    assert not finished.over_budget
    assert not is_reported(finished)


def test_a_cue_we_made_worse_is_reported() -> None:
    """Comfortable source, crammed translation - squarely our doing."""
    finished = finish("Yes.", "Ja, det er bestemt rigtigt og sandt her", 2000)
    assert finished.over_budget
    assert is_reported(finished)


def test_an_already_fast_source_is_counted_but_not_reported() -> None:
    """The 209-warning problem: inherited pacing is not a translation defect."""
    fast = "This is a great deal of dialogue for a very short cue indeed"
    finished = finish(fast, "Dette er rigtig meget dialog til en meget kort tekst", 2000)
    assert finished.over_budget
    assert not is_reported(finished)


def test_making_an_already_fast_cue_much_worse_is_still_reported() -> None:
    """Bad source is not a licence to make it much worse."""
    fast = "Short but quick"
    finished = finish(fast, "Meget længere og betydeligt langsommere at læse her", 1000)
    assert is_reported(finished)


def test_a_small_increase_on_an_already_fast_cue_is_not_reported() -> None:
    """Observed in the wild: 18.5 to 19.5 chars/sec, caused by one longer name."""
    source = "Peter Decian, who was convicted of killing his wife"
    finished = finish(source, "Peter Declan, der blev dømt for at have dræbt sin kone", 2700)
    assert finished.over_budget
    assert not is_reported(finished)


def test_crossing_the_budget_from_comfortable_always_counts() -> None:
    """No tolerance here - the source read fine and now it does not."""
    finished = finish("Enough moping.", "Så er det slut med selvmedlidenheden.", 1600)
    assert is_reported(finished)


def test_a_translation_that_improves_pacing_is_not_reported() -> None:
    long_source = "An extremely long line of dialogue crammed into no time at all"
    finished = finish(long_source, "Kort.", 1000)
    assert not is_reported(finished)


def test_the_note_names_both_numbers() -> None:
    """A bare 'too fast' is unactionable; the comparison is the useful part."""
    finished = finish("Yes.", "Ja, det er bestemt rigtigt og sandt her", 2000)
    note = next(n for n in finished.notes if n.kind is Degradation.HARDER_THAN_SOURCE)
    assert "up from" in note.detail
    assert "budget of 17" in note.detail


def test_a_tiny_increase_is_within_tolerance() -> None:
    """Rounding-level differences are not worth a line in a report."""
    source = "Dette er en ret lang linje med tekst"
    finished = finish(source, source + "!", 2000)
    assert not is_reported(finished)
