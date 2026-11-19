from contextlib import closing, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from test_work_memory_review import AS_OF, MIDNIGHT, OTHER, PROJECT, metadata, scan
from work_memory import review, source_codex, store, time_range, work_items, work_signals
from work_memory.__main__ import main


TITLE = "订单退款状态调整"
WINDOW = time_range.make_window("today", AS_OF)


def fixture_history(path=PROJECT):
    history = source_codex.History([source_codex.ProjectHistory(path)], source_codex.source_namespace())
    project = history.projects[0]
    project.listings = {"ordinary": {"status": "complete", "pages": 1, "chats": 5}}
    project.finished = True
    names = ["thread-a", "thread-b", "thread-c", "thread-d", "thread-e"]
    keys = [["BILL-19"], ["BILL-19"], ["BILL-23"], ["BILL-19", "BILL-23"], []]
    for index, (chat, markers) in enumerate(zip(names, keys)):
        project.sessions[chat] = dict(source_codex.decode_session(metadata(path, chat), path), archived=False, title=TITLE)
        project.turns.append({"id": "round", "thread_id": chat, "start": MIDNIGHT * 1000 + index,
                              "end": MIDNIGHT * 1000 + index + 10, "status": "completed", "signals_complete": True,
                              "signals": [{"id": "message", "keys": markers, "start": MIDNIGHT * 1000, "end": None}]})
    project.turns[0]["signals"].append({"id": "report", "claims": [("test", "success"), ("beta", "success")],
                         "hints": [("acceptance", "等待测试反馈")], "end": MIDNIGHT * 1000 + 2, "start": None})
    project.turns[1]["signals"].append({"id": "failure", "claims": [("test", "failed")],
                                        "end": MIDNIGHT * 1000 + 4, "start": None})
    project.commands.append({"id": "command-1", "turn_id": "round", "thread_id": "thread-a",
                             "start": MIDNIGHT * 1000, "end": MIDNIGHT * 1000 + 3, "exit_code": 0})
    return history


def work_report(history):
    return review.build_report(history, WINDOW, include_commands=True, include_work=True)


class SignalTests(unittest.TestCase):
    def test_only_explicit_namespaced_user_markers_are_used(self):
        rows = [{"type": "text", "text": "关联 OPS-99\n> 事项: OPS-4\n```\n事项: OPS-2\n```\n"
                 "工单：BILL-19\nIssue: https://github.com/org/repo/issues/19?ignored=secret\n事项：#6"}]
        self.assertEqual(work_signals.user_keys(rows), ["BILL-19", "https://github.com/org/repo/issues/19"])
        self.assertIsNone(work_signals.work_key("https://secret@host/org/repo/issues/19"))

    def test_quotes_hypotheticals_and_unrecognized_hints_are_ignored(self):
        text = "如果本地测试通过就发布\n> 已发布 Beta\n```\n验收通过\n```\n- 本地测试失败。\n下一步：补跑本地测试\n下一步：发出 PRIVATE_DATA"
        claims, hints = work_signals.assistant_signals(text)
        self.assertEqual(claims, [("test", "failed")])
        self.assertEqual(hints, [("test", "补跑本地测试")])

    def test_paginated_items_drive_work_view_without_retaining_bodies(self):
        base = MIDNIGHT * 1000
        def entry(kind, item_id, **fields):
            return {"turnId": "round", "completedAtMs": base + 1000,
                    "item": {"id": item_id, "type": kind, **fields}}
        rows = [entry("userMessage", "user", content=[{"type": "text", "text": "事项：BILL-19\nPRIVATE_PROMPT"}]),
                entry("agentMessage", "assistant", phase="final_answer", text="已发布 Beta\nPRIVATE_BODY"),
                entry("agentMessage", "commentary", phase="commentary", text="验收通过"),
                entry("fileChange", "patch", status="completed", changes=[{"path": "PRIVATE_PATH"}])]
        project = source_codex.ProjectHistory(PROJECT)
        responses = [scan(metadata()), scan(), {"thread": metadata()},
                     scan({"id": "round", "startedAt": MIDNIGHT, "completedAt": MIDNIGHT + 2, "status": "completed"}),
                     scan(rows[0], cursor="items-next"), scan(*rows[1:])]
        server = Mock()
        server.call.side_effect = responses
        self.assertIsNone(source_codex.collect_project(server, project, WINDOW, True, source_codex.Limits(), include_work=True))
        report = work_report(source_codex.History([project]))
        work_items.apply_work_view(report, {})
        item = report["projects"][0]["work_items"][0]
        self.assertIn("BILL-19", item["keys"])
        self.assertEqual(item["milestones"]["beta"][0]["grade"], "Reported")
        self.assertEqual(item["milestones"]["acceptance"][0]["grade"], "Unknown")
        self.assertEqual(item["milestones"]["implementation"][0]["grade"], "Unknown")
        self.assertTrue(any(row["kind"] == "file_change" and row["grade"] == "Verified" for row in item["evidence"]))
        self.assertNotIn("PRIVATE_", json.dumps(report))


