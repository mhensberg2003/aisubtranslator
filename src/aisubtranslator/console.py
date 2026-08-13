"""Terminal output.

Kept apart from the CLI wiring so that what the user reads is easy to find and
easy to change, and so the command functions stay about control flow.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from .domain.report import Degradation, RunReport, Usage
from .errors import SubtranslatorError
from .media.ranking import Ranked

console = Console()
errors = Console(stderr=True)


def usage_line(usage: Usage) -> str:
    """Requests, tokens and cost, on one dim line."""
    cost = f" · ${usage.cost_usd:.4f}" if usage.cost_usd else ""
    return (
        f"[dim]{usage.requests} request(s) · "
        f"{usage.prompt_tokens:,} in / {usage.completion_tokens:,} out{cost}[/]"
    )


def track_table(ranked: tuple[Ranked, ...], *, title: str) -> Table:
    table = Table(title=title, title_justify="left", header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Track")
    table.add_column("Why", style="dim")
    for entry in ranked:
        table.add_row(
            str(entry.candidate.subtitle_index),
            entry.candidate.describe(),
            "; ".join(entry.reasons) or "nothing notable",
        )
    return table


def sample_table(rows: list[tuple[str, str, str]], *, target: str) -> Table:
    """Source and translation side by side, for judging quality by eye."""
    table = Table(header_style="bold", show_lines=True)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Source")
    table.add_column(target)
    for timecode, source, translated in rows:
        table.add_row(timecode, source.replace("\n", " "), translated.replace("\n", " "))
    return table


def show_error(error: SubtranslatorError) -> None:
    errors.print(f"[bold red]Error:[/] {error.message}")
    if error.hint:
        errors.print(f"[dim]{error.hint}[/]")


def show_summary(report: RunReport, *, report_path: Path | None) -> None:
    """One screen: what was produced, and what to look at if anything."""
    console.print()
    console.print(f"[bold green]Wrote[/] {report.output}")
    console.print(
        f"[dim]{report.translated_cues} of {report.total_cues} cues translated[/]"
    )
    console.print(usage_line(report.usage))

    if report.cues_over_budget:
        regressions = len(report.of_kind(Degradation.HARDER_THAN_SOURCE))
        console.print(
            f"[dim]{report.cues_over_budget} cues over "
            f"{report.reading_budget:.0f} chars/sec, "
            f"{regressions} of them worse than the source[/]"
        )

    if report.is_clean:
        console.print("[green]Nothing to review.[/]")
        return

    counts = [
        (kind, len(report.of_kind(kind)))
        for kind in Degradation
        if report.of_kind(kind)
    ]
    for kind, count in counts:
        style = "yellow" if kind is not Degradation.REPAIR_EXHAUSTED else "red"
        console.print(f"[{style}]{count}[/] {kind.value.lower()}")

    if report_path:
        console.print(f"[dim]Details: {report_path}[/]")
