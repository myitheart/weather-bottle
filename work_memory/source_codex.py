"""Collect the verified local Codex history surface inside exact authorized CWDs."""

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import shutil
import unicodedata

from .codex_rpc import AppServer, Cancelled, ProbeError, RpcError, identifier, pages, path_key, same_path, timing, timestamp
from .work_signals import assistant_signals, user_keys
from .outcome_signals import project_changes, test_result, user_intent


SOURCES = ("vscode", "exec")
STATUSES = ("completed", "failed", "interrupted", "inProgress")


@dataclass(frozen=True)
class Limits:
    list_pages: int = 12
    turn_pages: int = 25
    item_pages: int = 8


@dataclass
class ProjectHistory:
    path: str
    listings: dict = field(default_factory=dict)
    sessions: dict = field(default_factory=dict)
    turns: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    issues: Counter = field(default_factory=Counter)
    chats_examined: int = 0
    finished: bool = False


@dataclass
class History:
    projects: list
    namespace: str = ""
    error: str | None = None


def clean_label(value, *, limit=160):
    if not isinstance(value, str):
        return ""
    cleaned = "".join(char if unicodedata.category(char) not in {"Cc", "Cf", "Cs"} else " " for char in value[:1024])
    return " ".join(cleaned.split())[:limit]


def source_namespace(home=None):
    if not isinstance(home, str) or not os.path.isabs(home):
        home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    normalized = path_key(os.path.realpath(os.path.abspath(home)))
    return "codex:" + hashlib.sha256(os.fsencode(normalized)).hexdigest()


def decode_session(raw, cwd):
    if (not identifier(raw.get("id")) or not same_path(raw.get("cwd"), cwd)
            or raw.get("source") not in SOURCES or raw.get("ephemeral") is True):
        return None
    return {"id": raw["id"], "title": clean_label(raw.get("name")), "source": raw["source"],
            "created": timestamp(raw, "createdAt"), "updated": timestamp(raw, "updatedAt")}


def normalize_times(raw, start, end, scale=1):
    values = timing(raw, start, end, scale)
    if values["start"] is not None and values["end"] is not None and values["end"] < values["start"]:
        return {"start": None, "end": None, "time_issue": "invalid_time_order"}
    return values


def decode_turn(raw):
    if not identifier(raw.get("id")):
        return None
    status = raw.get("status")
    return {"id": raw["id"], "status": status if status in STATUSES else "unknown",
            **normalize_times(raw, "startedAt", "completedAt")}


def decode_item(raw, turn_id, *, include_work=False, outcome_cwd=None):
    item = raw.get("item")
    if raw.get("turnId") != turn_id or not isinstance(item, dict) or not isinstance(item.get("type"), str):
        return None
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id or len(item_id) > 256:
        return None
    kind = item["type"]
    row = {"id": item_id, "command": kind == "commandExecution"}
    if row["command"]:
        exit_code = item.get("exitCode")
        row["exit_code"] = exit_code if type(exit_code) is int and -2**31 <= exit_code < 2**32 else None
        if outcome_cwd and (result := test_result(item, outcome_cwd)):
            row["test_result"] = result
    elif include_work and kind == "userMessage":
        row["keys"] = user_keys(item.get("content"))
        if outcome_cwd and (intent := user_intent(item.get("content"))):
            row["intent"] = intent
    elif include_work and kind == "agentMessage" and item.get("phase") in (None, "final_answer", "finalAnswer"):
        row["claims"], row["hints"] = assistant_signals(item.get("text"))
    elif include_work and kind == "fileChange" and item.get("status") == "completed":
        changes = item.get("changes")
        if isinstance(changes, list) and changes and all(isinstance(change, dict) and
                isinstance(change.get("path"), str) and change["path"] for change in changes):
            if outcome_cwd:
                row["changed_files"], row["file_names"] = project_changes(changes, outcome_cwd)
            else:
                row["changed_files"] = len(changes)
    if row["command"] or any(row.get(key) for key in ("keys", "claims", "hints", "changed_files", "intent")):
        row.update(normalize_times(raw, "startedAtMs", "completedAtMs", 1000))
    return row


def read_pages(server, method, params, maximum, decode):
    scan = pages(server, method, params, maximum, decode, keep_partial=True)
    if scan.pages and scan.coverage in {"invalid_or_repeated_cursor", "rpc_-32602"}:
        scan = pages(server, method, params, maximum, decode, keep_partial=True)
    return scan


def record_scan(project, name, scan):
    if scan.coverage != "complete":
        project.issues[f"{name}:{scan.coverage}"] += 1
    if scan.rejected:
        project.issues[f"{name}:rejected_rows"] += scan.rejected
    if scan.duplicates:
        project.issues[f"{name}:duplicate_rows"] += scan.duplicates