class WorkItemTests(unittest.TestCase):
    def test_strong_match_does_not_bridge_conflicting_or_weak_titles(self):
        history = fixture_history()
        history.projects.extend(fixture_history(OTHER).projects)
        report = work_report(history)
        work_items.apply_work_view(report, {})
        for project in report["projects"]:
            items = project["work_items"]
            self.assertEqual(len(items), 4)
            matched = next(item for item in items if len(item["anchors"]) == 2)
            self.assertEqual(set(matched["keys"]), {"BILL-19"})
            self.assertEqual(matched["milestones"]["test"][0]["outcome"], "conflict")
            self.assertEqual(matched["milestones"]["beta"][0]["grade"], "Reported")
            self.assertEqual(matched["milestones"]["acceptance"][0]["grade"], "Unknown")
            self.assertEqual(len(matched["follow_up"]), 1)
            self.assertTrue(any(item["grouping"] == "ambiguous" for item in items))
            self.assertTrue(all(hint["grade"] == "Inferred" for hint in project["merge_suggestions"]))
        self.assertFalse({item["id"] for item in report["projects"][0]["work_items"]} &
                         {item["id"] for item in report["projects"][1]["work_items"]})

    def test_partial_item_pages_disable_automatic_grouping_for_that_turn(self):
        history = fixture_history()
        history.projects[0].turns[1]["signals_complete"] = False
        report = work_report(history)
        work_items.apply_work_view(report, {})
        self.assertEqual(len(report["projects"][0]["work_items"]), 5)

    def test_cli_editing_survives_regeneration_and_undo_keeps_scope_distinct(self):
        history = fixture_history()
        with TemporaryDirectory() as scratch:
            db = str(Path(scratch) / "fixture.sqlite3")
            def cli(*tail):
                with redirect_stdout(StringIO()) as output:
                    self.assertEqual(main(["--db", db, *tail]), 0)
                return output.getvalue()
            def get(command):
                return json.loads(cli(command, "--project", PROJECT, "--work-items", "--format", "json"))["projects"][0]["work_items"]
            correct = ("correct", "--project", PROJECT)
            with (patch("work_memory.__main__.time_ns", return_value=AS_OF * 1_000_000),
                  patch("work_memory.__main__.collect", return_value=history)):
                before = get("review")
                linked = next(item for item in before if len(item["anchors"]) == 2)
                moved = linked["anchors"][0]["id"]
                other = next(item for item in before if set(item["keys"]) == {"BILL-23"})
                cli(*correct, "split", "--item", linked["id"], "--anchor", moved, "--title", "单独核对")
                after_split = get("review")
                split = next(item for item in after_split if item["title"] == "单独核对")
                self.assertEqual(len(after_split), 5)
                cli(*correct, "merge", "--into", split["id"], "--from", other["id"])
                cli(*correct, "confirm", "--anchor", moved, "--milestone", "beta", "--outcome", "failed", "--scope", "build-41/qa")
                cli(*correct, "confirm", "--anchor", moved, "--milestone", "beta", "--outcome", "success", "--scope", "build-42/qa")
                after = next(item for item in get("cached") if item["id"] == split["id"])
                confirms = {row["scope"]: row["outcome"] for row in after["milestones"]["beta"] if row["grade"] == "UserConfirmed"}
                self.assertEqual(confirms, {"build-41/qa": "failed", "build-42/qa": "success"})
                self.assertEqual(len(after["anchors"]), 2)
                self.assertEqual(after["aliases"], [other["id"]])
                for _ in range(4):
                    cli(*correct, "undo")
                self.assertEqual(get("cached"), before)
                log = json.loads(cli(*correct, "history"))
                self.assertEqual(len(log), 4)
                self.assertTrue(all(row["undone"] for row in log))

    def test_v1_cache_migrates_without_changing_existing_snapshot_key(self):
        with TemporaryDirectory() as scratch:
            filename = Path(scratch) / "v1.sqlite3"
            key = store.snapshot_key("original", [PROJECT], WINDOW, False)
            with closing(sqlite3.connect(filename)) as previous, previous:
                for statement in store.SCHEMA:
                    previous.execute(statement)
                previous.execute(f"PRAGMA application_id = {store.APP_ID}")
                previous.execute("PRAGMA user_version = 1")
                previous.execute("INSERT INTO snapshots VALUES (?, ?, ?)", (key, AS_OF, '{"original": true}'))
            with store.Store(filename) as current:
                self.assertEqual(current.cached(key, 0), {"original": True})
                self.assertNotEqual(key, store.snapshot_key("original", [PROJECT], WINDOW, False, include_work=True))
                self.assertEqual(current.db.execute("PRAGMA user_version").fetchone()[0], store.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
