"""Read production telemetry from the Shift-left SDK SQLite database."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catchtest.core.diff_extractor import ChangedFile

logger = logging.getLogger(__name__)


@dataclass
class IncidentSummary:
    exception_type: str
    exception_message: str
    endpoint: str
    timestamp: str


@dataclass
class FunctionTelemetry:
    function_name: str
    file_path: str
    call_count: int
    callers: list[str]
    callees: list[str]
    endpoints: list[str]
    endpoint_traffic: dict[str, int]
    exceptions: dict[str, int]
    avg_duration_ms: float
    incidents: list[IncidentSummary]


@dataclass
class TelemetryContext:
    function_telemetry: dict[str, FunctionTelemetry] = field(default_factory=dict)
    has_data: bool = False


def _match_file_path(db_path: str, changed_path: str) -> bool:
    """Check if a DB file_path ends with the changed file's relative path."""
    return db_path.endswith(changed_path) or db_path.endswith("/" + changed_path)


def load_telemetry_for_diff(db_path: str, changed_files: list[ChangedFile]) -> TelemetryContext:
    """Load production telemetry for functions affected by the diff.

    Opens the SDK's SQLite DB read-only and queries for telemetry matching
    the changed functions in the diff.
    """
    ctx = TelemetryContext()

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        logger.warning("Could not open telemetry database: %s", e)
        return ctx

    try:
        _load_telemetry(conn, changed_files, ctx)
    except sqlite3.Error as e:
        logger.warning("Error reading telemetry database: %s", e)
    finally:
        conn.close()

    ctx.has_data = bool(ctx.function_telemetry)
    return ctx


def _load_telemetry(
    conn: sqlite3.Connection,
    changed_files: list[ChangedFile],
    ctx: TelemetryContext,
) -> None:
    """Core loading logic — matches changed functions to DB records."""
    cursor = conn.cursor()

    # Build a mapping of function_name -> ChangedFile for lookup
    func_to_file: dict[str, str] = {}
    for cf in changed_files:
        for func_name in cf.changed_functions:
            func_to_file[func_name] = cf.path

    if not func_to_file:
        return

    # Query function_mapping for all candidate function names
    placeholders = ",".join("?" for _ in func_to_file)
    cursor.execute(
        f"SELECT function_id, name, file_path FROM function_mapping WHERE name IN ({placeholders})",
        list(func_to_file.keys()),
    )
    rows = cursor.fetchall()

    # Filter by file path suffix match
    matched: dict[str, list[str]] = {}  # function_name -> [function_id, ...]
    func_id_to_name: dict[str, str] = {}
    for row in rows:
        func_name = row["name"]
        changed_path = func_to_file.get(func_name)
        if changed_path and _match_file_path(row["file_path"], changed_path):
            matched.setdefault(func_name, []).append(row["function_id"])
            func_id_to_name[row["function_id"]] = func_name

    if not matched:
        return

    # Build name lookup for all function_ids (for resolving callers)
    all_func_ids = set()
    for ids in matched.values():
        all_func_ids.update(ids)

    # Query function_calls for matched function_ids
    for func_name, func_ids in matched.items():
        placeholders = ",".join("?" for _ in func_ids)
        cursor.execute(
            f"""SELECT function_id, endpoint_id, caller, exceptions,
                       duration_count, duration_sum, duration_max, duration_min
                FROM function_calls WHERE function_id IN ({placeholders})""",
            func_ids,
        )
        call_rows = cursor.fetchall()

        total_count = 0
        total_duration = 0.0
        callers_set: set[str] = set()
        endpoints_set: set[str] = set()
        exceptions_agg: dict[str, int] = {}

        for cr in call_rows:
            count = cr["duration_count"] or 0
            total_count += count
            total_duration += cr["duration_sum"] or 0

            if cr["caller"]:
                callers_set.add(cr["caller"])

            if cr["endpoint_id"]:
                endpoints_set.add(cr["endpoint_id"])

            if cr["exceptions"]:
                try:
                    exc_data = json.loads(cr["exceptions"])
                    if isinstance(exc_data, dict):
                        for exc_type, exc_count in exc_data.items():
                            exceptions_agg[exc_type] = exceptions_agg.get(exc_type, 0) + int(exc_count)
                    elif isinstance(exc_data, list):
                        for exc_type in exc_data:
                            exceptions_agg[str(exc_type)] = exceptions_agg.get(str(exc_type), 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass

        # Resolve caller function_ids to names
        caller_names = _resolve_function_names(cursor, list(callers_set))

        # Find callees (functions that list our func_ids as caller)
        callee_names = []
        if func_ids:
            cursor.execute(
                f"SELECT DISTINCT function_id FROM function_calls WHERE caller IN ({placeholders})",
                func_ids,
            )
            callee_ids = [r["function_id"] for r in cursor.fetchall()]
            callee_names = _resolve_function_names(cursor, callee_ids)

        # Query endpoint_metrics for traffic data
        endpoint_traffic: dict[str, int] = {}
        if endpoints_set:
            ep_placeholders = ",".join("?" for _ in endpoints_set)
            cursor.execute(
                f"SELECT endpoint_id, method, route, count FROM endpoint_metrics WHERE endpoint_id IN ({ep_placeholders})",
                list(endpoints_set),
            )
            for er in cursor.fetchall():
                ep_label = f"{er['method']} {er['route']}" if er["method"] and er["route"] else er["endpoint_id"]
                endpoint_traffic[ep_label] = endpoint_traffic.get(ep_label, 0) + (er["count"] or 0)

        # Query incident_snapshots where call_path contains any of our function_ids
        incidents: list[IncidentSummary] = []
        cursor.execute("SELECT * FROM incident_snapshots")
        for ir in cursor.fetchall():
            call_path = ir["call_path"] or ""
            if any(fid in call_path for fid in func_ids):
                incidents.append(IncidentSummary(
                    exception_type=ir["exception_type"] or "",
                    exception_message=(ir["exception_message"] or "")[:200],
                    endpoint=ir["affected_endpoint"] or "",
                    timestamp=ir["timestamp"] or "",
                ))

        avg_ms = (total_duration / total_count * 1000) if total_count > 0 else 0.0

        ctx.function_telemetry[func_name] = FunctionTelemetry(
            function_name=func_name,
            file_path=func_to_file[func_name],
            call_count=int(total_count),
            callers=caller_names,
            callees=callee_names,
            endpoints=list(endpoints_set),
            endpoint_traffic=endpoint_traffic,
            exceptions=exceptions_agg,
            avg_duration_ms=round(avg_ms, 2),
            incidents=incidents,
        )


def _resolve_function_names(cursor: sqlite3.Cursor, func_ids: list[str]) -> list[str]:
    """Resolve function_ids to human-readable names via function_mapping."""
    if not func_ids:
        return []
    placeholders = ",".join("?" for _ in func_ids)
    cursor.execute(
        f"SELECT function_id, name FROM function_mapping WHERE function_id IN ({placeholders})",
        func_ids,
    )
    return [row["name"] for row in cursor.fetchall()]