def overlaps(row, window):
    start, end = row["start"], row["end"]
    return (start is None or start < window.cutoff) and (end is None or end >= window.start)


def relevant(row, window):
    return window.contains(row["start"]) or window.contains(row["end"]) or (row["start"] is None and row["end"] is None)


def collect_items(server, project, thread_id, turn, limits, include_work, include_outcomes):
    result = read_pages(server, "thread/items/list", {"threadId": thread_id, "turnId": turn["id"],
                        "limit": 20, "sortDirection": "desc"}, limits.item_pages,
                        lambda row: decode_item(row, turn["id"], include_work=include_work,
                                                outcome_cwd=project.path if include_outcomes else None))
    record_scan(project, "items", result)
    return result


def collect_thread(server, project, candidate, window, include_commands, limits, *, include_work=False, include_outcomes=False):
    thread_id = candidate["id"]
    try:
        response = server.call("thread/read", {"threadId": thread_id, "includeTurns": False}).get("thread")
    except RpcError as error:
        project.issues[f"detail:{error}"] += 1
        return None
    detail = decode_session(response, project.path) if isinstance(response, dict) else None
    if detail is None or detail["id"] != thread_id:
        project.issues["detail:scope_or_id_mismatch"] += 1
        return None
    project.chats_examined += 1
    turn_scan = read_pages(server, "thread/turns/list", {"threadId": thread_id, "itemsView": "notLoaded",
                           "limit": 20, "sortDirection": "desc"}, limits.turn_pages, decode_turn)
    record_scan(project, "turns", turn_scan)
    project.sessions[thread_id] = {**detail, "archived": candidate["archived"]}
    for raw_turn in turn_scan.rows:
        turn = {**raw_turn, "thread_id": thread_id}
        commands, signals = [], []
        item_scan = None
        if not turn_scan.transport_error and (include_commands or include_work) and overlaps(turn, window):
            item_scan = collect_items(server, project, thread_id, turn, limits, include_work, include_outcomes)
            for row in item_scan.rows:
                if row["command"] and relevant(row, window):
                    commands.append({**row, "thread_id": thread_id, "turn_id": turn["id"]})
                if include_work and (row.get("keys") or any(row.get(key) for key in ("claims", "hints", "changed_files", "intent", "test_result"))):
                    signals.append(row)
        observed = any(relevant(row, window) and any(row.get(key) for key in
                       ("claims", "hints", "changed_files", "intent", "test_result"))
                       for row in signals)
        if relevant(turn, window) or commands or observed:
            if include_work:
                turn["signals"] = signals
                turn["signals_complete"] = item_scan is not None and item_scan.coverage == "complete"
            project.turns.append(turn)
            project.commands.extend(commands)
        if item_scan is not None and item_scan.transport_error:
            return item_scan.coverage
    return turn_scan.coverage if turn_scan.transport_error else None


def collect_project(server, project, window, include_commands, limits, *, include_work=False, include_outcomes=False):
    candidates = {}
    for archived in (False, True):
        label = "archived" if archived else "ordinary"
        scan = read_pages(server, "thread/list", {"cwd": project.path, "archived": archived, "limit": 25,
                          "sourceKinds": list(SOURCES), "modelProviders": [], "useStateDbOnly": True,
                          "sortKey": "updated_at", "sortDirection": "desc"}, limits.list_pages,
                          lambda raw: decode_session(raw, project.path))
        project.listings[label] = {"status": scan.coverage, "pages": scan.pages, "chats": len(scan.rows)}
        record_scan(project, label, scan)
        for row in scan.rows:
            if row["id"] in candidates:
                project.issues["archive_scope_overlap"] += 1
            else:
                candidates[row["id"]] = {**row, "archived": archived}
        if scan.transport_error:
            return scan.coverage
    for candidate in candidates.values():
        error = collect_thread(server, project, candidate, window, include_commands, limits, include_work=include_work,
                               include_outcomes=include_outcomes)
        if error:
            return error
    project.finished = True
    return None


def collect(paths, window, *, include_commands=False, include_work=False, include_outcomes=False, limits=Limits(), cancel=None):
    history = History([ProjectHistory(path) for path in paths])
    executable = shutil.which("codex")
    if not executable:
        history.error = "codex_not_found"
        return history
    try:
        with AppServer(executable, cancel=cancel) as server:
            history.namespace = source_namespace(server.initialize("dynamic_pearl_work_memory").get("codexHome"))
            for project in history.projects:
                history.error = collect_project(server, project, window, include_commands, limits, include_work=include_work,
                                                include_outcomes=include_outcomes)
                if history.error:
                    break
            server.check_cancelled()
        if server.process.returncode:
            history.error = history.error or "server_exit_error"
    except Cancelled:
        raise
    except ProbeError as error:
        history.error = str(error)
    except OSError:
        history.error = "process_io_error"
    return history
