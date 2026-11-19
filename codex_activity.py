"""Local status bridge for Codex lifecycle hooks and CLI tasks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile
from threading import Event, Thread
from time import sleep, time
from uuid import uuid4


PROJECT = Path(__file__).resolve().parent
PROJECT_ID = hashlib.sha256(os.fsencode(os.path.normcase(PROJECT))).hexdigest()[:16]
STATES = {"running", "ended", "failed", "interrupted", "unknown"}
HOOK_EVENTS = {"UserPromptSubmit": "running", "Stop": "ended", "Interrupt": "interrupted"}
HOOK_DESCRIPTION = "Dynamic Bottle local activity status"


def activity_path():
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / "DynamicBottle" / f"codex-{PROJECT_ID}.json"


def read_scope():
    try:
        value = activity_path().with_suffix(".scope").read_text(encoding="utf-8").strip()
    except OSError:
        return "project"
    return value if value in {"project", "global", "off"} else "project"


def set_scope(scope):
    if scope not in {"project", "global", "off"}:
        raise ValueError("Unknown Codex activity scope")
    path = activity_path().with_suffix(".scope")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, scope)


def atomic_write(path, contents):
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        output.write(contents)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def install_global_hooks():
    path = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "hooks.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        config = {"description": HOOK_DESCRIPTION, "hooks": {}}
    if not isinstance(config, dict) or not isinstance(config.get("hooks", {}), dict):
        raise ValueError("Invalid Codex hooks configuration")
    hooks = config.setdefault("hooks", {})

    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    if os.name == "nt":
        command = f"& {quote(python)} -X utf8 {quote(Path(__file__).resolve())} --hook-global"
    else:
        raise OSError("Global hook installation is supported on Windows")
    changed = False
    for event in HOOK_EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list) or any(not isinstance(group, dict) or not isinstance(group.get("hooks"), list)
                                               for group in groups):
            raise ValueError(f"Invalid Codex hook groups for {event}")
        if any(isinstance(handler, dict) and handler.get("command") == command
               for group in groups for handler in group["hooks"]):
            continue
        groups.append({"hooks": [{"type": "command", "command": command,
                                  "timeout": 2 if event == "Interrupt" else 3}]})
        changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return path


def read_records():
    try:
        stored = json.loads(activity_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    records = stored.get("activities", [stored])
    if not isinstance(records, list):
        return {}
    valid = {}
    for data in records:
        try:
            if (data["state"] in STATES and isinstance(data["id"], str)
                    and 0 < data["started"] <= data["updated"] <= time() + 5
                    and data["source"] in {"desktop", "cli"}):
                valid[data["id"]] = data
        except (ValueError, TypeError, KeyError):
            continue
    return valid


def activity_expiry(data):
    return 12 if data["source"] == "cli" else 3600


NOTICE_SECONDS = 7


def read_activities(now=None, *, records=None, scope=None):
    scope = read_scope() if scope is None else scope
    if scope == "off":
        return []
    now = time() if now is None else now
    # A newer turn supersedes any older turn from the same conversation.
    chats = {}
    records = read_records() if records is None else records
    for record in sorted(records.values(), key=lambda item: item["started"], reverse=True):
        if scope == "global" or record.get("in_project", True):
            chats.setdefault(record.get("thread") or record["id"], record)
    running, recent = [], []
    for record in chats.values():
        age = now - record["updated"]
        if record["state"] == "running":
            age -= activity_expiry(record)
            if age <= 0:
                running.append(record)
                continue
            record = {**record, "state": "unknown"}
        if age < NOTICE_SECONDS:
            recent.append(record)
    return sorted(running, key=lambda item: item["started"]) + sorted(
        recent, key=lambda item: item["updated"], reverse=True)


REVIEW_STATES = frozenset({"ended", "failed", "interrupted"})


def read_pin():
    try:
        record = json.loads(activity_path().with_suffix(".pin.json").read_text(encoding="utf-8"))
        if (record["state"] in (REVIEW_STATES | {"running", "unknown"})
                and record["source"] in {"desktop", "cli"}
                and 0 < record["started"] <= record["updated"]
                and all(isinstance(record[key], str) and record[key] for key in ("id", "thread"))):
            return record
    except (OSError, KeyError, ValueError, TypeError):
        pass
    return None


def save_pin(record):
    path = activity_path().with_suffix(".pin.json")
    if record is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ("id", "thread", "project", "in_project", "source", "state", "started", "updated")
    atomic_write(path, json.dumps({key: record.get(key) for key in fields}))


def display_name(value):
    return " ".join(value.split())[:160] if isinstance(value, str) else ""


def project_name(cwd, in_project):
    if in_project:
        return "灵动瓶"
    if not cwd:
        return "未分组"
    folder = Path(cwd)
    # Use the enclosing repository name when Codex runs in a subdirectory.
    for candidate in (folder, *folder.parents):
        if (candidate / ".git").exists():
            return display_name(candidate.name) or "未分组"
    return display_name(folder.name) or "未分组"


def publish(key, state, source, *, starting=False, thread_id=None, in_project=True, project=None):
    path = activity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import msvcrt
        with path.with_suffix(".lock").open("ab") as lock:
            for attempt in range(5):
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if attempt == 4:
                        raise
                    sleep(.02)
            write_activity(path, key, state, source, starting, thread_id, in_project, project)
    else:
        write_activity(path, key, state, source, starting, thread_id, in_project, project)


def write_activity(path, key, state, source, starting, thread_id, in_project, project):
    records = read_records()
    current = records.get(key)
    if starting and current:
        return
    if not starting and (not current or current["id"] != key or current["state"] != "running"):
        return
    now = time()
    record = {"id": key, "state": state, "source": source,
              "started": now if starting else current["started"], "updated": now,
              "thread": thread_id or (None if starting else current.get("thread")),
              "in_project": in_project if starting else current.get("in_project", True),
              "project": project if starting else current.get("project")}
    records[key] = record
    latest = sorted(records.values(), key=lambda item: item["updated"], reverse=True)[:40]
    pin = read_pin()
    protected = records.get(pin["id"]) if pin else None
    if protected is not None and protected not in latest:
        latest.append(protected)
    atomic_write(path, json.dumps({"activities": latest}))


def hook(global_hook=False):
    try:
        event = json.load(sys.stdin)
        if os.environ.get("DYNAMIC_BOTTLE_CLI_BRIDGE") == "1":
            return
        scope = read_scope()
        in_project = bool(event.get("cwd")) and Path(event["cwd"]).resolve().is_relative_to(PROJECT)
        if (global_hook and scope == "global") or (not global_hook and scope == "project" and in_project):
            state = HOOK_EVENTS.get(event["hook_event_name"])
            thread, turn = event.get("session_id"), event.get("turn_id")
            if state and isinstance(thread, str) and isinstance(turn, str) and thread and turn:
                publish(f"{thread}:{turn}", state, "desktop", starting=state == "running",
                        thread_id=thread, in_project=in_project,
                        project=project_name(event.get("cwd"), in_project) if state == "running" else None)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    finally:
        print("{}")


def run_cli(prompt):
    key = uuid4().hex
    # Use the installed CLI and its existing login; display the final answer in this terminal.
    command = ["codex", "exec", "--json", "--sandbox", "read-only", "--cd", str(PROJECT), "--", prompt]
    publish(key, "running", "cli", starting=True, project="灵动瓶")
    stop = Event()

    def heartbeat():
        while not stop.wait(3):
            try:
                publish(key, "running", "cli")
            except OSError:
                pass

    worker = Thread(target=heartbeat, daemon=True)
    worker.start()
    state = "failed"
    result = 1
    thread_id = None
    try:
        env = {**os.environ, "DYNAMIC_BOTTLE_CLI_BRIDGE": "1"}
        with subprocess.Popen(command, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True,
                              encoding="utf-8", errors="replace") as process:
            completed = False
            try:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "turn.completed":
                        completed = True
                    if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                        thread_id = event["thread_id"]
                        publish(key, "running", "cli", thread_id=thread_id)
                    item = event.get("item") or {}
                    if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                        print(item.get("text", ""), flush=True)
                result = process.wait()
                state = "ended" if result == 0 and completed else "failed"
                if state == "failed" and result == 0:
                    result = 1
            except KeyboardInterrupt:
                process.terminate()
                state, result = "interrupted", 130
    except OSError as error:
        print(error, file=sys.stderr)
    finally:
        stop.set()
        worker.join()
        publish(key, state, "cli", thread_id=thread_id)
    return result


if __name__ == "__main__":
    if sys.argv[1:] in (["--hook"], ["--hook-global"]):
        hook(global_hook=sys.argv[1] == "--hook-global")
    elif sys.argv[1:] == ["--enable-global-hook"]:
        print(install_global_hooks())
        set_scope("global")
    elif len(sys.argv) == 2 and sys.argv[1].strip():
        sys.exit(run_cli(sys.argv[1]))
    else:
        sys.exit("Usage: python codex_activity.py \"prompt\"")

