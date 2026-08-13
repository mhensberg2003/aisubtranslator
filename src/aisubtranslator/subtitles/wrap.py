"""Line breaking and the Reading Budget.

Source line breaks are discarded rather than mirrored. Danish word order puts
the natural break somewhere other than where English put it, so preserving the
original break points reliably lands them mid-phrase.

Nothing here ever shortens text. A translation that will not fit is still
emitted in full and recorded in the Run Report; silently dropping words a
viewer needed is worse than a line that runs long.
"""

from __future__ import annotations

import re

_PUA_START = 0xE000
_PUA_END = 0xE080

#: A line opening with a dash marks a change of speaker. Two of them in one Cue
#: means two people are talking, and each must keep its own line - merging them
#: onto one line makes it read as a single speaker saying both halves.
_SPEAKER_DASH = re.compile(r"^[-–—]\s*(?=\S)")

#: Breaking after these is much better than breaking mid-phrase.
_CLAUSE_END = re.compile(r"[.,!?;:…]$")

#: Breaking *before* these keeps a phrase intact.
_PHRASE_START = frozenset(
    {
        "og", "eller", "men", "at", "som", "der", "hvis", "fordi", "mens",
        "når", "da", "så", "for", "til", "med", "på", "i", "af", "om",
        "and", "or", "but", "that", "which", "who", "if", "because", "while",
        "when", "then", "for", "to", "with", "on", "in", "of", "about",
    }
)


def visible_length(text: str) -> int:
    """Length as a viewer perceives it - sentinels are invisible."""
    return sum(1 for c in text if not _PUA_START <= ord(c) < _PUA_END)


def characters_per_second(text: str, duration_ms: int) -> float:
    """Reading load. Zero-duration Cues report 0 rather than dividing by zero."""
    if duration_ms <= 0:
        return 0.0
    visible = visible_length(text.replace("\n", " "))
    return visible / (duration_ms / 1000.0)


def rewrap(text: str, *, max_line_length: int, max_lines: int) -> str:
    """Re-break text into at most `max_lines` balanced lines.

    Existing breaks are discarded first. If the text cannot fit within the
    line budget it is still returned complete, using the allowed number of
    lines - overflow is a reporting concern, not a truncation trigger.
    """
    segments = speaker_segments(text)
    if len(segments) >= 2:
        # One speaker per line, whatever the lengths. Reading two people's
        # words as one sentence is a worse failure than a long line.
        return "\n".join(segments)

    flat = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if not flat:
        return text.strip()
    if visible_length(flat) <= max_line_length or max_lines <= 1:
        return flat

    words = flat.split(" ")
    if len(words) == 1:
        return flat

    target_lines = min(
        max_lines,
        max(2, -(-visible_length(flat) // max_line_length)),
    )
    return "\n".join(_split_balanced(words, target_lines, max_line_length))


def speaker_segments(text: str) -> list[str]:
    """Split a Cue into one segment per speaker, or [] if it is not dialogue.

    A continuation line - one that does not itself open with a dash - belongs
    to the speaker above it, so `- A / - B / and more from B` is two segments,
    not three.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []

    opens = [bool(_SPEAKER_DASH.match(line)) for line in lines]
    if sum(opens) < 2:
        return []

    segments: list[str] = []
    for line, is_new_speaker in zip(lines, opens, strict=True):
        if is_new_speaker or not segments:
            segments.append(line)
        else:
            segments[-1] += " " + line
    return segments if len(segments) >= 2 else []


def _split_balanced(words: list[str], lines: int, max_line_length: int) -> list[str]:
    """Split words into `lines` chunks, balanced and preferring good breaks."""
    if lines <= 1 or len(words) < lines:
        return [" ".join(words)]

    best = _best_break(words, lines, max_line_length)
    head = " ".join(words[:best])
    rest = _split_balanced(words[best:], lines - 1, max_line_length)
    return [head, *rest]


#: Overflowing a line is worse than an uneven split, so it must dominate the
#: stylistic bonuses rather than compete with them.
_OVERFLOW_PENALTY = 10.0
_CLAUSE_BONUS = 0.25
_PHRASE_BONUS = 0.15


def _best_break(words: list[str], lines: int, max_line_length: int) -> int:
    """Choose the word index to break at, nearest an even split.

    Both resulting sides are checked against the line length. Scoring only the
    first line lets the remainder overflow unnoticed, which is precisely the
    case a two-line subtitle hits most often.
    """
    # Cumulative visible length of words[:i] joined by single spaces.
    prefix: list[int] = [0]
    for word in words:
        separator = 1 if prefix[-1] else 0
        prefix.append(prefix[-1] + separator + visible_length(word))
    total = prefix[-1]
    ideal = total / lines

    last = len(words) - (lines - 2) if lines > 2 else len(words)
    best_index = 1
    best_score = float("inf")

    for index in range(1, max(2, last)):
        head = prefix[index]
        tail = total - head - 1
        score = abs(head - ideal)
        if head > max_line_length:
            score += (head - max_line_length) * _OVERFLOW_PENALTY
        if lines == 2 and tail > max_line_length:
            score += (tail - max_line_length) * _OVERFLOW_PENALTY
        if _CLAUSE_END.search(words[index - 1]):
            score -= max_line_length * _CLAUSE_BONUS
        if words[index].casefold().strip("—-") in _PHRASE_START:
            score -= max_line_length * _PHRASE_BONUS
        if score < best_score:
            best_score, best_index = score, index
    return best_index
