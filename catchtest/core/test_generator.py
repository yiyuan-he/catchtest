"""LLM-based test generation — the core brain of CatchTest."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from catchtest.core.weak_catch import GeneratedTest
from catchtest.prompts.generate import build_dodgy_diff_prompt, build_intent_aware_prompt
from catchtest.prompts.intent import build_intent_prompt

if TYPE_CHECKING:
    from catchtest.config import CatchTestConfig
    from catchtest.core.diff_extractor import ChangedFile, DiffContext
    from catchtest.llm import LLMClient

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
    return json.loads(text)


def _syntax_check(code: str) -> bool:
    """Check if Python code is syntactically valid."""
    try:
        compile(code, "<test>", "exec")
        return True
    except SyntaxError:
        return False


def infer_intent(
    client: LLMClient,
    diff_context: DiffContext,
    changed_file: ChangedFile,
) -> tuple[str, list[str]]:
    """Infer the intent and risks of a diff using an LLM.

    Returns (intent_text, list_of_risks).
    """
    files_summary = "\n".join(
        f"- {f.path} ({f.language}): functions changed: {', '.join(f.changed_functions) or 'N/A'}"
        for f in diff_context.changed_files
    )

    file_context = f"File: {changed_file.path}\n```\n{changed_file.parent_content[:3000]}\n```"

    system, messages = build_intent_prompt(
        commit_message=diff_context.commit_message,
        diff_text=diff_context.diff_text[:5000],  # Truncate very large diffs
        changed_files_summary=files_summary,
        file_context=file_context,
    )

    try:
        response = client.complete(system=system, messages=messages)
        parsed = _parse_json_response(response)
        intent = parsed.get("intent", "Unknown intent")
        risks = parsed.get("risks", [])
        return intent, risks
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse intent response: %s", e)
        return "Could not infer intent", ["General regression risk"]


def generate_intent_aware(
    client: LLMClient,
    changed_file: ChangedFile,
    diff_context: DiffContext,
    config: CatchTestConfig,
) -> list[GeneratedTest]:
    """Intent-aware test generation workflow (3 LLM calls)."""
    # Step 1: Infer intent and risks
    intent, risks = infer_intent(client, diff_context, changed_file)

    if not risks:
        logger.info("No risks identified for %s, skipping", changed_file.path)
        return []

    # Step 2: Generate tests targeting each risk
    system, messages = build_intent_aware_prompt(
        file_path=changed_file.path,
        language=changed_file.language,
        parent_content=changed_file.parent_content[:5000],
        risks=risks[:config.test.max_tests_per_diff],
        framework=config.test.framework,
    )

    try:
        response = client.complete(system=system, messages=messages)
        parsed = _parse_json_response(response)
        raw_tests = parsed.get("tests", [])
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse test generation response: %s", e)
        return []

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

    return generated[:config.test.max_tests_per_diff]


def generate_dodgy_diff(
    client: LLMClient,
    changed_file: ChangedFile,
    diff_context: DiffContext,
    config: CatchTestConfig,
) -> list[GeneratedTest]:
    """Dodgy diff test generation workflow (1 LLM call)."""
    hunk_text = "\n".join(changed_file.diff_hunks)

    system, messages = build_dodgy_diff_prompt(
        file_path=changed_file.path,
        language=changed_file.language,
        parent_content=changed_file.parent_content[:5000],
        child_content=changed_file.child_content[:5000],
        diff_text=hunk_text[:3000],
        framework=config.test.framework,
    )

    try:
        response = client.complete(system=system, messages=messages)
        parsed = _parse_json_response(response)
        raw_tests = parsed.get("tests", [])
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse dodgy diff response: %s", e)
        return []

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

    return generated[:config.test.max_tests_per_diff]
