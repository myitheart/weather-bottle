"""Read-only, bounded App Server diagnostics for Work Memory Phase 0."""

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys
from time import monotonic


# Keep the documented direct script invocation working from any directory.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from work_memory.codex_rpc import AppServer, ProbeError, RpcError, identifier, pages, path_key, same_path, timestamp, timing
from work_memory.time_range import make_window


SOURCES = ("cli", "vscode", "exec", "appServer", "unknown")


def page_report(scan):
    return {"pages": scan.pages, "rows": len(scan.rows), "duplicates": scan.duplicates,
            "rejected": scan.rejected, "coverage": scan.coverage}


def session(raw, cwd):
    if not identifier(raw.get("id")) or not same_path(raw.get("cwd"), cwd):
        return None
    source = raw.get("source")
    mode = raw.get("historyMode")
    return {"id": raw["id"], "source": source if source in SOURCES else "other",
            "mode": mode if mode in ("legacy", "paginated") else "unknown"}


def turn(raw):
    if not identifier(raw.get("id")):
        return None
    status = raw.get("status")
    return {"id": raw["id"], **timing(raw, "startedAt", "completedAt"),
            "status": status if status in ("completed", "failed", "interrupted", "inProgress") else "other"}


def item(raw, turn_id):
    data = raw.get("item")
    if raw.get("turnId") != turn_id or not isinstance(data, dict) or not isinstance(data.get("id"), str):
        return None
    kind = data.get("type")
    command = kind == "commandExecution"
    exit_code = data.get("exitCode")
    return {"id": data["id"], **timing(raw, "startedAtMs", "completedAtMs", 1000),
            "kind": kind if kind in ("commandExecution", "fileChange", "mcpToolCall", "contextCompaction") else "other",
            "exit_recorded": command and type(exit_code) is int,
            "exit_zero": command and type(exit_code) is int and exit_code == 0,
            "command_output_present": command and bool(data.get("aggregatedOutput"))}


def date_windows(as_of):
    ranges = (make_window(period, as_of) for period in ("today", "yesterday", "last-7-days"))
    return {window.period.replace("-", "_"): (window.start, window.cutoff) for window in ranges}


def time_report(rows, windows):
    starts = [row["start"] for row in rows if row["start"] is not None]
    ends = [row["end"] for row in rows if row["end"] is not None]

    def local_day(ms):
        return datetime.fromtimestamp(ms / 1000).date()

    both = [(row["start"], row["end"]) for row in rows if row["start"] is not None and row["end"] is not None]
    return {"start_recorded": len(starts), "end_recorded": len(ends),
            "no_time": sum(row["start"] is None and row["end"] is None for row in rows),
            "days_observed": len({local_day(ms) for ms in starts + ends}),
            "cross_midnight": sum(local_day(start) < local_day(end) for start, end in both),
            "end_before_start": sum(end < start for start, end in both),
            "window_events": {name: {"starts": sum(lo <= ms < hi for ms in starts),
                                     "ends": sum(lo <= ms < hi for ms in ends)}
                              for name, (lo, hi) in windows.items()}}


def check_history(server, thread_id, cwd, limits, windows):
    try:
        detail = server.call("thread/read", {"threadId": thread_id, "includeTurns": False}).get("thread")
    except RpcError as error:
        return {"read": str(error)}
    if not isinstance(detail, dict) or detail.get("id") != thread_id or session(detail, cwd) is None:
        return {"read": "scope_or_id_mismatch"}
    report = {"read": "ok", "created_at_recorded": timestamp(detail, "createdAt") is not None,
              "updated_at_recorded": timestamp(detail, "updatedAt") is not None,
              "project_id_recorded": bool(detail.get("projectId"))}
    turns = pages(server, "thread/turns/list", {"threadId": thread_id, "limit": limits.page_size,
                  "itemsView": "notLoaded", "sortDirection": "desc"}, limits.turn_pages, turn)
    report["turns"] = {**page_report(turns), **time_report(turns.rows, windows),
                       "statuses": Counter(row["status"] for row in turns.rows)}
    # Look at the newest and oldest sampled turns. Keep item contents ephemeral.
    item_samples = turns.rows[:1] + turns.rows[-1:] if len(turns.rows) > 1 else turns.rows
    if limits.item_pages:
        report["item_samples"] = []
        for row in item_samples:
            items = pages(server, "thread/items/list", {"threadId": thread_id, "turnId": row["id"],
                          "limit": limits.item_page_size, "sortDirection": "desc"}, limits.item_pages,
                          lambda raw: item(raw, row["id"]))
            report["item_samples"].append({**page_report(items), **time_report(items.rows, windows),
                "kinds": Counter(entry["kind"] for entry in items.rows),
                "exit_recorded": sum(entry["exit_recorded"] for entry in items.rows),
                "exit_zero": sum(entry["exit_zero"] for entry in items.rows),
                "command_output_present": sum(entry["command_output_present"] for entry in items.rows)})
    return report


