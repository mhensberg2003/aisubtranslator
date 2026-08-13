"""Job checkpointing.

A Job is one resumable execution over one Track. Completed Chunks are written
out as they land, so an interrupted run resumes instead of restarting and never
re-pays for work already done.

The fingerprint covers everything that would change the output: the source
text, the model, the languages, the Style Preferences, the chunking, and the
Bible. If any of those change the checkpoint is discarded rather than
misapplied - editing a name in the Bible is meant to retranslate, not to be
silently ignored.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.report import Usage


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Translations completed so far for one Job."""

    fingerprint: str
    translations: dict[int, str] = field(default_factory=dict)
    failed: frozenset[int] = field(default_factory=frozenset)
    usage: Usage = field(default_factory=Usage)

    def merged(
        self,
        translations: dict[int, str],
        failed: frozenset[int],
        usage: Usage,
    ) -> Checkpoint:
        return Checkpoint(
            fingerprint=self.fingerprint,
            translations={**self.translations, **translations},
            failed=self.failed | failed,
            usage=self.usage.plus(usage),
        )

    @property
    def done_ids(self) -> frozenset[int]:
        return frozenset(self.translations)


def fingerprint(*parts: str) -> str:
    """A stable digest of everything that affects the output."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:32]


def checkpoint_path(state_dir: Path, source_name: str, target_language: str) -> Path:
    stem = hashlib.sha256(f"{source_name}:{target_language}".encode()).hexdigest()[:16]
    return state_dir / "jobs" / f"{stem}.json"


def load(path: Path, expected: str) -> Checkpoint:
    """Read a checkpoint, returning an empty one if absent or stale."""
    if not path.is_file():
        return Checkpoint(fingerprint=expected)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Checkpoint(fingerprint=expected)

    if raw.get("fingerprint") != expected:
        return Checkpoint(fingerprint=expected)

    usage = raw.get("usage") or {}
    return Checkpoint(
        fingerprint=expected,
        translations={int(k): str(v) for k, v in (raw.get("translations") or {}).items()},
        failed=frozenset(int(i) for i in raw.get("failed") or []),
        usage=Usage(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            requests=int(usage.get("requests", 0)),
            cost_usd=usage.get("cost_usd"),
        ),
    )


def save(path: Path, checkpoint: Checkpoint) -> None:
    """Write a checkpoint atomically, so an interrupt cannot corrupt it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fingerprint": checkpoint.fingerprint,
        "translations": {str(k): v for k, v in checkpoint.translations.items()},
        "failed": sorted(checkpoint.failed),
        "usage": {
            "prompt_tokens": checkpoint.usage.prompt_tokens,
            "completion_tokens": checkpoint.usage.completion_tokens,
            "requests": checkpoint.usage.requests,
            "cost_usd": checkpoint.usage.cost_usd,
        },
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def clear(path: Path) -> None:
    path.unlink(missing_ok=True)
