"""Bounded stdio transport and decoders for read-only Codex history."""

from dataclasses import dataclass, field
import json
import os
from queue import Empty, Queue
import subprocess
from threading import Event, Thread
from time import monotonic


METHODS = {"initialize", "thread/list", "thread/read", "thread/turns/list", "thread/items/list"}
MAX_FRAME = 4 * 1024 * 1024


class ProbeError(Exception):
    """A safe diagnostic code without source text or paths."""


class RpcError(ProbeError):
    pass


class Cancelled(ProbeError):
    pass


class AppServer:
    def __init__(self, executable, *, cancel=None):
        self.process = subprocess.Popen(
            [executable, "app-server", "--listen", "stdio://", "-c", "analytics.enabled=false"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.incoming = Queue()
        self.stopped = Event()
        self.cancel = cancel
        self.serial = 0
        self.bytes_read = 0
        self.deadline = monotonic() + 50
        self.reader = Thread(target=self.read_frames, daemon=True)
        self.reader.start()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stopped.set()
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=2)
        self.process.stdout.close()

    def read_frames(self):
        while not self.stopped.is_set():
            try:
                frame = self.process.stdout.readline(MAX_FRAME + 1)
            except OSError:
                self.incoming.put("process_io_error")
                return
            if not frame or len(frame) > MAX_FRAME:
                self.incoming.put("frame_too_large" if frame else "server_closed")
                return
            self.bytes_read += len(frame)
            if self.bytes_read > 32 * 1024 * 1024:
                self.incoming.put("transfer_budget")
                return
            try:
                message = json.loads(frame)
            except (ValueError, RecursionError):
                self.incoming.put("invalid_frame")
                return
            if isinstance(message, dict) and "id" in message and "method" not in message:
                self.incoming.put(message)

    def send(self, message):
        try:
            self.process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
            self.process.stdin.flush()
        except OSError:
            raise ProbeError("server_closed") from None

    def call(self, method, params):
        if method not in METHODS:
            raise ValueError("Method outside the historical read allowlist")
        self.check_cancelled()
        self.serial += 1
        deadline = min(self.deadline, monotonic() + 8)
        if monotonic() >= deadline:
            raise ProbeError("time_budget")
        self.send({"method": method, "id": self.serial, "params": params})
        while monotonic() < deadline:
            self.check_cancelled()
            try:
                message = self.incoming.get(timeout=min(.1, max(0, deadline - monotonic())))
            except Empty:
                continue
            if isinstance(message, str):
                raise ProbeError(message)
            if message.get("id") != self.serial:
                continue
            result = message.get("result")
            if isinstance(result, dict):
                return result
            error = message.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise RpcError(f"rpc_{code}" if type(code) is int else "invalid_response")
        raise ProbeError("request_timeout")

    def check_cancelled(self):
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled("cancelled")

    def initialize(self, name="dynamic_pearl_phase0"):
        result = self.call("initialize", {"clientInfo": {"name": name, "version": "1"}})
        self.send({"method": "initialized", "params": {}})
        return result


@dataclass
class Scan:
    rows: list = field(default_factory=list)
    pages: int = 0
    duplicates: int = 0
    rejected: int = 0
    coverage: str = "page_budget"
    transport_error: bool = False


def pages(server, method, params, maximum, decode, *, keep_partial=False):
    scan = Scan()
    cursor = None
    cursors = set()
    identifiers = set()
    for _ in range(maximum):
        request = dict(params, cursor=cursor) if cursor else params
        try:
            response = server.call(method, request)
        except RpcError as error:
            scan.coverage = str(error)
            return scan
        except Cancelled:
            raise
        except ProbeError as error:
            if not keep_partial:
                raise
            scan.coverage = str(error)
            scan.transport_error = True
            return scan
        rows = response.get("data")
        if not isinstance(rows, list):
            scan.coverage = "invalid_page"
            return scan
        scan.pages += 1
        for raw in rows:
            row = decode(raw) if isinstance(raw, dict) else None
            if row is None:
                scan.rejected += 1
            elif row["id"] in identifiers:
                scan.duplicates += 1
            else:
                identifiers.add(row["id"])
                scan.rows.append(row)
        cursor = response.get("nextCursor")
        if cursor is None:
            scan.coverage = "rows_rejected" if scan.rejected else "complete"
            break
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            scan.coverage = "invalid_or_repeated_cursor"
            break
        cursors.add(cursor)
    return scan


def identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 100 and value.isascii() and all(
        char.isalnum() or char in "_-" for char in value
    )


def path_key(path):
    return os.path.normcase(os.path.normpath(path))


def same_path(value, requested):
    return isinstance(value, str) and os.path.isabs(value) and path_key(value) == path_key(requested)


def timestamp(raw, key, scale=1):
    value = raw.get(key)
    if type(value) is int and 0 <= value < 253402214400 * scale:
        return value * 1000 // scale
    return None


def timing(raw, start, end, scale=1):
    return {"start": timestamp(raw, start, scale), "end": timestamp(raw, end, scale)}
