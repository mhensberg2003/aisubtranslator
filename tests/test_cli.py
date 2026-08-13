"""The command-line surface.

Covers what a person actually types, and - more importantly - what they are
told when something is wrong. A confusing error at this layer is the difference
between a tool you keep and one you delete.

The provider is swapped for a fake, so nothing here touches the network.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aisubtranslator import cli
from aisubtranslator.translate.provider import PrefixProvider, UnreliableProvider

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read or write the developer's real config directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> PrefixProvider:
    provider = PrefixProvider()
    monkeypatch.setattr(cli, "OpenRouterProvider", lambda **_: provider)
    return provider


@pytest.fixture
def media(tmp_path: Path) -> Path:
    destination = tmp_path / "Some.Film.2019.srt"
    shutil.copy(FIXTURES / "sample.srt", destination)
    return destination


def test_translate_writes_a_sidecar_beside_the_source(
    media: Path, fake_provider: PrefixProvider
) -> None:
    result = runner.invoke(cli.app, ["translate", str(media), "--to", "da"])

    assert result.exit_code == 0, result.output
    sidecar = media.with_name("Some.Film.2019.da.srt")
    assert sidecar.is_file()
    assert "DA:" in sidecar.read_text(encoding="utf-8")


def test_translate_refuses_to_clobber(media: Path, fake_provider: PrefixProvider) -> None:
    sidecar = media.with_name("Some.Film.2019.da.srt")
    sidecar.write_text("mine", encoding="utf-8")

    result = runner.invoke(cli.app, ["translate", str(media)])
    assert result.exit_code == 1
    assert "already exists" in result.output
    assert sidecar.read_text(encoding="utf-8") == "mine"


def test_overwrite_is_available_when_asked_for(
    media: Path, fake_provider: PrefixProvider
) -> None:
    sidecar = media.with_name("Some.Film.2019.da.srt")
    sidecar.write_text("mine", encoding="utf-8")

    result = runner.invoke(cli.app, ["translate", str(media), "--overwrite"])
    assert result.exit_code == 0, result.output
    assert "DA:" in sidecar.read_text(encoding="utf-8")


def test_an_explicit_output_path_is_honoured(
    media: Path, tmp_path: Path, fake_provider: PrefixProvider
) -> None:
    destination = tmp_path / "elsewhere" / "out.srt"
    result = runner.invoke(
        cli.app, ["translate", str(media), "-o", str(destination)]
    )
    assert result.exit_code == 0, result.output
    assert destination.is_file()


def test_a_report_is_written_only_when_something_degraded(
    media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean runs leave no clutter; degraded runs leave the details."""
    monkeypatch.setattr(
        cli, "OpenRouterProvider", lambda **_: UnreliableProvider(mode="drop", fails_for=99)
    )
    result = runner.invoke(cli.app, ["translate", str(media)])

    assert result.exit_code == 0, result.output
    report = media.with_name("Some.Film.2019.da.srt.report.md")
    assert report.is_file()
    assert "source text kept" in report.read_text(encoding="utf-8")


