from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone, tzinfo
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from work_memory import codex_rpc, review, source_codex, store, time_range
from work_memory.__main__ import main


PROJECT = os.path.abspath("fixture-project")
OTHER = os.path.abspath("other-project")
MIDNIGHT = int(datetime(2026, 11, 19).timestamp())
AS_OF = (MIDNIGHT + 3600) * 1000


def metadata(path=PROJECT, thread_id="sample-thread"):
    return {"id": thread_id, "cwd": path, "source": "vscode", "createdAt": 10, "updatedAt": 20,
            "name": "Example\x1b\nchat", "preview": "PRIVATE_PROMPT"}


def scan(*rows, cursor=None):
    return {"data": list(rows), "nextCursor": cursor}


def attempt(project, replies, window, *, commands=False, limits=source_codex.Limits()):
    server = Mock()
    server.call.side_effect = replies
    failure = source_codex.collect_project(server, project, window, commands, limits)
    return server, failure


def finished_history(*paths, observed_end=None):
    projects = []
    for path in paths:
        project = source_codex.ProjectHistory(path)
        project.listings = {"ordinary": {"status": "complete", "pages": 1, "chats": 1},
                            "archived": {"status": "complete", "pages": 1, "chats": 0}}
        project.finished = True
        project.chats_examined = 1
        project.sessions["sample-thread"] = dict(source_codex.decode_session(metadata(path), path), archived=False)
        project.turns.append({"id": "round", "thread_id": "sample-thread", "start": MIDNIGHT * 1000,
                              "end": observed_end, "status": "completed" if observed_end else "inProgress"})
        projects.append(project)
    return source_codex.History(projects, source_codex.source_namespace())


