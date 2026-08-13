"""Language codes and names.

The model is prompted with a language *name*, because "Danish" is unambiguous
in a prompt and "da" is not. Files are named with the *code*, because that is
what media players look for in a sidecar filename.
"""

from __future__ import annotations

NAMES = {
    "ar": "Arabic", "bg": "Bulgarian", "cs": "Czech", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "fa": "Persian", "fi": "Finnish", "fr": "French",
    "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian",
    "id": "Indonesian", "is": "Icelandic", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian", "nl": "Dutch",
    "no": "Norwegian", "pl": "Polish", "pt": "Portuguese", "ro": "Romanian",
    "ru": "Russian", "sk": "Slovak", "sl": "Slovenian", "sv": "Swedish",
    "th": "Thai", "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese",
    "zh": "Chinese",
}

#: ISO 639-2 codes as they appear in container metadata, mapped to 639-1.
_THREE_LETTER = {
    "ara": "ar", "bul": "bg", "ces": "cs", "cze": "cs", "dan": "da",
    "deu": "de", "ger": "de", "ell": "el", "gre": "el", "eng": "en",
    "spa": "es", "est": "et", "fas": "fa", "per": "fa", "fin": "fi",
    "fra": "fr", "fre": "fr", "heb": "he", "hin": "hi", "hrv": "hr",
    "hun": "hu", "ind": "id", "isl": "is", "ice": "is", "ita": "it",
    "jpn": "ja", "kor": "ko", "lit": "lt", "lav": "lv", "nld": "nl",
    "dut": "nl", "nor": "no", "pol": "pl", "por": "pt", "ron": "ro",
    "rum": "ro", "rus": "ru", "slk": "sk", "slo": "sk", "slv": "sl",
    "swe": "sv", "tha": "th", "tur": "tr", "ukr": "uk", "vie": "vi",
    "zho": "zh", "chi": "zh",
}

_BY_NAME = {name.casefold(): code for code, name in NAMES.items()}


def to_code(value: str) -> str:
    """Normalise anything the user or a container might say into a short code."""
    cleaned = value.strip().casefold().replace("_", "-").split("-")[0]
    if cleaned in NAMES:
        return cleaned
    if cleaned in _THREE_LETTER:
        return _THREE_LETTER[cleaned]
    if cleaned in _BY_NAME:
        return _BY_NAME[cleaned]
    return cleaned


def to_name(value: str) -> str:
    """The language name to use in a prompt. Unknown values pass through."""
    if not value or value.casefold() in {"auto", "detect"}:
        return "the source language"
    return NAMES.get(to_code(value), value.strip())
