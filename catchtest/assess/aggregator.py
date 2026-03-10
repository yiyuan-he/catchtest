"""Combine rule-based and LLM judge scores into a final verdict."""

from __future__ import annotations


def aggregate(
    rule_score: float,
    llm_score: float,
) -> tuple[float, str]:
    """Aggregate rule-based and LLM judge scores.

    Returns (combined_score, verdict) where verdict is one of:
    DISCARD, LIKELY_BUG, LIKELY_FALSE_POSITIVE, UNCERTAIN.
    """
    # Rule-based gets veto power for strong false positive signals
    if rule_score <= -0.8:
        return (rule_score, "DISCARD")

    # Weighted average (rule-based is more reliable but narrower)
    combined = 0.4 * rule_score + 0.6 * llm_score

    if combined >= 0.5:
        return (combined, "LIKELY_BUG")
    elif combined <= -0.5:
        return (combined, "LIKELY_FALSE_POSITIVE")
    else:
        return (combined, "UNCERTAIN")