class SourceTests(unittest.TestCase):
    def test_archived_result_has_its_own_coverage_and_source_flag(self):
        window = time_range.make_window("today", AS_OF)
        project = source_codex.ProjectHistory(PROJECT)
        archived = metadata(thread_id="archived-thread")
        replies = [scan(), scan(archived), {"thread": archived},
                   scan({"id": "archived-round", "startedAt": MIDNIGHT, "completedAt": MIDNIGHT + 1, "status": "completed"})]
        server, error = attempt(project, replies, window)
        self.assertIsNone(error)
        report = review.build_report(source_codex.History([project]), window)
        view = report["projects"][0]
        self.assertFalse(server.call.call_args_list[0].args[1]["archived"])
        self.assertTrue(server.call.call_args_list[1].args[1]["archived"])
        self.assertEqual(view["listings"]["archived"]["chats"], 1)
        self.assertTrue(all(event["source"]["archived"] for event in view["events"]))
        self.assertFalse(report["archive_coverage_validated"])

    def test_archiving_during_pagination_deduplicates_the_same_thread(self):
        window = time_range.make_window("today", AS_OF)
        project = source_codex.ProjectHistory(PROJECT)
        thread = metadata()
        replies = [scan(thread), scan(thread), {"thread": thread}, scan({"id": "once", "startedAt": MIDNIGHT})]
        _, error = attempt(project, replies, window)
        self.assertIsNone(error)
        view = review.build_report(source_codex.History([project]), window)["projects"][0]
        self.assertEqual(view["status"], "partial")
        self.assertEqual(view["issues"], {"archive_scope_overlap": 1})
        self.assertEqual(view["counts"], {"turn_started": 1})

    def test_replays_a_cross_day_turn_and_its_command_with_provenance(self):
        window = time_range.make_window("today", AS_OF)
        project = source_codex.ProjectHistory(PROJECT)
        thread = metadata()
        overnight = {"id": "round", "startedAt": MIDNIGHT - 1, "completedAt": MIDNIGHT + 4, "status": "completed"}
        command = {"turnId": "round", "startedAtMs": MIDNIGHT * 1000 - 1, "completedAtMs": MIDNIGHT * 1000,
                   "item": {"id": "command-1", "type": "commandExecution", "command": "PRIVATE_COMMAND",
                            "aggregatedOutput": "PRIVATE_OUTPUT", "exitCode": 0}}
        undated = {"id": "no-time", "status": "completed"}
        replies = [scan(thread), scan(), {"thread": thread}, scan(overnight, cursor="next"),
                   scan(overnight, undated), scan(command), scan()]
        server, error = attempt(project, replies, window, commands=True)
        report = review.build_report(source_codex.History([project]), window, include_commands=True)
        self.assertIsNone(error)
        self.assertEqual(report["status"], "complete")
        view = report["projects"][0]
        self.assertEqual(view["counts"], {"turn_ended": 1, "command_ended": 1})
        self.assertEqual(view["issues"], {"turns:duplicate_rows": 1})
        self.assertEqual(len(view["undated"]), 1)
        self.assertEqual(view["events"][1]["source"], {"thread_id": "sample-thread", "turn_id": "round",
                         "item_id": "command-1", "open_url": "codex://threads/sample-thread", "source": "vscode",
                         "archived": False, "title": "Example chat"})
        self.assertEqual(view["events"][1]["at_ms"], MIDNIGHT * 1000)
        self.assertEqual(view["events"][1]["exit_code"], 0)
        self.assertNotIn("PRIVATE_", json.dumps(report))
        self.assertNotIn("测试通过", review.render_text(report))
        first_query = server.call.call_args_list[0].args[1]
        self.assertEqual(first_query["cwd"], PROJECT)
        self.assertTrue(first_query["useStateDbOnly"])
        self.assertEqual(first_query["sourceKinds"], ["vscode", "exec"])
        self.assertTrue(server.call.call_args_list[1].args[1]["archived"])
        yesterday = review.build_report(source_codex.History([project]), time_range.make_window("yesterday", AS_OF),
                                        include_commands=True)
        self.assertEqual(yesterday["projects"][0]["counts"], {"turn_started": 1, "command_started": 1})

    def test_scope_mismatch_never_loads_unapproved_turns(self):
        window = time_range.make_window("today", AS_OF)
        project = source_codex.ProjectHistory(PROJECT)
        server, _ = attempt(project, [scan(metadata(), metadata(OTHER, "outside")), scan(),
                                      {"thread": metadata(OTHER)}], window)
        result = review.build_report(source_codex.History([project]), window)
        self.assertEqual(result["status"], "partial")
        self.assertEqual([call.args[0] for call in server.call.call_args_list], ["thread/list", "thread/list", "thread/read"])
        self.assertFalse(result["projects"][0]["events"])

    def test_empty_unsupported_and_truncated_reads_are_distinct(self):
        window = time_range.make_window("today", AS_OF)
        empty = source_codex.ProjectHistory(PROJECT)
        attempt(empty, [scan(), scan()], window)
        self.assertEqual(review.build_report(source_codex.History([empty]), window)["status"], "empty")
        missing = source_codex.History([source_codex.ProjectHistory(PROJECT)], error="server_closed")
        self.assertEqual(review.build_report(missing, window)["status"], "unavailable")
        for error in (codex_rpc.RpcError("rpc_-32601"), codex_rpc.ProbeError("request_timeout")):
            with self.subTest(error=error):
                project = source_codex.ProjectHistory(PROJECT)
                replies = [scan(metadata()), scan(), {"thread": metadata()},
                           scan({"id": "first", "startedAt": MIDNIGHT}, cursor="next"), error]
                _, failure = attempt(project, replies, window)
                report = review.build_report(source_codex.History([project], error=failure), window)
                self.assertEqual(report["status"], "partial")
                self.assertEqual(report["projects"][0]["counts"], {"turn_started": 1})

    def test_invalid_continuation_restarts_from_first_page_once(self):
        client = Mock()
        client.call.side_effect = [scan({"id": "old"}, cursor="expired"), codex_rpc.RpcError("rpc_-32602"),
                                   scan({"id": "new"})]
        result = source_codex.read_pages(client, "thread/list", {"cwd": PROJECT}, 3, lambda row: row)
        self.assertEqual(result.rows, [{"id": "new"}])
        self.assertEqual(result.coverage, "complete")
        self.assertEqual(client.call.call_args_list[-1].args[1], {"cwd": PROJECT})

    def test_cancellation_is_not_treated_as_a_partial_success(self):
        client = object.__new__(codex_rpc.AppServer)
        client.cancel = Event()
        client.cancel.set()
        with self.assertRaises(codex_rpc.Cancelled):
            source_codex.read_pages(client, "thread/list", {"cwd": PROJECT}, 1, lambda row: row)

    def test_transport_deadline_is_bounded(self):
        client = object.__new__(codex_rpc.AppServer)
        client.cancel = None
        client.serial = 0
        client.deadline = 1
        client.send = Mock()
        with patch.object(codex_rpc, "monotonic", return_value=2):
            with self.assertRaisesRegex(codex_rpc.ProbeError, "time_budget"):
                client.call("thread/list", {})
        client.send.assert_not_called()


