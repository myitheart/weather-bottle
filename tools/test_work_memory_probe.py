import argparse
from datetime import datetime
from io import BytesIO
import os
from queue import Queue
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import work_memory_probe as probe
from work_memory import codex_rpc


class FakeServer:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class ProbeTests(unittest.TestCase):
    def test_overlapping_pages_keep_only_one_row_and_preserve_query(self):
        server = FakeServer(
            {"data": [{"id": "one"}], "nextCursor": "cursor"},
            {"data": [{"id": "one"}, {"id": "two"}], "nextCursor": None},
        )
        result = probe.pages(server, "thread/list", {"archived": True}, 2, lambda row: row)
        self.assertEqual(result.coverage, "complete")
        self.assertEqual(result.duplicates, 1)
        self.assertEqual([row["id"] for row in result.rows], ["one", "two"])
        self.assertEqual(server.calls[1][1], {"archived": True, "cursor": "cursor"})

    def test_budget_repeated_cursor_and_unsupported_are_distinct(self):
        partial = {"data": [{"id": "one"}], "nextCursor": "same"}
        for responses, pages, expected in (
            ([partial], 1, "page_budget"),
            ([partial, partial], 2, "invalid_or_repeated_cursor"),
            ([probe.RpcError("rpc_-32601")], 1, "rpc_-32601"),
        ):
            with self.subTest(expected=expected):
                result = probe.pages(FakeServer(*responses), "thread/items/list", {}, pages, lambda row: row)
                self.assertEqual(result.coverage, expected)

    def test_cwd_mismatch_does_not_read_turns(self):
        authorized = os.path.abspath("allowed")
        outside = os.path.abspath("outside")
        detail = {"thread": {"id": "one", "cwd": outside}}
        server = FakeServer(detail)
        report = probe.check_history(server, "one", authorized, argparse.Namespace(), {})
        self.assertEqual(report["read"], "scope_or_id_mismatch")
        self.assertEqual([method for method, _ in server.calls], ["thread/read"])
        self.assertIsNone(probe.session(detail["thread"], authorized))
        self.assertIsNone(probe.session({"id": "one", "cwd": "allowed"}, authorized))

    def test_seconds_and_milliseconds_across_midnight(self):
        midnight = int(datetime(2026, 11, 19, 0, 0).timestamp())
        windows = probe.date_windows((midnight + 600) * 1000)
        cross = probe.turn({"id": "turn-1", "status": "completed", "startedAt": midnight - 1,
                            "completedAt": midnight + 1})
        report = probe.time_report([cross, {"start": None, "end": None}], windows)
        self.assertEqual(report["cross_midnight"], 1)
        self.assertEqual(report["no_time"], 1)
        self.assertEqual(report["window_events"]["today"], {"starts": 0, "ends": 1})
        self.assertEqual(report["window_events"]["yesterday"], {"starts": 1, "ends": 0})
        self.assertEqual(report["window_events"]["last_7_days"], {"starts": 1, "ends": 1})

        entry = {"turnId": "turn-1", "startedAtMs": midnight * 1000 - 1, "completedAtMs": midnight * 1000,
                 "item": {"id": "entry", "type": "commandExecution", "exitCode": 0,
                          "command": "discard", "aggregatedOutput": "discard"}}
        result = probe.item(entry, "turn-1")
        self.assertIsNone(probe.item(entry, "turn-2"))
        self.assertEqual(result["start"], midnight * 1000 - 1)
        self.assertEqual(result["end"], midnight * 1000)
        self.assertTrue(result["exit_zero"])
        self.assertNotIn("discard", str(result))

    def test_history_transport_has_no_mutation_methods(self):
        client = object.__new__(probe.AppServer)
        for method in ("thread/start", "thread/archive", "turn/start", "command/exec"):
            with self.subTest(method=method), self.assertRaises(ValueError):
                client.call(method, {})

    def test_bad_frames_and_unexpected_process_exit_are_reported(self):
        for frame, expected in ((b"not json\n", "invalid_frame"),
                                (b"12345678901", "frame_too_large"),
                                (b"", "server_closed")):
            with self.subTest(expected=expected), patch.object(codex_rpc, "MAX_FRAME", 10):
                client = object.__new__(probe.AppServer)
                client.process = SimpleNamespace(stdout=BytesIO(frame))
                client.incoming = Queue()
                client.stopped = Event()
                client.bytes_read = 0
                client.read_frames()
                self.assertEqual(client.incoming.get_nowait(), expected)


if __name__ == "__main__":
    unittest.main()
