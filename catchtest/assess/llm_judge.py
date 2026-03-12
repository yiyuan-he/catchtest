"""LLM-as-judge assessor for weak catches."""

from __future__ import annotations

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

# Score mapping from classification + is_unexpected
_SCORE_MAP = {
    ("HIGH", True): 1.0,
    ("HIGH", False): 0.0,
    ("MEDIUM", True): 0.5,
    ("MEDIUM", False): -0.5,
    ("LOW", True): 0.0,
    ("LOW", False): -1.0,
}


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

    usage = TokenUsage()
    try:
        response, usage = client.complete(system=system, messages=messages)
        # Strip markdown fences if present
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines[1:] if not l.strip().startswith("```")]
            text = "\n".join(lines)

        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: extract JSON object when LLM returns narrative before/after JSON
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                # Handle single-quoted JSON (common LLM mistake)
                try:
                    fixed = match.group().replace("'", '"')
                    # Fix True/False/None from Python-style to JSON-style
                    fixed = re.sub(r'\bTrue\b', 'true', fixed)
                    fixed = re.sub(r'\bFalse\b', 'false', fixed)
                    fixed = re.sub(r'\bNone\b', 'null', fixed)
                    parsed = json.loads(fixed)
                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse LLM judge response: %s", e)
                    return 0.0, {"classification": "UNKNOWN", "explanation": str(e)}, usage
        else:
            logger.warning("Failed to parse LLM judge response: no JSON found")
            return 0.0, {"classification": "UNKNOWN", "explanation": "No JSON found in response"}, usage
    except Exception as e:
        logger.warning("Failed to parse LLM judge response: %s", e)
        return 0.0, {"classification": "UNKNOWN", "explanation": str(e)}, usage

    classification = parsed.get("classification", "MEDIUM").upper()
    is_unexpected = parsed.get("is_unexpected", False)

    score = _SCORE_MAP.get((classification, is_unexpected), 0.0)

    return score, parsed, usage