class CalendarTests(unittest.TestCase):
    def test_calendar_day_is_23_hours_across_spring_transition(self):
        class SpringZone(tzinfo):
            def dst(self, dt):
                return timedelta(hours=dt.replace(tzinfo=None) >= datetime(2026, 3, 8, 2))

            def utcoffset(self, dt):
                return timedelta(hours=-5) + self.dst(dt)

            def tzname(self, dt):
                return "Spring fixture"

        instant = datetime(2026, 3, 9, 14, tzinfo=timezone.utc)
        window = time_range.make_window("yesterday", int(instant.timestamp() * 1000), zone=SpringZone())
        self.assertEqual(window.end - window.start, 23 * 60 * 60 * 1000)
        self.assertTrue(window.contains(window.start))
        self.assertFalse(window.contains(window.end))

    def test_today_excludes_as_of_and_week_starts_at_local_midnight(self):
        today = time_range.make_window("today", AS_OF)
        week = time_range.make_window("last-7-days", AS_OF)
        self.assertEqual(today.cutoff, AS_OF)
        self.assertTrue(today.contains(AS_OF - 1))
        self.assertFalse(today.contains(AS_OF))
        self.assertEqual(datetime.fromtimestamp(week.start / 1000).date().isoformat(), "2026-11-13")


class StoreTests(unittest.TestCase):
    def test_rerun_updates_late_end_without_duplicate_turns_or_stale_overwrite(self):
        history = finished_history(PROJECT, OTHER)
        older = time_range.make_window("today", AS_OF)
        newer = time_range.make_window("today", AS_OF + 1000)
        key = store.snapshot_key(history.namespace, (PROJECT, OTHER), older, False)
        self.assertEqual(key, store.snapshot_key(history.namespace, (OTHER, PROJECT), newer, False))
        with store.Store() as database:
            database.save(key, history, older, review.build_report(history, older), 0)
            late = finished_history(PROJECT, OTHER, observed_end=AS_OF)
            database.save(key, late, newer, review.build_report(late, newer), 0)
            self.assertFalse(database.save(key, history, older, review.build_report(history, older), 0))
            self.assertEqual(database.db.execute("SELECT COUNT(*), COUNT(end) FROM turns").fetchone(), (2, 2))
            self.assertEqual(database.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
            self.assertEqual(database.cached(key, 0)["projects"][0]["counts"], {"turn_ended": 1, "turn_started": 1})

    def test_project_clear_preserves_exclusion_and_rejects_an_inflight_write(self):
        with TemporaryDirectory() as directory:
            filename = Path(directory) / "test.sqlite3"
            with store.Store(filename) as first, store.Store(filename) as second:
                history = finished_history(PROJECT, OTHER)
                window = time_range.make_window("today", AS_OF)
                report = review.build_report(history, window)
                first.save("combined", history, window, report, 0)
                solo = finished_history(OTHER)
                first.save("other", solo, window, review.build_report(solo, window), 0)
                second.set_excluded([PROJECT], True)
                second.clear([PROJECT])
                with self.assertRaises(store.StoreError):
                    first.save("combined", history, window, report, 0)
                allowed, excluded, generation = first.selection([PROJECT, OTHER])
                self.assertEqual((allowed, excluded), ([OTHER], [PROJECT]))
                self.assertIsNone(first.cached("combined", generation))
                self.assertIsNotNone(first.cached("other", generation))
                self.assertEqual(first.db.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 1)
                second.clear()
                self.assertEqual(first.db.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 0)
                self.assertEqual(first.selection([PROJECT])[1], [PROJECT])

    def test_cli_partial_result_keeps_the_previous_complete_snapshot(self):
        history = finished_history(PROJECT)
        partial = finished_history(PROJECT)
        partial.projects[0].issues["ordinary:page_budget"] = 1
        with TemporaryDirectory() as directory:
            filename = str(Path(directory) / "test.sqlite3")
            tail = ["--project", PROJECT, "--format", "json"]
            reports = []
            with (
                patch("work_memory.__main__.time_ns", return_value=AS_OF * 1_000_000),
                patch("work_memory.__main__.collect", side_effect=[history, partial]) as collect,
            ):
                for command, expected in (("review", 0), ("review", 3), ("cached", 0)):
                    with redirect_stdout(StringIO()) as output:
                        self.assertEqual(main(["--db", filename, command, *tail]), expected)
                    reports.append(json.loads(output.getvalue()))
            self.assertEqual(collect.call_count, 2)
            self.assertEqual([report["cache"] for report in reports], ["saved", "unchanged", "hit"])
            self.assertEqual(reports[-1]["mode"], "cached")
            self.assertEqual(reports[-1]["status"], "complete")

    def test_existing_non_work_memory_database_is_rejected(self):
        with TemporaryDirectory() as directory:
            filename = Path(directory) / "other.sqlite3"
            with sqlite3.connect(filename) as other:
                other.execute("CREATE TABLE unrelated (value TEXT)")
                other.execute("INSERT INTO unrelated VALUES ('keep')")
            other.close()
            with self.assertRaises(store.StoreError):
                store.Store(filename)
            with sqlite3.connect(filename) as other:
                self.assertEqual(other.execute("SELECT value FROM unrelated").fetchone(), ("keep",))
            other.close()


if __name__ == "__main__":
    unittest.main()
