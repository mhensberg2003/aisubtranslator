"""Command-line interface.

CLI-first by design: one command, path in, translated sidecar out. It drops to
an interactive picker only when it genuinely cannot decide - several plausible
subtitle tracks - so batching a whole season stays possible.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn

from . import console as ui
from . import inputs, languages
from .config import (
    Settings,
    global_style_path,
    work_dir_for,
    work_state_dir,
    work_style_path,
)
from .domain.bible import Bible, bible_path
from .domain.style import StylePreferences
from .errors import ConfigError, InputError, SubtranslatorError
from .media import probe, ranking
from .subtitles import classify, document, payload
from .translate import pipeline
from .translate.openrouter import OpenRouterProvider
from .translate.provider import Batch, Line
from .translate.repair import translate_with_repair

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Translate subtitles with an LLM. Drop in a subtitle file or a video.",
)


@app.command()
def translate(
    source: Annotated[Path, typer.Argument(help="Subtitle file or video file.")],
    to: Annotated[str, typer.Option("--to", "-t", help="Target language.")] = "da",
    source_language: Annotated[
        str, typer.Option("--from", "-f", help="Source language, or 'auto'.")
    ] = "auto",
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Where to write.")
    ] = None,
    track: Annotated[
        int | None, typer.Option("--track", help="Subtitle track index in a video.")
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="OpenRouter model id.")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace an existing file.")] = False,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
    refresh_bible: Annotated[
        bool, typer.Option("--refresh-bible", help="Rebuild the Work's reference sheet.")
    ] = False,
    pin_routing: Annotated[
        bool,
        typer.Option(
            "--pin-routing/--no-pin-routing",
            help="Pin to one upstream for consistent schemas and caching.",
        ),
    ] = True,
    assume_yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Never prompt; take the best guess.")
    ] = False,
) -> None:
    """Translate a subtitle file, or the subtitles inside a video."""
    try:
        asyncio.run(
            _translate(
                source=source,
                target=to,
                source_language=source_language,
                output=output,
                track=track,
                model=model,
                overwrite=overwrite,
                resume=resume,
                refresh_bible=refresh_bible,
                pin_routing=pin_routing,
                assume_yes=assume_yes,
            )
        )
    except SubtranslatorError as error:
        ui.show_error(error)
        raise typer.Exit(1) from error
    except KeyboardInterrupt:
        ui.errors.print("\n[yellow]Stopped. Rerun to resume where it left off.[/]")
        raise typer.Exit(130) from None


@app.command()
def tracks(source: Annotated[Path, typer.Argument(help="Video file to inspect.")]) -> None:
    """List the subtitle tracks in a video, with the ranking that would be used."""
    try:
        candidates = probe.probe(source)
    except SubtranslatorError as error:
        ui.show_error(error)
        raise typer.Exit(1) from error

    ranked = ranking.rank(candidates)
    if not ranked:
        ui.errors.print(f"[yellow]No text subtitle tracks in {source.name}.[/]")
        for candidate in candidates:
            ui.console.print(f"  [dim]{candidate.describe()} (not text)[/]")
        raise typer.Exit(1)

    ui.console.print(ui.track_table(ranked, title=f"Subtitle tracks in {source.name}"))
    verdict = "would be chosen automatically" if ranking.is_decisive(ranked) else "is a close call"
    ui.console.print(f"[dim]Track {ranked[0].candidate.subtitle_index} {verdict}.[/]")


@app.command()
def style(
    init: Annotated[bool, typer.Option("--init", help="Write the defaults out to edit.")] = False,
) -> None:
    """Show, or create, your target-language Style Preferences."""
    path = global_style_path()
    if init:
        if path.exists():
            ui.console.print(f"[yellow]Already exists:[/] {path}")
        else:
            StylePreferences().save(path)
            ui.console.print(f"[green]Wrote defaults to[/] {path}")
    if not path.exists():
        ui.console.print(f"[dim]No preferences file yet. Run `style --init` to create {path}.[/]")
    ui.console.print(StylePreferences.load(path).to_prompt())


@app.command()
def sample(
    source: Annotated[Path, typer.Argument(help="Subtitle file or video file.")],
    to: Annotated[str, typer.Option("--to", "-t", help="Target language.")] = "da",
    lines: Annotated[int, typer.Option("--lines", "-n", help="How many cues.")] = 20,
    model: Annotated[str | None, typer.Option("--model")] = None,
) -> None:
    """Translate a few cues and print them side by side, to judge the quality.

    This is the deliberate exception to everything else being offline and free:
    it makes a real request so you can read actual output before committing to
    a whole file. Nothing is written to disk.
    """
    try:
        asyncio.run(_sample(source=source, target=to, count=lines, model=model))
    except SubtranslatorError as error:
        ui.show_error(error)
        raise typer.Exit(1) from error


@app.command()
def bible(
    source: Annotated[Path, typer.Argument(help="Any file in the Work.")],
) -> None:
    """Show the reference sheet for the Work containing a file."""
    work_dir = work_dir_for(source)
    path = bible_path(work_dir)
    loaded = Bible.load(work_dir)
    if loaded.is_empty():
        ui.console.print(f"[dim]No reference sheet yet for {work_dir}.[/]")
        raise typer.Exit(0)
    ui.console.print(f"[dim]{path}[/]\n")
    ui.console.print(loaded.to_prompt())


# --------------------------------------------------------------------------


async def _translate(
    *,
    source: Path,
    target: str,
    source_language: str,
    output: Path | None,
    track: int | None,
    model: str | None,
    overwrite: bool,
    resume: bool,
    refresh_bible: bool,
    pin_routing: bool,
    assume_yes: bool,
) -> None:
    settings = _settings(model)
    work_dir = work_dir_for(source)
    resolved = inputs.resolve(
        source,
        work_dir=work_dir,
        track_index=track,
        preferred_languages=_preferred(source_language),
        choose=None if assume_yes or not sys.stdin.isatty() else _ask_which_track,
    )
    _announce_extraction(resolved)

    doc = document.load(resolved.subtitle_path)
    plan = pipeline.Plan(
        document=doc,
        style=_load_style(work_dir),
        source_language=languages.to_name(_detected(source_language, resolved)),
        target_language=languages.to_name(target),
        settings=settings,
        work_dir=work_dir,
        output=output
        or document.sidecar_path(
            resolved.origin, languages.to_code(target), doc.output_extension
        ),
        refresh_bible=refresh_bible,
        resume=resume,
        origin=resolved.origin,
    )

    result = await _execute(plan, pin_routing=pin_routing)
    _write_outputs(plan, result, overwrite=overwrite)


async def _execute(plan: pipeline.Plan, *, pin_routing: bool) -> pipeline.Result:
    """Run the Job with a live provider and a progress bar."""
    settings = plan.settings
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        provider = OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            model=settings.aisubtranslator_model,
            client=client,
            base_url=settings.openrouter_base_url,
            pin_routing=pin_routing,
        )
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"Translating into {plan.target_language}", total=None
            )

            def advance(done: int, total: int) -> None:
                progress.update(task, completed=done, total=total)

            return await pipeline.run(plan, provider, on_progress=advance)


def _write_outputs(
    plan: pipeline.Plan, result: pipeline.Result, *, overwrite: bool
) -> None:
    """Write the subtitle file, and a report only if there is anything to say."""
    rendered = document.render(plan.document, result.translations)
    document.write(
        rendered,
        plan.output,
        format_=plan.document.output_format,
        overwrite=overwrite,
    )

    report_path = None
    if not result.report.is_clean:
        report_path = plan.output.with_suffix(plan.output.suffix + ".report.md")
        report_path.write_text(result.report.to_markdown(), encoding="utf-8")

    ui.show_summary(result.report, report_path=report_path)


def _settings(model: str | None) -> Settings:
    settings = Settings()
    if model:
        settings = settings.model_copy(update={"aisubtranslator_model": model})
    if not settings.openrouter_api_key:
        raise ConfigError(
            "No OpenRouter API key found.",
            hint="Set OPENROUTER_API_KEY in your environment. "
            "Get one at https://openrouter.ai/keys.",
        )
    return settings


def _announce_extraction(resolved: inputs.ResolvedInput) -> None:
    if not (resolved.was_extracted and resolved.candidate):
        return
    ui.console.print(f"[dim]Extracted track: {resolved.candidate.describe()}[/]")
    if resolved.ambiguous:
        ui.console.print(
            "[yellow]Several tracks scored similarly; picked the best. "
            "Use --track to choose another.[/]"
        )


def _detected(requested: str, resolved: inputs.ResolvedInput) -> str:
    """Fall back to the container's language tag when none was given."""
    if requested in {"auto", ""} and resolved.language_hint:
        return resolved.language_hint
    return requested


