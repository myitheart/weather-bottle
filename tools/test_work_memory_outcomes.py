"""Outcomes rules, request boundaries, persistence, and desktop review interactions."""

from collections import Counter
from contextlib import closing
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import MagicMock, Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit

import test_work_memory_panel as desktop
from test_work_memory_review import metadata
from work_memory import outcome_signals, summary
from work_memory.codex_rpc import Cancelled
from work_memory.outcome_service import load_outcomes
from work_memory.source_codex import History, ProjectHistory, decode_session, source_namespace
from work_memory.store import AI_SCHEMA, APP_ID, SCHEMA, WORK_SCHEMA, Store, StoreError
from work_memory_panel import ROLE


def sample_history(paths, window, **_):
    path, = paths
    p = ProjectHistory(path, finished=True)
    p.listings = {name: {"status": "complete", "pages": 1, "chats": 3} for name in ("ordinary", "archived")}
    now = window.start + 6000

    def add(chat, turn, *, title="", signals=(), key=None, start=None, end=None):
        if chat not in p.sessions:
            p.sessions[chat] = dict(decode_session(metadata(path, chat), path), title=title, archived=chat == "thread-fix")
        rows = [dict(signal, id=f"{turn}-{index}", start=None, end=now + index)
                for index, signal in enumerate(signals)]
        if key:
            rows.append(dict(id=f"{turn}-key", start=now, end=None, keys=[key]))
        p.turns.append(dict(id=turn, thread_id=chat, start=now if start is None else start, end=now+10 if end is None else end,
                            status="completed", signals=rows, signals_complete=True))

    add("thread-orders", "turn-settings", title="订单流程开发", key="PAY-24",
        signals=[{"intent": "新增订单列表筛选"}, {"changed_files": 2, "file_names": ["orders.py", "filters.py"]}])
    add("thread-orders", "turn-tests", key="PAY-24",
        signals=[{"test_result": {"runner": "unittest", "passed": 12}}])
    add("thread-fix", "turn-duplicate", title="修复订单重复提交",
        signals=[{"changed_files": 1, "file_names": ["orders.py"]}])
    add("thread-check", "turn-tests-only", title="测试订单接口",
        signals=[{"test_result": {"runner": "pytest", "passed": 8}}])
    add("thread-check", "turn-next", title="订单导出",
        signals=[{"claims": [("beta", "success"), ("test", "success")]},
                 {"claims": [("test", "failed")], "hints": [("test", "补跑导出权限回归测试")]}])
    add("thread-check", "turn-process-only")
    if window.start:
        add("thread-check", "turn-prev", start=window.start - 30000, end=window.start - 3)
    p.commands.append({"id": "command-only", "turn_id": "turn-process-only", "thread_id": "thread-check",
                       "start": now, "end": now+1, "exit_code": 0})
    p.chats_examined = len(p.sessions)
    return History([p], source_namespace())


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.paths = [str(self.root / "outcomes-project")]
        self.day = date.today() - timedelta(days=1)
        self.db = self.root / "outcome.sqlite3"
        self.call = Mock(side_effect=sample_history)
        self.cancel = Event()

    def run_action(self, action="generate", payload=None, *, model_request=None, day=None, paths=None):
        options = dict(collector=self.call)
        if model_request is not None:
            options["model_request"] = model_request
        return load_outcomes(self.db, paths or self.paths, day or self.day, action, self.cancel, payload, **options)

    def test_measurable_evidence_and_conflicts_are_distinct(self):
        rows = self.run_action().document["rows"]
        self.assertEqual(Counter(r["category"] for r in rows), dict(feature=1, fix=1, validation=1, pending=1))
        feature, fix, validation, pending = (next(r for r in rows if r["category"] == k) for k in
                                             ("feature", "fix", "validation", "pending"))
        self.assertEqual(feature["title"], "新增订单列表筛选")
        self.assertEqual({e["source"]["turn_id"] for e in feature["refs"]}, {"turn-settings", "turn-tests"})
        self.assertIn("业务结果待核实", feature["summary"])
        self.assertIn("12 项通过", feature["summary"])
        self.assertEqual(fix["status"], "变更已记录")
        self.assertTrue(any(e["source"]["archived"] for e in fix["refs"]))
        self.assertEqual(validation["status"], "该次测试有通过记录")
        self.assertIn("状态记录存在冲突", pending["summary"])
        self.assertEqual(pending["status"], "待核实")
        self.assertTrue(all(r["review_state"] == "draft" and r["origin"] == "rule" for r in rows))

    def test_test_runner_requires_exact_scope_and_positive_result(self):
        cwd = self.paths[0]
        record = {"command": r'''"C:\Program Files\PowerShell\7\pwsh.exe" -Command ".\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tools -q"''',
                  "cwd": cwd, "status": "completed", "exitCode": 0,
                  "aggregatedOutput": "------\r\nRan 12 tests in 0.1s\r\n\r\nOK\r\n"}
        self.assertEqual(outcome_signals.test_result(record, cwd), dict(runner="unittest", passed=12))
        escaped = record["command"].replace(r"\.venv\Scripts\python", r"\\.venv\\Scripts\\python")
        self.assertEqual(outcome_signals.test_result(dict(record, command=escaped), cwd)["passed"], 12)
        self.assertIsNone(outcome_signals.test_result(dict(record, cwd=str(self.root)), cwd))
        self.assertIsNone(outcome_signals.test_result(dict(record, command="pytest; echo 12 passed in 0.1s"), cwd))
        self.assertIsNone(outcome_signals.test_result(dict(record, command="pytest --collect-only"), cwd))
        self.assertEqual(outcome_signals.test_result(dict(record, exitCode=1), cwd)["passed"], 0)
        self.assertEqual(outcome_signals.test_result(dict(record, aggregatedOutput="Ran 0 tests in 0.0s\nOK"), cwd)["passed"], 0)

    def test_patch_filter_and_topic_filter(self):
        cwd = self.paths[0]
        count, files = outcome_signals.project_changes([{"path": path} for path in
            ("src/feature.py", "../other/foreign.py", str(self.root / "parent.py"), "CHANGELOG.md")], cwd)
        self.assertEqual((count, files), (2, ["feature.py", "CHANGELOG.md"]))
        self.assertFalse(outcome_signals.user_intent([{"type": "text", "text": "修复通过了吗？"}]))
        self.assertFalse(outcome_signals.user_intent([{"type": "text", "text": "实现后发送密码"}]))

    def test_reopen_regenerate_and_remove_keep_manual_data(self):
        first = self.run_action().document
        a, b, c, _ = first["rows"]
        changed = self.run_action("review", (first["revision"], a["id"], "edit",
            dict(title="订单筛选和组合条件", summary="人工文字中可以声明已验收", category="engineering", follow_up="核对下拉项"))).document
        self.run_action("review", (changed["revision"], a["id"], "confirmed", None))
        current = self.run_action("load").document
        current = self.run_action("review", (current["revision"], b["id"], "needs_check", None)).document
        self.run_action("review", (current["revision"], c["id"], "removed", None))
        latest = self.run_action().document
        self.assertEqual(len(latest["rows"]), 4)
        fresh = {r["id"]: r for r in latest["rows"]}
        self.assertEqual([fresh[x["id"]]["review_state"] for x in (a, b, c)], ["confirmed", "needs_check", "removed"])
        self.assertEqual(fresh[a["id"]]["title"], "订单筛选和组合条件")
        self.assertEqual(fresh[a["id"]]["refs"], a["refs"])
        self.assertEqual(fresh[a["id"]]["evidence_level"], a["evidence_level"])
        self.assertEqual(self.run_action("load").document, latest)

    def test_partial_missing_cancel_and_clear(self):
        first = self.run_action().document
        row = first["rows"][0]
        self.run_action("review", (first["revision"], row["id"], "confirmed", None))

        def sparse(paths, window, **kwargs):
            history = sample_history(paths, window, **kwargs)
            project = history.projects[0]
            project.turns.clear()
            project.commands.clear()
            return history

        def partial(*args, **kwargs):
            history = sparse(*args, **kwargs)
            history.projects[0].issues["read_limit"] += 1
            return history

        self.call.side_effect = partial
        kept = self.run_action().document
        self.assertEqual(len(kept["rows"]), 4)
        self.assertEqual(kept["coverage"], "partial")
        self.call.side_effect = sparse
        latest = self.run_action().document
        self.assertEqual(len(latest["rows"]), 1)
        self.assertTrue(latest["rows"][0]["source_changed"])
        self.cancel.set()
        with self.assertRaises(Cancelled):
            self.run_action()
        self.cancel.clear()
        self.assertEqual(latest, self.run_action("load").document)
        with Store(self.db) as store:
            store.clear(self.paths)
        self.assertIsNone(self.run_action("load").document)

    def test_scope_revision_future_and_day_isolation(self):
        first = self.run_action().document
        action = (first["revision"], first["rows"][0]["id"], "confirmed", None)
        self.run_action("review", action)
        with self.assertRaisesRegex(StoreError, "草稿已变化"):
            self.run_action("review", action)
        with self.assertRaises(StoreError):
            self.run_action(paths=self.paths * 2)
        self.assertIsNone(self.run_action("load", day=self.day - timedelta(days=1)).document)
        with self.assertRaisesRegex(StoreError, "未来日期"):
            self.run_action(day=date.today() + timedelta(days=1))
        with Store(self.db) as store:
            store.set_excluded(self.paths, True)
        with self.assertRaisesRegex(StoreError, "已被排除"):
            self.run_action("load")
        self.assertEqual(self.call.call_count, 1)

    def test_intraday_events_inside_cross_midnight_round(self):
        def constrained(paths, window, **opts):
            sample = sample_history(paths, window, **opts)
            p = sample.projects[0]
            p.turns = [p.turns[0]]
            p.commands = []
            p.turns[0]["start"] = window.start - 1000
            p.turns[0]["signals"][0]["end"] = window.start - 1
            return sample
        self.call.side_effect = constrained
        rows = self.run_action().document["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "engineering")
        self.assertTrue(all(e["kind"] not in {"outcome_intent", "turn_started"} for e in rows[0]["refs"]))

    def test_empty_day_is_saved_as_empty(self):
        def no_activity(paths, window, **opts):
            p = ProjectHistory(paths[0], finished=True, listings={"ordinary": {"status": "complete", "pages": 1, "chats": 0}})
            return History([p], source_namespace())
        self.call.side_effect = no_activity
        result = self.run_action().document
        self.assertEqual(result["coverage"], "empty")
        self.assertEqual(result["rows"], [])
        self.assertEqual(self.run_action("load").document, result)

    def test_real_v3_migration_preserves_existing_tables(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            for command in SCHEMA + WORK_SCHEMA + AI_SCHEMA:
                db.execute(command)
            db.execute(f"PRAGMA application_id = {APP_ID}")
            db.execute("PRAGMA user_version = 3")
            db.execute("INSERT INTO projects(path, excluded) VALUES (?, 1)", (os.path.normcase(self.paths[0]),))
        with Store(self.db) as store:
            self.assertEqual(store.selection(self.paths)[1], self.paths)
            self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], 4)
        with self.assertRaises(StoreError):
            self.run_action()

    def test_model_fallback_without_credentials_and_on_failure(self):
        model = Mock(side_effect=summary.ModelError("invalid_response"))
        with patch.dict(os.environ, OPENAI_API_KEY=""):
            result = self.run_action("preview", "test-model", model_request=model)
        self.assertIsNone(result.preview)
        self.assertIn("未配置", result.notice)
        model.assert_not_called()
        with patch.dict(os.environ, OPENAI_API_KEY="fake-test-only"):
            result = self.run_action("preview", "test-model", model_request=model)
            model.assert_not_called()
            fallback = self.run_action("ai", result.preview, model_request=model)
        self.assertEqual(result.document, fallback.document)
        self.assertIn("规则草稿", fallback.notice)
        model.assert_called_once()

    def test_model_verifies_aliases_no_new_work_and_preserves_original_evidence(self):
        with patch.dict(os.environ, OPENAI_API_KEY="fake-test-only"):
            draft = self.run_action("preview", "test-model")
            preview = draft.preview
            aliases = list(preview.mapping)
            body = json.loads(preview.body)
            self.assertFalse(body["store"])
            self.assertNotIn("orders.py", body["input"])
            self.assertNotIn("thread-orders", body["input"])
            self.assertNotIn("fake-test-only", preview.body.decode())
            self.assertNotIn(str(self.root), preview.body.decode())
            first, second, third = aliases[:3]
            foreign = next(iter(preview.mapping[first][1]))
            last_ref = next(iter(preview.mapping[third][1]))
            reply = {"outcomes": [
                {"row": first, "title": "订单筛选候选", "summary": "涉及订单列表筛选条件。", "refs": [foreign]},
                {"row": second, "title": "修复缺陷", "summary": "业务待核实。", "refs": [foreign]},
                {"row": third, "title": "缺陷已发布", "summary": "已验收。", "refs": [last_ref]},
                {"row": "foreign-row", "title": "跨项目成果", "summary": "说明", "refs": [foreign]},
            ]}
            request = Mock(return_value=(reply, {}))
            result = self.run_action("ai", preview, model_request=request)
            request.assert_called_once_with(preview.body, "fake-test-only")
            self.assertEqual(len(result.document["rows"]), len(draft.document["rows"]))
            before, after = draft.document["rows"], result.document["rows"]
            self.assertEqual([r["refs"] for r in before], [r["refs"] for r in after])
            self.assertEqual([r["status"] for r in before], [r["status"] for r in after])
            self.assertEqual(Counter(r["origin"] for r in after)["ai"], 1)
            self.assertEqual(sum(bool(r.get("model_issue")) for r in after), 2)
            self.assertEqual(sum(r["review_state"] == "needs_check" for r in after), 2)
            with self.assertRaises(StoreError):
                self.run_action("ai", preview, model_request=request)

    def test_empty_ai_payload_and_scope_change_do_not_write(self):
        with patch.dict(os.environ, OPENAI_API_KEY="fake-test-only"):
            draft = self.run_action("preview", "test-model")
            for value in ({"outcomes": []}, {"outcomes": 1}, {"bad": []}):
                result = self.run_action("ai", draft.preview, model_request=Mock(return_value=(value, {})))
                self.assertEqual(draft.document, result.document)
            with Store(self.db) as store:
                store.set_excluded(self.paths, True)
            request = Mock()
            with self.assertRaises(StoreError):
                self.run_action("ai", draft.preview, model_request=request)
            request.assert_not_called()

    def test_malformed_model_wire_json_uses_rule_snapshot(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"{unclosed"
        opener = Mock()
        opener.open.return_value = response
        with (patch.dict(os.environ, OPENAI_API_KEY="fake-test-only"),
              patch.object(summary, "build_opener", return_value=opener)):
            draft = self.run_action("preview", "test-model")
            opener.open.assert_not_called()
            result = self.run_action("ai", draft.preview)
        self.assertEqual(result.document, draft.document)
        self.assertEqual(opener.open.call_args.args[0].data, draft.preview.body)

    def test_model_failure_cannot_restore_cache_cleared_during_request(self):
        def transport_fails_after_clear(*_):
            with Store(self.db) as other:
                other.clear(self.paths)
            raise summary.ModelError("transport_error")

        with patch.dict(os.environ, OPENAI_API_KEY="fake-test-only"):
            draft = self.run_action("preview", "test-model")
            with self.assertRaisesRegex(StoreError, "缓存已改变"):
                self.run_action("ai", draft.preview, model_request=transport_fails_after_clear)
        self.assertIsNone(self.run_action("load").document)


class OutcomePanelTests(unittest.TestCase):
    def setUp(self):
        self.ui = desktop.PanelTests()
        self.ui.setUpClass()
        self.ui.setUp()
        self.addCleanup(self.ui.doCleanups)
        self.collector = Mock(side_effect=sample_history)
        self.model = Mock(return_value=({"outcomes": []}, {}))
        self.ui.bottle.toggle_work_memory()
        self.panel = self.ui.bottle.work_memory_panel
        self.pane = self.panel.outcomes
        self.pane.loader = self.loader
        self.panel.add_project(str(self.ui.project))
        self.wait()

    def loader(self, *args):
        return load_outcomes(*args, collector=self.collector, model_request=self.model)

    def click(self, widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

    def wait(self):
        self.ui.wait_until(lambda: self.pane.job is None)

    def generate(self):
        self.click(self.pane.generate)
        self.wait()
        self.assertIsNotNone(self.pane.document)

    def select(self, category):
        for index in range(self.pane.tree.topLevelItemCount()):
            node = self.pane.tree.topLevelItem(index)
            if node.data(0, ROLE)["row"]["category"] == category:
                self.pane.tree.setCurrentItem(node)
                self.pane.tree.scrollToItem(node)
                return node
        self.fail("Expected visible outcome category")

    def edit_dialog(self):
        self.click(self.pane.edit)
        self.ui.wait_until(lambda: self.panel.dialog is not None and self.panel.dialog.panel.isVisible())
        return self.panel.dialog

    def test_actual_pane_review_edit_source_and_saved_reopen(self):
        self.collector.assert_not_called()
        self.assertTrue(self.panel.showing_outcomes)
        self.generate()
        self.select("feature")
        self.click(self.pane.confirm)
        self.wait()
        self.assertEqual(self.pane.selection()[0]["review_state"], "confirmed")
        self.select("fix")
        self.click(self.pane.check)
        self.wait()
        self.assertEqual(self.pane.selection()[0]["review_state"], "needs_check")
        dialog = self.edit_dialog()
        dialog.title.setText("核对重复提交处理")
        dialog.summary.setPlainText("已调整订单提交处理，待复现验证。")
        dialog.follow.setText("补跑重复提交回归")
        self.click(dialog.primary)
        self.ui.wait_until(lambda: self.panel.dialog is None)
        self.wait()
        self.assertEqual(self.pane.selection()[0]["title"], "核对重复提交处理")
        node = self.select("feature")
        node.setExpanded(True)
        evidence = next(node.child(i) for i in range(node.childCount()) if node.child(i).data(0, ROLE))
        self.pane.tree.setCurrentItem(evidence)
        self.click(self.pane.copy_source_button)
        self.assertIn("codex://threads/thread-orders", QApplication.clipboard().text())
        with patch("work_outcomes_panel.open_codex_thread", return_value=False) as launch:
            self.click(self.pane.open_source_button)
            launch.assert_called_once_with("thread-orders")
            self.assertIn("复制来源", self.pane.status.text())
        self.select("validation")
        self.click(self.pane.remove)
        self.wait()
        self.assertEqual(self.pane.tree.topLevelItemCount(), 3)
        self.panel.hide()
        self.panel.reveal()
        self.wait()
        self.assertIn("已保存", self.pane.status.text())
        self.assertEqual(self.pane.tree.topLevelItemCount(), 3)
        self.assertEqual(self.select("feature").data(0, ROLE)["row"]["review_state"], "confirmed")
        self.click(self.panel.record_tab)
        self.assertFalse(self.panel.showing_outcomes)
        self.assertTrue(self.panel.record_tab.isChecked())

    def test_date_project_cancel_and_no_automatic_source_scan(self):
        entered, released = Event(), Event()
        self.addCleanup(released.set)

        def hold(paths, window, **kwargs):
            entered.set()
            released.wait(3)
            return sample_history(paths, window, **kwargs)
        self.collector.side_effect = hold
        self.click(self.pane.generate)
        self.ui.wait_until(entered.is_set)
        self.pane.range.setCurrentIndex(1)
        released.set()
        self.wait()
        self.assertIsNone(self.pane.document)
        self.assertEqual(self.pane.calendar.date().toPython(), date.today() - timedelta(days=1))
        self.pane.range.setCurrentIndex(2)
        self.assertTrue(self.pane.calendar.isEnabled())
        second = self.ui.root / "另一项目"
        second.mkdir()
        self.panel.add_project(str(second))
        self.pane.project.setCurrentIndex(self.pane.project.findData(str(second)))
        self.wait()
        self.assertIsNone(self.pane.document)
        self.assertEqual(self.collector.call_count, 1)
        self.generate()
        self.assertEqual(self.collector.call_args.args[0], [str(second)])
        self.click(self.panel.record_tab)
        self.panel.remove_project()  # First project leaves the authorized UI scope.
        self.click(self.panel.outcome_tab)
        self.wait()
        self.assertEqual(self.pane.project.count(), 1)

    def test_model_preview_requires_separate_explicit_click(self):
        with patch.dict(os.environ, OPENAI_API_KEY="fake-test-only", DYNAMIC_PEARL_OUTCOME_MODEL="test-model"):
            self.click(self.pane.ai)
            self.ui.wait_until(lambda: self.panel.dialog and self.panel.dialog.panel.isVisible())
            self.click(self.panel.dialog.primary)
            self.ui.wait_until(lambda: self.panel.dialog and self.panel.dialog.windowTitle() == "确认发送模型材料"
                               and self.panel.dialog.panel.isVisible())
            preview = self.panel.dialog.findChild(QPlainTextEdit)
            self.assertEqual(json.loads(preview.toPlainText())["model"], "test-model")
            self.model.assert_not_called()
            self.click(self.panel.dialog.cancel_button)
            self.ui.wait_until(lambda: self.panel.dialog is None)
            self.model.assert_not_called()
            self.click(self.pane.ai)
            self.ui.wait_until(lambda: self.panel.dialog and self.panel.dialog.panel.isVisible())
            self.click(self.panel.dialog.primary)
            self.ui.wait_until(lambda: self.panel.dialog and self.panel.dialog.windowTitle() == "确认发送模型材料"
                               and self.panel.dialog.panel.isVisible())
            self.click(self.panel.dialog.primary)
            self.ui.wait_until(lambda: self.panel.dialog is None)
            self.wait()
        self.model.assert_called_once()
        self.assertIn("继续使用", self.pane.status.text())


if __name__ == "__main__":
    unittest.main()
