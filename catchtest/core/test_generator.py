"""LLM-based test generation — the core brain of CatchTest."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from catchtest.core.weak_catch import GeneratedTest
from catchtest.llm import TokenUsage
from catchtest.prompts.generate import build_dodgy_diff_prompt, build_intent_aware_prompt
from catchtest.prompts.intent import build_intent_prompt

if TYPE_CHECKING:
    from catchtest.config import CatchTestConfig
    from catchtest.core.diff_extractor import ChangedFile, DiffContext
    from catchtest.llm import LLMClient
    from catchtest.telemetry.reader import TelemetryContext

logger = logging.getLogger(__name__)


def _parse_json_response(text: str) -> dict:
    """Parse a JSON response from the LLM, handling common formatting issues."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: extract JSON object when LLM returns narrative before/after JSON
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group())
        raise


def _syntax_check(code: str) -> bool:
    """Check if Python code is syntactically valid."""
    try:
        compile(code, "<test>", "exec")
        return True
    except SyntaxError:
        return False


def _extract_focused_context(
    full_content: str,
    diff_hunks: list[str],
    max_chars: int = 5000,
    context_lines: int = 50,
) -> str:
    """Extract content around changed regions rather than truncating from file start."""
    if not full_content or not diff_hunks:
        return full_content[:max_chars]

    lines = full_content.splitlines()

    # Parse line ranges from @@ headers
    changed_ranges: list[tuple[int, int]] = []
    for hunk in diff_hunks:
        for match in re.finditer(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", hunk):
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) else 1
            changed_ranges.append((start, start + count - 1))

    if not changed_ranges:
        return full_content[:max_chars]

    # Expand each range with context and merge overlapping regions
    regions: list[tuple[int, int]] = []
    for start, end in sorted(changed_ranges):
        region_start = max(1, start - context_lines)
        region_end = min(len(lines), end + context_lines)
        if regions and region_start <= regions[-1][1] + 1:
            regions[-1] = (regions[-1][0], max(regions[-1][1], region_end))
        else:
            regions.append((region_start, region_end))

    # Build output with "..." markers between non-contiguous regions
    parts: list[str] = []
    for i, (start, end) in enumerate(regions):
        if i > 0:
            parts.append("...")
        # Line numbers are 1-indexed, list is 0-indexed
        parts.append("\n".join(lines[start - 1 : end]))

    result = "\n".join(parts)
    if len(result) > max_chars:
        result = result[:max_chars]
    return result


def infer_intent(
    client: LLMClient,
    diff_context: DiffContext,
    changed_file: ChangedFile,
    telemetry_ctx: TelemetryContext | None = None,
) -> tuple[str, list[str], TokenUsage]:
    """Infer the intent and risks of a diff using an LLM.

    Returns (intent_text, list_of_risks, token_usage).
    """
    files_summary = "\n".join(
        f"- {f.path} ({f.language}): functions changed: {', '.join(f.changed_functions) or 'N/A'}"
        for f in diff_context.changed_files
    )

    focused = _extract_focused_context(changed_file.parent_content, changed_file.diff_hunks, max_chars=3000)
    file_context = f"File: {changed_file.path}\n```\n{focused}\n```"

    telemetry_section = ""
    if telemetry_ctx and telemetry_ctx.has_data:
        from catchtest.telemetry.formatter import format_for_risk_analysis
        telemetry_section = format_for_risk_analysis(telemetry_ctx)

    system, messages = build_intent_prompt(
        commit_message=diff_context.commit_message,
        diff_text=diff_context.diff_text[:5000],  # Truncate very large diffs
        changed_files_summary=files_summary,
        file_context=file_context,
        telemetry_section=telemetry_section,
    )

    try:
        response, usage = client.complete(system=system, messages=messages)
        parsed = _parse_json_response(response)
        intent = parsed.get("intent", "Unknown intent")
        risks = parsed.get("risks", [])
        return intent, risks, usage
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse intent response: %s", e)
        return "Could not infer intent", ["General regression risk"], TokenUsage()