def test_a_missing_api_key_is_explained(
    media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(cli.app, ["translate", str(media)])

    assert result.exit_code == 1
    assert "No OpenRouter API key" in result.output
    assert "openrouter.ai/keys" in result.output


def test_a_missing_file_is_explained(tmp_path: Path, fake_provider: PrefixProvider) -> None:
    result = runner.invoke(cli.app, ["translate", str(tmp_path / "nope.srt")])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_an_unreadable_format_is_explained(
    tmp_path: Path, fake_provider: PrefixProvider
) -> None:
    junk = tmp_path / "not-a-subtitle.srt"
    junk.write_bytes(b"\xff\xfe\x00 this is not a subtitle file at all")

    result = runner.invoke(cli.app, ["translate", str(junk)])
    assert result.exit_code == 1
    assert "Cannot read" in result.output


def test_the_bible_is_reported_per_work(
    media: Path, fake_provider: PrefixProvider
) -> None:
    assert runner.invoke(cli.app, ["bible", str(media)]).exit_code == 0

    runner.invoke(cli.app, ["translate", str(media)])
    result = runner.invoke(cli.app, ["bible", str(media)])
    assert result.exit_code == 0


def test_style_init_writes_defaults_once(tmp_path: Path) -> None:
    first = runner.invoke(cli.app, ["style", "--init"])
    assert first.exit_code == 0
    assert "Wrote defaults" in first.output

    second = runner.invoke(cli.app, ["style", "--init"])
    assert "Already exists" in second.output


def test_style_shows_the_active_preferences() -> None:
    result = runner.invoke(cli.app, ["style"])
    assert result.exit_code == 0
    assert "du-form" in result.output


def test_tracks_rejects_a_file_with_no_subtitle_streams(tmp_path: Path) -> None:
    junk = tmp_path / "empty.mkv"
    junk.write_bytes(b"not really an mkv")
    result = runner.invoke(cli.app, ["tracks", str(junk)])
    assert result.exit_code == 1


def test_resuming_makes_no_further_requests(
    media: Path, fake_provider: PrefixProvider
) -> None:
    runner.invoke(cli.app, ["translate", str(media)])
    calls_after_first = len(fake_provider.calls)

    result = runner.invoke(cli.app, ["translate", str(media), "--overwrite"])
    assert result.exit_code == 0, result.output
    assert len(fake_provider.calls) == calls_after_first


def test_no_resume_starts_over(media: Path, fake_provider: PrefixProvider) -> None:
    runner.invoke(cli.app, ["translate", str(media)])
    calls_after_first = len(fake_provider.calls)

    runner.invoke(cli.app, ["translate", str(media), "--overwrite", "--no-resume"])
    assert len(fake_provider.calls) > calls_after_first


def test_sample_prints_source_and_translation_side_by_side(
    media: Path, fake_provider: PrefixProvider
) -> None:
    result = runner.invoke(cli.app, ["sample", str(media), "-n", "2"])

    assert result.exit_code == 0, result.output
    assert "DA:" in result.output
    assert "Danish" in result.output
    # Nothing is written to disk by a sample.
    assert not media.with_name("Some.Film.2019.da.srt").exists()


def test_sample_needs_a_key(media: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(cli.app, ["sample", str(media)])
    assert result.exit_code == 1
    assert "No OpenRouter API key" in result.output


def test_sample_reports_a_file_with_nothing_translatable(
    tmp_path: Path, fake_provider: PrefixProvider
) -> None:
    empty = tmp_path / "silent.srt"
    empty.write_text("1\n00:00:01,000 --> 00:00:02,000\n♪\n", encoding="utf-8")

    result = runner.invoke(cli.app, ["sample", str(empty)])
    assert result.exit_code == 1
    assert "nothing to translate" in result.output


def test_the_picker_accepts_a_valid_track(monkeypatch: pytest.MonkeyPatch) -> None:
    from aisubtranslator.media.ranking import rank

    from .test_ranking import track

    ranked = rank((track(0, frames=1200), track(1, frames=1180)))
    monkeypatch.setattr(cli.typer, "prompt", lambda *_, **__: 1)
    assert cli._ask_which_track(ranked).candidate.subtitle_index == 1


def test_the_picker_re_asks_until_the_answer_is_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aisubtranslator.media.ranking import rank

    from .test_ranking import track

    ranked = rank((track(0, frames=1200), track(1, frames=1180)))
    answers = iter([7, 42, 0])
    monkeypatch.setattr(cli.typer, "prompt", lambda *_, **__: next(answers))
    assert cli._ask_which_track(ranked).candidate.subtitle_index == 0


def test_help_lists_every_command() -> None:
    output = runner.invoke(cli.app, ["--help"]).output
    for command in ("translate", "tracks", "style", "bible", "sample"):
        assert command in output