def scan_scope(server, cwd, archived, expected, limits, windows, report):
    query = {"cwd": cwd, "archived": archived, "limit": limits.page_size, "sortKey": "updated_at",
             "sortDirection": "desc", "useStateDbOnly": True}
    report["baseline"] = {"expected": len(expected)}
    filters_to_compare = (
        ("default", {}),
        ("sources_only", {"sourceKinds": list(SOURCES)}),
        ("providers_only", {"modelProviders": []}),
        ("explicit", {"sourceKinds": list(SOURCES), "modelProviders": []}),
    )
    scans = {
        label: pages(server, "thread/list", {**query, **filters}, limits.list_pages, lambda raw: session(raw, cwd))
        for label, filters in filters_to_compare
    }
    for label, result in scans.items():
        report[label] = page_report(result)
        report["baseline"][f"found_{label}"] = sum(row["id"] in expected for row in result.rows)
    explicit = scans["explicit"]
    report["baseline"]["missing_explicit"] = len(expected) - report["baseline"]["found_explicit"]
    report["source_modes"] = {}
    for row in explicit.rows:
        key = f'{row["source"]}:{row["mode"]}'
        bucket = report["source_modes"].setdefault(key, {"listed": 0, "in_baseline": 0})
        bucket["listed"] += 1
        bucket["in_baseline"] += row["id"] in expected
    report["thread_samples"] = []
    # Include each source/mode once, then prefer desktop baseline samples for comparison.
    modes_seen = set()
    samples = []
    for row in explicit.rows:
        key = (row["source"], row["mode"])
        if key not in modes_seen:
            modes_seen.add(key)
            samples.append(row)
    ordered = sorted(explicit.rows, key=lambda row: row["id"] not in expected)
    samples.extend(row for row in ordered if row not in samples)
    for row in samples[:limits.thread_samples]:
        report["thread_samples"].append({"source": row["source"], "mode": row["mode"],
            "baseline_index": expected.get(row["id"]), **check_history(server, row["id"], cwd, limits, windows)})


def read_baseline(parser, argument, project_count):
    baseline = {}
    if argument is None:
        return baseline
    try:
        if argument == "-":
            data = sys.stdin.read(65537)
        else:
            with Path(argument).open(encoding="utf-8-sig") as file:
                data = file.read(65537)
        rows = json.loads(data.lstrip("\ufeff")) if len(data) <= 65536 else None
    except (OSError, ValueError, RecursionError):
        parser.error("could not read the baseline JSON")
    if not isinstance(rows, list):
        parser.error("baseline must be an array of {project, threadId, archived} objects")
    for index, row in enumerate(rows, start=1):
        if (not isinstance(row, dict) or type(row.get("project")) is not int
                or not 1 <= row["project"] <= project_count or not identifier(row.get("threadId"))
                or type(row.get("archived")) is not bool):
            parser.error("baseline contains an invalid project index, thread ID or archive flag")
        baseline.setdefault((row["project"], row["archived"]), {}).setdefault(row["threadId"], index)
    return baseline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", action="append", required=True,
                        help="Exact authorized absolute cwd. Repeat to probe other paths separately.")
    parser.add_argument("--baseline", help="Optional baseline JSON file, or - for stdin. IDs stay out of output.")
    parser.add_argument("--page-size", type=int, choices=range(1, 26), default=2, metavar="1..25")
    parser.add_argument("--list-pages", type=int, choices=range(1, 31), default=15, metavar="1..30")
    parser.add_argument("--thread-samples", type=int, choices=range(0, 21), default=8, metavar="0..20")
    parser.add_argument("--turn-pages", type=int, choices=range(1, 31), default=12, metavar="1..30")
    parser.add_argument("--item-pages", type=int, choices=range(0, 11), default=2, metavar="0..10")
    parser.add_argument("--item-page-size", type=int, choices=range(1, 26), default=4, metavar="1..25")
    parser.add_argument("--measure-python-memory", action="store_true", help="Trace peak allocations in the probe process.")
    args = parser.parse_args()
    if len(args.project) > 6 or any(not os.path.isabs(path) or len(path) > 1024 for path in args.project):
        parser.error("provide at most six absolute cwd paths of at most 1024 characters each")
    if len({path_key(path) for path in args.project}) != len(args.project):
        parser.error("duplicate project cwd")
    baseline = read_baseline(parser, args.baseline, len(args.project))
    exe = shutil.which("codex")
    if not exe:
        parser.exit(2, "codex executable not found\n")
    started = monotonic()
    if args.measure_python_memory:
        import tracemalloc
        tracemalloc.start()
    windows = date_windows(int(datetime.now().timestamp() * 1000))
    report = {"schema_version": 1, "projects": [], "error": None}
    server = None
    try:
        with AppServer(exe) as server:
            server.initialize()
            for index, cwd in enumerate(args.project, start=1):
                project = {"project": index, "scopes": []}
                report["projects"].append(project)
                for archived in (False, True):
                    scope = {"archived": archived}
                    project["scopes"].append(scope)
                    scan_scope(server, cwd, archived, baseline.get((index, archived), {}), args, windows, scope)
    except ProbeError as error:
        report["error"] = str(error)
    except OSError:
        report["error"] = "process_io_error"
    if server is not None:
        report["server_exit_code"] = server.process.returncode
        report["rpc_requests"] = server.serial
        report["bytes_received"] = server.bytes_read
    report["elapsed_seconds"] = round(monotonic() - started, 3)
    if args.measure_python_memory:
        report["python_peak_bytes"] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    print(json.dumps(report, indent=2))
    return int(report["error"] is not None or report.get("server_exit_code") != 0)


if __name__ == "__main__":
    sys.exit(main())
