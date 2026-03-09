"""LLM-as-judge assessor for weak catches."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from catchtest.prompts.judge import build_judge_prompt

if TYPE_CHECKING:
    from catchtest.core.diff_extractor import DiffContext
    from catchtest.core.weak_catch import WeakCatch
    from catchtest.llm import LLMClient

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
) -> tuple[float, dict]:
    """Use an LLM to classify whether a weak catch is a real bug.

    Returns (score, judge_response_dict).
    """
    system, messages = build_judge_prompt(
        diff_text=diff_context.diff_text[:5000],
        intent=intent,
        test_code=catch.test.test_code,
        failure_message=catch.result.failure_message or "",
        failure_traceback=catch.result.failure_traceback or "",
    )

    try:
        response = client.complete(system=system, messages=messages)
        # Strip markdown fences if present
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines[1:] if not l.strip().startswith("```")]
            text = "\n".join(lines)

        parsed = json.loads(text)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to parse LLM judge response: %s", e)
        return 0.0, {"classification": "UNKNOWN", "explanation": str(e)}

    classification = parsed.get("classification", "MEDIUM").upper()
    is_unexpected = parsed.get("is_unexpected", False)

    score = _SCORE_MAP.get((classification, is_unexpected), 0.0)

    return score, parsed
