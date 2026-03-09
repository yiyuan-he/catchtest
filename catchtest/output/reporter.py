"""Terminal output formatting for CatchTest results."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from catchtest.core.weak_catch import GeneratedTest, WeakCatch

console = Console()

VERDICT_STYLE = {
    "LIKELY_BUG": ("bold red", "LIKELY BUG"),
    "UNCERTAIN": ("bold yellow", "UNCERTAIN"),
    "LIKELY_FALSE_POSITIVE": ("bold green", "LIKELY FALSE POSITIVE"),
    "DISCARD": ("dim", "DISCARDED"),
}


def report_terminal(
    assessed: list[tuple[WeakCatch, float, str, dict]],
    verbose: bool = False,
) -> None:
    """Print results to the terminal using rich formatting."""
    if not assessed:
        console.print("\n[green]No issues found. Code change looks clean.[/green]\n")
        return

    # Count by verdict
    counts = {"LIKELY_BUG": 0, "UNCERTAIN": 0, "LIKELY_FALSE_POSITIVE": 0, "DISCARD": 0}
    for _, _, verdict, _ in assessed:
        counts[verdict] = counts.get(verdict, 0) + 1

    total = len(assessed)
    console.print(f"\n[bold]CatchTest found {total} potential issue(s)[/bold]\n")
    console.print("=" * 60)

    for catch, score, verdict, judge_data in assessed:
        style, label = VERDICT_STYLE.get(verdict, ("", verdict))

        # Icon based on verdict
        if verdict == "LIKELY_BUG":
            icon = "[red]BUG[/red]"
        elif verdict == "UNCERTAIN":
            icon = "[yellow]???[/yellow]"
        elif verdict == "LIKELY_FALSE_POSITIVE":
            icon = "[green]OK[/green]"
        else:
            icon = "[dim]---[/dim]"

        behavior_summary = judge_data.get("behavior_change_summary", "No summary available")
        explanation = judge_data.get("explanation", "")

        console.print(f"\n{icon} [{style}]{label}[/{style}] (score: {score:.2f}) -- {catch.test.target_file}")
        console.print(f"   Risk: {catch.test.target_risk}")
        console.print(f"   {behavior_summary}")
        if explanation:
            console.print(f"   Reason: {explanation}")

        if verbose:
            console.print(f"\n   [dim]Test code:[/dim]")
            console.print(Panel(catch.test.test_code, title="Generated Test", border_style="dim"))
            if catch.result.failure_message:
                console.print(f"   [dim]Failure:[/dim] {catch.result.failure_message}")
            if catch.result.failure_traceback:
                console.print(Panel(catch.result.failure_traceback, title="Traceback", border_style="dim"))

    console.print("\n" + "=" * 60)
    parts = []
    if counts["LIKELY_BUG"]:
        parts.append(f"[red]{counts['LIKELY_BUG']} likely bug(s)[/red]")
    if counts["UNCERTAIN"]:
        parts.append(f"[yellow]{counts['UNCERTAIN']} uncertain[/yellow]")
    if counts["LIKELY_FALSE_POSITIVE"]:
        parts.append(f"[green]{counts['LIKELY_FALSE_POSITIVE']} false positive(s)[/green]")
    if counts["DISCARD"]:
        parts.append(f"[dim]{counts['DISCARD']} discarded[/dim]")
    console.print("Summary: " + ", ".join(parts))

    if not verbose:
        console.print("[dim]Run with --verbose to see test code and full failure traces.[/dim]\n")


def report_json(assessed: list[tuple[WeakCatch, float, str, dict]]) -> None:
    """Output results as JSON."""
    results = []
    for catch, score, verdict, judge_data in assessed:
        results.append({
            "file": catch.test.target_file,
            "risk": catch.test.target_risk,
            "workflow": catch.test.workflow,
            "score": score,
            "verdict": verdict,
            "behavior_change_summary": judge_data.get("behavior_change_summary", ""),
            "explanation": judge_data.get("explanation", ""),
            "classification": judge_data.get("classification", ""),
        })
    print(json.dumps({"results": results, "total": len(results)}, indent=2))


def report_markdown(assessed: list[tuple[WeakCatch, float, str, dict]]) -> None:
    """Output results as Markdown."""
    if not assessed:
        print("# CatchTest Results\n\nNo issues found. Code change looks clean.")
        return

    print("# CatchTest Results\n")
    print(f"Found **{len(assessed)}** potential issue(s).\n")

    for catch, score, verdict, judge_data in assessed:
        behavior = judge_data.get("behavior_change_summary", "No summary")
        explanation = judge_data.get("explanation", "")
        icon = {"LIKELY_BUG": "🔴", "UNCERTAIN": "🟡", "LIKELY_FALSE_POSITIVE": "🟢", "DISCARD": "⚪"}
        print(f"## {icon.get(verdict, '')} {verdict} (score: {score:.2f}) — {catch.test.target_file}")
        print(f"\n**Risk:** {catch.test.target_risk}")
        print(f"\n{behavior}")
        if explanation:
            print(f"\n> {explanation}")
        print()


def report_dry_run(tests: list[GeneratedTest]) -> None:
    """Report generated tests without executing them."""
    if not tests:
        console.print("\n[yellow]No tests were generated.[/yellow]\n")
        return

    console.print(f"\n[bold]Dry run: Generated {len(tests)} test(s)[/bold]\n")

    for i, test in enumerate(tests, 1):
        console.print(f"[bold]Test {i}[/bold] — {test.target_file} ({test.workflow} workflow)")
        console.print(f"  Risk: {test.target_risk}")
        console.print(Panel(test.test_code, title=f"Test {i}", border_style="blue"))
        console.print()


def report(
    assessed: list[tuple[WeakCatch, float, str, dict]],
    output_format: str = "terminal",
    verbose: bool = False,
) -> None:
    """Route to the correct reporter based on format."""
    if output_format == "json":
        report_json(assessed)
    elif output_format == "markdown":
        report_markdown(assessed)
    else:
        report_terminal(assessed, verbose=verbose)