def generate_intent_aware(
    client: LLMClient,
    changed_file: ChangedFile,
    diff_context: DiffContext,
    config: CatchTestConfig,
    telemetry_ctx: TelemetryContext | None = None,
) -> tuple[list[GeneratedTest], list[tuple[str, TokenUsage]]]:
    """Intent-aware test generation workflow (2 LLM calls).

    Returns (generated_tests, list of (call_label, usage) pairs).
    """
    all_usage: list[tuple[str, TokenUsage]] = []

    # Step 1: Infer intent and risks
    intent, risks, intent_usage = infer_intent(client, diff_context, changed_file, telemetry_ctx)
    all_usage.append(("intent", intent_usage))

    if not risks:
        logger.info("No risks identified for %s, skipping", changed_file.path)
        return [], all_usage

    # Step 2: Generate tests targeting each risk
    hunk_text = "\n".join(changed_file.diff_hunks)
    production_context = ""
    if telemetry_ctx and telemetry_ctx.has_data:
        from catchtest.telemetry.formatter import format_for_test_generation
        production_context = format_for_test_generation(telemetry_ctx, changed_file)

    system, messages = build_intent_aware_prompt(
        file_path=changed_file.path,
        language=changed_file.language,
        parent_content=_extract_focused_context(changed_file.parent_content, changed_file.diff_hunks, max_chars=5000),
        diff_text=hunk_text[:3000],
        risks=risks[:config.test.max_tests_per_diff],
        framework=config.test.framework,
        production_context=production_context,
    )

    try:
        response, gen_usage = client.complete(system=system, messages=messages)
        all_usage.append(("generate", gen_usage))
        parsed = _parse_json_response(response)
        raw_tests = parsed.get("tests", [])
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse test generation response: %s", e)
        return [], all_usage

    # Step 3: Validate and filter
    generated = []
    for test_data in raw_tests:
        code = test_data.get("test_code", "")
        risk = test_data.get("risk", "Unknown risk")

        if not code:
            continue

        if changed_file.language == "python" and not _syntax_check(code):
            logger.debug("Discarding syntactically invalid test for risk: %s", risk)
            continue

        generated.append(GeneratedTest(
            test_code=code,
            target_risk=risk,
            target_file=changed_file.path,
            workflow="intent",
        ))

    return generated[:config.test.max_tests_per_diff], all_usage


def generate_dodgy_diff(
    client: LLMClient,
    changed_file: ChangedFile,
    diff_context: DiffContext,
    config: CatchTestConfig,
    telemetry_ctx: TelemetryContext | None = None,
) -> tuple[list[GeneratedTest], list[tuple[str, TokenUsage]]]:
    """Dodgy diff test generation workflow (1 LLM call).

    Returns (generated_tests, list of (call_label, usage) pairs).
    """
    hunk_text = "\n".join(changed_file.diff_hunks)

    production_context = ""
    if telemetry_ctx and telemetry_ctx.has_data:
        from catchtest.telemetry.formatter import format_for_test_generation
        production_context = format_for_test_generation(telemetry_ctx, changed_file)

    system, messages = build_dodgy_diff_prompt(
        file_path=changed_file.path,
        language=changed_file.language,
        parent_content=_extract_focused_context(changed_file.parent_content, changed_file.diff_hunks, max_chars=5000),
        child_content=_extract_focused_context(changed_file.child_content, changed_file.diff_hunks, max_chars=5000),
        diff_text=hunk_text[:3000],
        framework=config.test.framework,
        production_context=production_context,
    )

    all_usage: list[tuple[str, TokenUsage]] = []
    try:
        response, gen_usage = client.complete(system=system, messages=messages)
        all_usage.append(("generate", gen_usage))
        parsed = _parse_json_response(response)
        raw_tests = parsed.get("tests", [])
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse dodgy diff response: %s", e)
        return [], all_usage

    generated = []
    for test_data in raw_tests:
        code = test_data.get("test_code", "")
        risk = test_data.get("risk", "Behavioral difference detected")

        if not code:
            continue

        if changed_file.language == "python" and not _syntax_check(code):
            continue

        generated.append(GeneratedTest(
            test_code=code,
            target_risk=risk,
            target_file=changed_file.path,
            workflow="dodgy",
        ))

    return generated[:config.test.max_tests_per_diff], all_usage
