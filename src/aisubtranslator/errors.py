"""Exception hierarchy.

Every error a user can plausibly cause carries a message written for a person
reading a terminal, not a stack trace. Internal invariant violations raise
plain assertions instead — those are bugs, not conditions.
"""

from __future__ import annotations


class SubtranslatorError(Exception):
    """Base for every error this tool raises deliberately."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class InputError(SubtranslatorError):
    """The input cannot be used, and the user needs to do something about it."""


class NoTextTrackError(InputError):
    """A video was supplied but carries no extractable text Subtitle Track.

    This is the documented edge of scope: image-based tracks (Blu-ray PGS,
    DVD VobSub) and media with no subtitles at all both land here.
    """


class ExtractionError(InputError):
    """ffmpeg or ffprobe failed, or is not installed."""


class UnsupportedFormatError(InputError):
    """The subtitle file is not in a format pysubs2 can read."""


class ConfigError(SubtranslatorError):
    """Configuration is missing or contradictory - notably a missing API key."""


class ProviderError(SubtranslatorError):
    """The translation provider failed in a way we cannot recover from."""


class OutputExistsError(SubtranslatorError):
    """The destination file exists and we were not told to overwrite it."""
