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
@click.option("--base", default="HEAD~1", help="Base revision (parent)")
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
    base: str,
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
    from catchtest.llm import create_client
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

    # Load telemetry if configured
    telemetry_ctx = None
    if config.telemetry_db:
        from catchtest.telemetry.reader import load_telemetry_for_diff
        telemetry_ctx = load_telemetry_for_diff(config.telemetry_db, diff_context.changed_files)
        if telemetry_ctx.has_data:
            logger.info("Loaded production telemetry for %d function(s)", len(telemetry_ctx.function_telemetry))

    # Step 2: Generate tests
    click.echo("Generating tests...")
    generated_tests = []
    for changed_file in diff_context.changed_files:
        try:
            if workflow in ("intent", "both"):
                generated_tests += generate_intent_aware(client, changed_file, diff_context, config, telemetry_ctx)
            if workflow in ("dodgy", "both"):
                generated_tests += generate_dodgy_diff(client, changed_file, diff_context, config, telemetry_ctx)
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
                llm_score, judge_data = assess_llm_judge(
                    client, catch, diff_context,
                    telemetry_ctx=telemetry_ctx,
                )
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
