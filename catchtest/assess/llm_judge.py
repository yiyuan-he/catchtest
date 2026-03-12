"""LLM-as-judge assessor for weak catches."""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import TYPE_CHECKING

from catchtest.llm import TokenUsage
from catchtest.prompts.judge import build_judge_prompt

if TYPE_CHECKING:
    from catchtest.core.diff_extractor import DiffContext
    from catchtest.core.weak_catch import WeakCatch
    from catchtest.llm import LLMClient
    from catchtest.telemetry.reader import TelemetryContext

logger = logging.getLogger(__name__)

_MAX_JUDGE_ATTEMPTS = 2

# Score mapping from classification + is_unexpected
_SCORE_MAP = {
    ("HIGH", True): 1.0,
    ("HIGH", False): 0.0,
    ("MEDIUM", True): 0.5,
    ("MEDIUM", False): -0.5,
    ("LOW", True): 0.0,
    ("LOW", False): -1.0,
}


def _parse_judge_json(raw: str) -> dict:
    """Parse a judge response, tolerating common LLM formatting mistakes.

    Tries, in order:
      1. Direct ``json.loads`` on the full text (after stripping markdown fences).
      2. Extract the outermost ``{…}`` block and ``json.loads`` it.
      3. ``ast.literal_eval`` on the extracted block (handles single-quoted keys,
         Python booleans ``True``/``False``/``None``, and apostrophes inside values).

    Raises ``ValueError`` if none of the strategies succeed.
    """
    text = raw.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # 1. Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract outermost {…} and try json.loads
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("No JSON object found in response")

    fragment = match.group()
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        pass

    # 3. ast.literal_eval handles single quotes, True/False/None
    try:
        result = ast.literal_eval(fragment)
        if isinstance(result, dict):
            return result
    except (ValueError, SyntaxError):
        pass

    raise ValueError(f"All parse strategies failed on: {fragment[:200]}")


def assess_llm_judge(
    client: LLMClient,
    catch: WeakCatch,
    diff_context: DiffContext,
    intent: str = "",
    telemetry_ctx: TelemetryContext | None = None,
) -> tuple[float, dict, TokenUsage]:
    """Use an LLM to classify whether a weak catch is a real bug.

    Returns (score, judge_response_dict, token_usage).
    """
    production_impact = ""
    if telemetry_ctx and telemetry_ctx.has_data:
        from catchtest.telemetry.formatter import format_for_judge
        # Try to find a matching function name from the test's target file
        for func_name in telemetry_ctx.function_telemetry:
            production_impact = format_for_judge(telemetry_ctx, func_name)
            if production_impact:
                break

    system, messages = build_judge_prompt(
        diff_text=diff_context.diff_text[:5000],
        intent=intent,
        test_code=catch.test.test_code,
        failure_message=catch.result.failure_message or "",
        failure_traceback=catch.result.failure_traceback or "",
        production_impact=production_impact,
    )

    total_usage = TokenUsage()
    parsed = None
    last_error = ""

    for attempt in range(_MAX_JUDGE_ATTEMPTS):
        try:
            response, usage = client.complete(system=system, messages=messages)
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens

            parsed = _parse_judge_json(response)
            break
        except Exception as e:
            last_error = str(e)
            if attempt < _MAX_JUDGE_ATTEMPTS - 1:
                logger.debug("Judge parse failed (attempt %d), retrying: %s", attempt + 1, e)
            else:
                logger.warning("Failed to parse LLM judge response after %d attempts: %s", _MAX_JUDGE_ATTEMPTS, e)

    if parsed is None:
        return 0.0, {"classification": "UNKNOWN", "explanation": last_error}, total_usage

    classification = parsed.get("classification", "MEDIUM").upper()
    is_unexpected = parsed.get("is_unexpected", False)

    score = _SCORE_MAP.get((classification, is_unexpected), 0.0)

    return score, parsed, total_usage
