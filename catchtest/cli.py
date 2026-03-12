"""Click-based CLI entry point for CatchTest."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from catchtest.config import DEFAULT_CONFIG_YAML, CatchTestConfig, load_config


@click.group()
@click.version_option(package_name="catchtest")
def cli():
    """CatchTest: Just-in-time catching test generation."""
    pass


@cli.command()
@click.option("--base", default=None, help="Base revision (default: remote tracking branch)")
@click.option("--target", default="HEAD", help="Target revision (child)")
@click.option("--file", "file_filter", default=None, help="Only test changes in this file")
@click.option(
    "--workflow",
    type=click.Choice(["intent", "dodgy", "both"]),
    default="intent",
    help="Test generation workflow",
)
@click.option("--provider", default=None, help="LLM provider override (anthropic|openai|ollama|bedrock)")
@click.option("--model", default=None, help="LLM model override")
@click.option("--aws-region", default=None, help="AWS region for Bedrock provider")
@click.option("--aws-profile", default=None, help="AWS profile for Bedrock provider")
@click.option("--telemetry-db", type=click.Path(exists=True), default=None,
              help="Path to Shift-left SDK telemetry SQLite database")
@click.option("--dry-run", is_flag=True, help="Generate tests but do not execute")
@click.option("--verbose", is_flag=True, help="Show detailed output")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["terminal", "json", "markdown"]),
    default=None,
    help="Output format",
)
def run(
    base: str | None,
    target: str,
    file_filter: str | None,
    workflow: str,
    provider: str | None,
    model: str | None,
    aws_region: str | None,
    aws_profile: str | None,
    telemetry_db: str | None,
    dry_run: bool,
    verbose: bool,
    output_format: str | None,
):
    """Generate catching tests for a code change."""
    # Set up logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    # Resolve --base default
    if base is None:
        from catchtest.utils.git import get_remote_head, GitError
        try:
            base = get_remote_head()
            click.echo(f"Using base: {base}")
        except GitError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    # Load config with CLI overrides
    config = load_config(cli_overrides={
        "provider": provider,
        "model": model,
        "aws_region": aws_region,
        "aws_profile": aws_profile,
        "verbose": verbose,
        "format": output_format,
    })
    config.telemetry_db = telemetry_db

    _run_pipeline(config, base, target, file_filter, workflow, dry_run)


def _run_pipeline(
    config: CatchTestConfig,
    base: str,
    target: str,
    file_filter: str | None,
    workflow: str,
    dry_run: bool,
) -> None:
    """Main pipeline orchestration."""
    from catchtest.assess.aggregator import aggregate
    from catchtest.assess.llm_judge import assess_llm_judge
    from catchtest.assess.rule_based import assess_rule_based
    from catchtest.core.diff_extractor import extract_diff
    from catchtest.core.test_generator import generate_dodgy_diff, generate_intent_aware, infer_intent
    from catchtest.core.test_runner import run_and_find_catches
    from catchtest.llm import TokenUsage, create_client
    from catchtest.output.reporter import report, report_dry_run
    from catchtest.utils.git import is_git_repo

    logger = logging.getLogger(__name__)

    # Verify we're in a git repo
    if not is_git_repo():
        click.echo("Error: Not inside a git repository.", err=True)
        sys.exit(1)

    # Create LLM client
    try:
        client = create_client(config.llm)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Step 1: Extract diff context
    click.echo(f"Extracting diff between {base} and {target}...")
    try:
        diff_context = extract_diff(base, target, file_filter)
    except Exception as e:
        click.echo(f"Error extracting diff: {e}", err=True)
        sys.exit(1)

    if not diff_context.changed_files:
        click.echo("No changes detected.")
        return

    click.echo(f"Found changes in {len(diff_context.changed_files)} file(s)")

    # Measure total chars of changed source files (for static analysis estimate)
    codebase_chars = sum(len(cf.child_content or "") + len(cf.parent_content or "")
                        for cf in diff_context.changed_files) // 2  # average of parent/child

    # Load telemetry if configured
    telemetry_ctx = None
    telemetry_chars = 0
    if config.telemetry_db:
        from catchtest.telemetry.reader import load_telemetry_for_diff
        telemetry_ctx = load_telemetry_for_diff(config.telemetry_db, diff_context.changed_files)
        if telemetry_ctx and telemetry_ctx.has_data:
            from catchtest.telemetry.formatter import format_for_risk_analysis
            telemetry_chars = len(format_for_risk_analysis(telemetry_ctx))
            logger.info("Loaded production telemetry for %d function(s)", len(telemetry_ctx.function_telemetry))

    # Step 2: Generate tests
    click.echo("Generating tests...")
    generated_tests = []
    all_usage: list[tuple[str, TokenUsage]] = []
    for changed_file in diff_context.changed_files:
        try:
            if workflow in ("intent", "both"):
                tests, usage_list = generate_intent_aware(client, changed_file, diff_context, config, telemetry_ctx)
                generated_tests += tests
                all_usage.extend(usage_list)
            if workflow in ("dodgy", "both"):
                tests, usage_list = generate_dodgy_diff(client, changed_file, diff_context, config, telemetry_ctx)
                generated_tests += tests
                all_usage.extend(usage_list)
        except Exception as e:
            logger.warning("Failed to generate tests for %s: %s", changed_file.path, e)

    click.echo(f"Generated {len(generated_tests)} test(s)")

    if dry_run:
        report_dry_run(generated_tests)
        return

    if not generated_tests:
        click.echo("No tests were generated. Nothing to run.")
        return

    # Step 3: Run tests against both revisions
    click.echo("Running tests against parent and child revisions...")
    try:
        weak_catches = run_and_find_catches(generated_tests, diff_context, config)
    except Exception as e:
        click.echo(f"Error running tests: {e}", err=True)
        sys.exit(1)

    if not weak_catches:
        click.echo("No weak catches found. Code change looks clean.")
        return

    click.echo(f"Found {len(weak_catches)} weak catch(es). Assessing...")

    # Step 4: Assess each weak catch
    assessed = []
    for catch in weak_catches:
        rule_score, rule_pattern = assess_rule_based(catch, diff_context)

        judge_data = {}
        llm_score = 0.0
        if config.assessment.enable_llm_judge:
            try:
                llm_score, judge_data, judge_usage = assess_llm_judge(
                    client, catch, diff_context,
                    telemetry_ctx=telemetry_ctx,
                )
                all_usage.append(("judge", judge_usage))
            except Exception as e:
                logger.warning("LLM judge failed: %s", e)

        if config.assessment.enable_rule_based and not config.assessment.enable_llm_judge:
            final_score = rule_score
            verdict = _score_to_verdict(final_score)
        elif config.assessment.enable_llm_judge and not config.assessment.enable_rule_based:
            final_score = llm_score
            verdict = _score_to_verdict(final_score)
        else:
            final_score, verdict = aggregate(rule_score, llm_score)

        if rule_pattern:
            judge_data.setdefault("explanation", "")
            judge_data["explanation"] += f" [rule: {rule_pattern}]"

        assessed.append((catch, final_score, verdict, judge_data))

    # Step 5: Report results
    verbose = config.output.verbosity == "verbose"
    report(assessed, output_format=config.output.format, verbose=verbose)

    # Step 6: Print token usage summary
    _print_token_summary(all_usage, assessed, len(weak_catches), telemetry_chars, codebase_chars)


def _print_token_summary(
    all_usage: list[tuple[str, object]],
    assessed: list[tuple],
    weak_catch_count: int = 0,
    telemetry_chars: int = 0,
    codebase_chars: int = 0,
) -> None:
    """Print a token usage summary table after the results report."""
    from collections import defaultdict

    # Aggregate by call label
    counts: dict[str, int] = defaultdict(int)
    input_totals: dict[str, int] = defaultdict(int)
    output_totals: dict[str, int] = defaultdict(int)

    for label, usage in all_usage:
        counts[label] += 1
        input_totals[label] += usage.input_tokens
        output_totals[label] += usage.output_tokens

    if not counts:
        return

    click.echo("")
    click.echo("Token Usage:")

    total_in = 0
    total_out = 0
    total_calls = 0
    for label in ("intent", "generate", "judge"):
        if label not in counts:
            continue
        inp = input_totals[label]
        out = output_totals[label]
        n = counts[label]
        total_in += inp
        total_out += out
        total_calls += n
        click.echo(f"  {label + ':':<11} {inp:>7,} in / {out:>6,} out   ({n} call{'s' if n != 1 else ''})")

    click.echo("  " + "\u2500" * 37)
    click.echo(f"  {'Total:':<11} {total_in:>7,} in / {total_out:>6,} out   ({total_calls} call{'s' if total_calls != 1 else ''})")

    # Efficiency metrics
    likely_bugs = sum(1 for _, _, verdict, _ in assessed if verdict == "LIKELY_BUG")

    click.echo("")
    click.echo("Efficiency:")
    click.echo(f"  Catches:      {likely_bugs} likely bug(s) / {weak_catch_count} weak catches")
    if weak_catch_count > 0:
        precision = likely_bugs / weak_catch_count * 100
        click.echo(f"  Precision:    {precision:.1f}%   (likely bugs / weak catches)")
    if total_calls > 0:
        catch_yield = likely_bugs / total_calls * 100
        click.echo(f"  Catch yield:  {catch_yield:.1f}%   (likely bugs / LLM calls)")
    if likely_bugs > 0:
        click.echo(f"  Tokens/catch: {total_in // likely_bugs:,} input tokens per catch")

    # Context cost comparison (only when telemetry was used)
    if telemetry_chars > 0 and total_in > 0:
        telemetry_tokens = telemetry_chars // 4
        telemetry_pct = telemetry_tokens / total_in * 100
        static_chars = codebase_chars if codebase_chars > 0 else telemetry_chars * 4
        static_tokens = static_chars // 4
        static_pct = static_tokens / total_in * 100

        click.echo("")
        click.echo("Context cost (telemetry vs static analysis):")
        click.echo(f"  Telemetry added:     ~{telemetry_chars:,} chars (~{telemetry_tokens:,} tokens, {telemetry_pct:.1f}% of input)")
        click.echo(f"  Static analysis est: ~{static_chars:,} chars (~{static_tokens:,} tokens, {static_pct:.1f}% of input)")
        click.echo("    (full source of changed files — structural info only)")
        click.echo("  Runtime-only signals: traffic volume, exception rates, incidents, latency")
        click.echo("    (not available from static analysis at any cost)")


def _score_to_verdict(score: float) -> str:
    if score >= 0.5:
        return "LIKELY_BUG"
    elif score <= -0.5:
        return "LIKELY_FALSE_POSITIVE"
    else:
        return "UNCERTAIN"


@cli.command()
def init():
    """Create a default .catchtest.yaml config file."""
    config_path = Path.cwd() / ".catchtest.yaml"
    if config_path.exists():
        click.echo(f"{config_path} already exists. Remove it first to reinitialize.")
        return

    config_path.write_text(DEFAULT_CONFIG_YAML)
    click.echo(f"Created {config_path}")


if __name__ == "__main__":
    cli()