async def _sample(*, source: Path, target: str, count: int, model: str | None) -> None:
    settings = _settings(model)
    work_dir = work_dir_for(source)
    resolved = inputs.resolve(source, work_dir=work_dir)
    doc = document.load(resolved.subtitle_path)
    style = _load_style(work_dir)

    translatable, _ = classify.partition(doc.track.cues)
    chosen = translatable[:count]
    if not chosen:
        raise InputError(f"{resolved.subtitle_path.name} has nothing to translate.")

    prepared = [payload.prepare(cue) for cue in chosen]
    batch = Batch(
        lines=tuple(Line(id=p.cue.id, text=p.source_text) for p in prepared),
        bible=Bible.load(work_dir),
        style=style,
        source_language=languages.to_name(resolved.language_hint or "auto"),
        target_language=languages.to_name(target),
    )

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        provider = OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            model=settings.aisubtranslator_model,
            client=client,
            base_url=settings.openrouter_base_url,
        )
        with ui.console.status("Translating a sample..."):
            outcome = await translate_with_repair(provider, batch, max_attempts=1)

    rows = [
        (
            item.cue.timecode,
            item.cue.plaintext,
            payload.finalise(item, translated, style).text
            if (translated := outcome.translated.get(item.cue.id))
            else "[red]failed[/]",
        )
        for item in prepared
    ]
    ui.console.print(ui.sample_table(rows, target=languages.to_name(target)))
    ui.console.print(ui.usage_line(outcome.usage))


def _load_style(work_dir: Path) -> StylePreferences:
    """Per-Work preferences win over global ones when present."""
    local = work_style_path(work_dir)
    return StylePreferences.load(local if local.is_file() else global_style_path())


def _preferred(source_language: str) -> tuple[str, ...]:
    if source_language in {"auto", ""}:
        return ()
    return (languages.to_code(source_language),)


def _ask_which_track(ranked: tuple[ranking.Ranked, ...]) -> ranking.Ranked:
    """Only reached when the ranking is genuinely close."""
    ui.console.print(ui.track_table(ranked, title="Several tracks look plausible"))
    valid = {entry.candidate.subtitle_index: entry for entry in ranked}
    choice = typer.prompt(
        "Which track?",
        default=ranked[0].candidate.subtitle_index,
        type=int,
    )
    while choice not in valid:
        choice = typer.prompt(f"Pick one of {sorted(valid)}", type=int)
    return valid[choice]


def main() -> None:
    app()


if __name__ == "__main__":
    main()
