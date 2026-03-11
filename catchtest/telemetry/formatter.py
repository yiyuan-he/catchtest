"""Format telemetry data into prompt-ready strings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catchtest.core.diff_extractor import ChangedFile
    from catchtest.telemetry.reader import TelemetryContext


def format_for_risk_analysis(ctx: TelemetryContext, max_chars: int = 2000) -> str:
    """Format telemetry for the risk/intent analysis prompt."""
    if not ctx.has_data:
        return ""

    sections: list[str] = ["## Production Telemetry"]
    total_len = len(sections[0])

    for ft in ctx.function_telemetry.values():
        lines = [f"\n### `{ft.function_name}` (in `{ft.file_path}`)"]
        lines.append(f"- Traffic: ~{ft.call_count:,} calls, avg {ft.avg_duration_ms:.1f}ms")

        if ft.callers:
            lines.append(f"- Top callers: {', '.join(ft.callers[:5])}")

        if ft.endpoint_traffic:
            ep_parts = [f"{ep} ({count:,} req)" for ep, count in sorted(ft.endpoint_traffic.items(), key=lambda x: -x[1])[:3]]
            lines.append(f"- Endpoints: {', '.join(ep_parts)}")

        if ft.exceptions:
            exc_parts = [f"{t} ({c})" for t, c in sorted(ft.exceptions.items(), key=lambda x: -x[1])[:3]]
            lines.append(f"- Exceptions: {', '.join(exc_parts)}")

        if ft.incidents:
            inc = ft.incidents[0]
            lines.append(f"- Recent incident: {inc.exception_type} on {inc.endpoint} ({len(ft.incidents)} total)")

        section = "\n".join(lines)
        if total_len + len(section) > max_chars:
            break
        sections.append(section)
        total_len += len(section)

    return "\n".join(sections) if len(sections) > 1 else ""


def format_for_test_generation(ctx: TelemetryContext, changed_file: ChangedFile, max_chars: int = 1500) -> str:
    """Format telemetry for the test generation prompt, scoped to one file."""
    if not ctx.has_data:
        return ""

    relevant = {
        name: ft for name, ft in ctx.function_telemetry.items()
        if ft.file_path == changed_file.path
    }
    if not relevant:
        return ""

    sections: list[str] = [
        "## Production Context",
        "Use this production context to generate tests with realistic calling patterns.",
    ]
    total_len = sum(len(s) for s in sections)

    for ft in relevant.values():
        lines = [f"\n### `{ft.function_name}`"]
        lines.append(f"- Traffic: ~{ft.call_count:,} calls, avg {ft.avg_duration_ms:.1f}ms")

        if ft.callers:
            lines.append(f"- Called by: {', '.join(ft.callers[:5])}")

        if ft.endpoint_traffic:
            ep_parts = [f"{ep} ({count:,} req)" for ep, count in sorted(ft.endpoint_traffic.items(), key=lambda x: -x[1])[:3]]
            lines.append(f"- Endpoints: {', '.join(ep_parts)}")

        if ft.exceptions:
            exc_parts = [f"{t} ({c})" for t, c in sorted(ft.exceptions.items(), key=lambda x: -x[1])[:3]]
            lines.append(f"- Known exceptions: {', '.join(exc_parts)}")

        section = "\n".join(lines)
        if total_len + len(section) > max_chars:
            break
        sections.append(section)
        total_len += len(section)

    return "\n".join(sections) if len(sections) > 2 else ""


def format_for_judge(ctx: TelemetryContext, function_name: str, max_chars: int = 400) -> str:
    """Format a short telemetry summary for the judge prompt."""
    if not ctx.has_data:
        return ""

    ft = ctx.function_telemetry.get(function_name)
    if not ft:
        return ""

    parts = [f"Production impact: `{ft.function_name}` handles ~{ft.call_count:,} calls"]
    if ft.endpoint_traffic:
        top_ep = max(ft.endpoint_traffic.items(), key=lambda x: x[1])
        parts.append(f"top endpoint: {top_ep[0]} ({top_ep[1]:,} req)")
    if ft.incidents:
        parts.append(f"{len(ft.incidents)} recent incident(s)")

    result = ", ".join(parts) + "."
    return result[:max_chars]
