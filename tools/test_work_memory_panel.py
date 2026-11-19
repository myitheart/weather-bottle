from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, get_ident
from time import monotonic, sleep, time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings, Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import app as shell
from codex_links import open_codex_thread
from test_work_memory_items import WINDOW, fixture_history, work_report
from work_memory.service import ReviewResult, read_review
from work_memory.store import Store
from work_memory.work_items import apply_work_view
from work_memory_panel import PROJECTS_SETTING, ROLE, WorkMemoryPanel, load_panel_review


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.project = self.root / "示例项目"
        self.project.mkdir()
        self.settings = QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("pearl_reduced_motion", True)
        self.calls = []
        self.snapshots = {}
        self.started, self.release = Event(), Event()
        self.block = False
        self.fixture = fixture_history(str(self.project))
        self.factory = Mock(side_effect=lambda bottle: WorkMemoryPanel(
            bottle, loader=self.load, database=self.root / "review.sqlite3"))
        patches = (patch.object(shell, "QSettings", return_value=self.settings), patch.object(shell, "read_pin", return_value=None),
                   patch.object(shell, "read_scope", return_value="project"), patch.object(shell, "WorkMemoryPanel", self.factory),
                   patch.object(shell.WeatherBottle, "refresh_weather"), patch.object(shell.WeatherBottle, "poll_activity"),
                   patch("activity_panel.CodexThreadNames.fetch"), patch("quick_panel.QuickPanel.desktop_keys", return_value=set()),
                   patch.object(shell.QSystemTrayIcon, "isSystemTrayAvailable", return_value=False))
        for setup in patches:
            setup.start()
            self.addCleanup(setup.stop)
        self.bottle = shell.WeatherBottle()
        self.addCleanup(self.dispose)
        self.bottle.show()
        self.bottle.timer.stop()
        self.bottle.fold = 0.
        self.bottle.shape = "orb"
        self.bottle.resize(42, 42)

    def dispose(self):
        self.release.set()
        self.bottle.hide()
        QThreadPool.globalInstance().waitForDone(4000)
        self.qt.processEvents()
        self.bottle.deleteLater()
        QTest.qWait(10)

    def load(self, database, paths, period, action, cancel, correction):
        self.calls.append((tuple(paths), period, action, get_ident(), cancel))
        if action == "cached":
            saved = deepcopy(self.snapshots.get((tuple(paths), period)))
            if saved:
                saved.report.update(mode="cached", cache="hit")
            return saved
        if self.block and action == "review":
            self.started.set()
            self.release.wait(3)
        if action == "edit":
            return self.real_loader(database, paths, period, action, cancel, correction)
        report = work_report(self.fixture)
        apply_work_view(report, {})
        report.update(cache="saved")
        result = ReviewResult(report, "fixture", self.fixture.namespace, 0, WINDOW)
        if not cancel.is_set():
            self.snapshots.setdefault((tuple(paths), period), deepcopy(result))
        return result

    def real_loader(self, database, paths, period, action, cancel, correction):
        def read(*args, **kwargs):
            if kwargs.get("as_of") is None:
                kwargs["as_of"] = WINDOW.as_of
            return read_review(*args, **kwargs, collector=lambda *_args, **_kwargs: self.fixture)
        with patch("work_memory_panel.read_review", side_effect=read):
            return load_panel_review(database, paths, period, action, cancel, correction)

    def wait_until(self, predicate):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(10)
            sleep(.005)
        panel = self.bottle.work_memory_panel
        state = (panel.isVisible(), panel.busy_action(), panel.token, ascii(panel.status.text())) if panel else None
        self.fail(f"Qt condition did not complete. State {state}, calls {[row[2] for row in self.calls]}")

    def show_scope(self):
        self.bottle.toggle_work_memory()
        panel = self.bottle.work_memory_panel
        self.show_records(panel)
        panel.add_project(str(self.project))
        self.wait_until(lambda: not panel.busy())
        return panel

    @staticmethod
    def show_records(panel):
        QTest.mouseClick(panel.record_tab, Qt.MouseButton.LeftButton)

    def generate(self, panel):
        QTest.mouseClick(panel.generate, Qt.MouseButton.LeftButton)
        self.wait_until(lambda: panel.result is not None and not panel.busy())

    def anchor_under(self, project, *, linked=False):
        panel = self.bottle.work_memory_panel
        for index in range(project.childCount()):
            item = project.child(index)
            data = item.data(0, ROLE)
            if data["kind"] != "item" or (linked and len(panel.by_item[data["item"]]["anchors"]) != 2):
                continue
            item.setExpanded(True)
            for child in range(item.childCount()):
                anchor = item.child(child)
                if anchor.data(0, ROLE)["kind"] == "anchor":
                    return anchor
        self.fail("Expected an anchor under a visible item")

    def test_idle_pearl_opens_review_and_only_generate_scans(self):
        self.assertIsNone(self.bottle.work_memory_panel)
        self.factory.assert_not_called()
        QTest.mouseClick(self.bottle, Qt.MouseButton.LeftButton)
        self.assertEqual(self.bottle.activity_panel.mode, "quick")
        QTest.mouseClick(self.bottle.activity_panel.work_review, Qt.MouseButton.LeftButton)
        panel = self.bottle.work_memory_panel
        self.assertTrue(panel.isVisible())
        self.show_records(panel)
        self.assertFalse(panel.generate.isEnabled())
        self.assertFalse(self.calls)
        QTest.mouseClick(panel.add_button, Qt.MouseButton.LeftButton)
        self.assertIsNotNone(panel.dialog)
        panel.dialog.fileSelected.emit(str(self.project))
        panel.dialog.reject()
        self.wait_until(lambda: not panel.busy())
        self.assertEqual([row[2] for row in self.calls], ["cached"])
        self.assertEqual(self.settings.value(PROJECTS_SETTING, [], type=list), [str(self.project)])
        self.generate(panel)
        self.assertNotEqual(self.calls[-1][3], get_ident())
        self.assertEqual(self.calls[-1][:3], ((str(self.project),), "today", "review"))
        self.assertTrue(panel.tree.topLevelItem(0).isExpanded())
        panel.remove_project()
        self.assertFalse(panel.generate.isEnabled())
        self.assertEqual(panel.tree.topLevelItemCount(), 0)

    def test_date_change_and_cancel_ignore_late_worker_results(self):
        panel = self.show_scope()
        self.block = True
        QTest.mouseClick(panel.generate, Qt.MouseButton.LeftButton)
        self.wait_until(self.started.is_set)
        QTest.mouseClick(panel.range_buttons.buttons()[1], Qt.MouseButton.LeftButton)
        self.assertEqual(panel.period, "yesterday")
        self.assertTrue(next(row[-1] for row in self.calls if row[2] == "review").is_set())
        self.release.set()
        self.wait_until(lambda: panel.job is None)
        self.assertIsNone(panel.result)
        self.block = False
        self.generate(panel)
        self.assertEqual(self.calls[-1][1], "yesterday")
        self.release.clear()
        self.started.clear()
        self.block = True
        QTest.mouseClick(panel.generate, Qt.MouseButton.LeftButton)
        self.wait_until(self.started.is_set)
        old = panel.result
        QTest.mouseClick(panel.generate, Qt.MouseButton.LeftButton)
        self.assertIn("已取消", panel.status.text())
        self.release.set()
        self.wait_until(lambda: panel.job is None)
        self.assertIs(panel.result, old)

    def test_expand_and_copy_then_open_source_without_reviewing_activity(self):
        panel = self.show_scope()
        self.generate(panel)
        root = panel.tree.topLevelItem(0)
        more = next(root.child(i) for i in range(root.childCount()) if root.child(i).data(0, ROLE)["kind"] == "more")
        more.setExpanded(True)
        self.assertGreater(more.childCount(), 0)
        anchor = self.anchor_under(root)
        panel.tree.setCurrentItem(anchor)
        ref = anchor.data(0, ROLE)["source"]
        self.bottle.visible_pin = {"thread": ref["thread_id"], "state": "ended"}
        with patch("work_memory_panel.open_codex_thread", side_effect=(False, True)) as navigate:
            QTest.mouseClick(panel.open_button, Qt.MouseButton.LeftButton)
            self.assertIn("无法打开", panel.status.text())
            clipboard = Mock()
            with patch.object(QApplication, "clipboard", return_value=clipboard):
                QTest.mouseClick(panel.copy_button, Qt.MouseButton.LeftButton)
            self.assertIn(ref["turn_id"], clipboard.setText.call_args.args[0])
            QTest.mouseClick(panel.open_button, Qt.MouseButton.LeftButton)
            self.assertFalse(panel.isVisible())
            navigate.assert_called_with(ref["thread_id"])
        self.assertEqual(self.bottle.visible_pin["thread"], ref["thread_id"])
        self.assertFalse(self.bottle.reviewed_activities)
        self.bottle.toggle_work_memory()
        self.assertTrue(panel.isVisible())
        self.wait_until(lambda: not panel.busy())
        self.assertEqual(panel.tree.currentItem().data(0, ROLE), anchor.data(0, ROLE))
        QTest.keyClick(panel, Qt.Key.Key_Escape)
        self.assertFalse(panel.isVisible())

    def test_classic_and_focus_entries_and_reminder_priority(self):
        self.bottle.orb_action.setChecked(False)
        self.bottle.expand_now()
        QTest.mouseClick(self.bottle, Qt.MouseButton.LeftButton, pos=self.bottle.cap_center())
        self.assertTrue(self.bottle.quick_panel.isVisible())
        self.wait_until(lambda: self.bottle.quick_panel.review_button.isVisible())
        QTest.mouseClick(self.bottle.quick_panel.review_button, Qt.MouseButton.LeftButton)
        self.wait_until(self.bottle.work_memory_visible)
        panel = self.bottle.work_memory_panel
        self.bottle.reminders.add("自测提醒", int(time()) - 1)
        self.bottle.show_due_notice()
        self.assertFalse(panel.isVisible())
        self.assertTrue(self.bottle.focus_capsule.isVisible())
        self.bottle.reminders.remove(self.bottle.focus_capsule.reminder_id)
        self.bottle.focus_capsule.hide()
        self.bottle.orb_action.setChecked(True)
        self.bottle.focus.start("focus", 60)
        self.bottle.toggle_activity_panel()
        self.assertEqual(self.bottle.activity_panel.mode, "focus")
        QTest.mouseClick(self.bottle.activity_panel.work_review, Qt.MouseButton.LeftButton)
        self.assertTrue(panel.isVisible())
        self.bottle.focus.deadline = time() - 1
        self.bottle.show_due_notice()
        self.assertEqual(self.bottle.focus.phase, "focus_done")
        self.assertFalse(panel.isVisible())

    def test_bounds_theme_and_external_dismiss(self):
        panel = self.show_scope()
        area = self.bottle.screen().availableGeometry()
        for appearance in ("light", "dark"):
            self.bottle.change_appearance(appearance)
            for corner in (area.topLeft(), area.topRight(), area.bottomLeft(), area.bottomRight()):
                self.bottle.move(corner)
                panel.place()
                self.assertTrue(area.contains(panel.geometry()), (area, panel.geometry()))
        outside = QWidget()
        outside.resize(20, 20)
        outside.move(area.topLeft())
        outside.show()
        QTest.mouseClick(outside, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
        self.assertFalse(panel.isVisible())
        outside.close()
        self.bottle.toggle_work_memory()
        self.bottle.hide()
        self.assertFalse(panel.isVisible())

    def test_confirm_and_undo_use_the_saved_snapshot_without_app_server(self):
        panel = self.show_scope()
        panel.loader = self.real_loader
        self.generate(panel)
        anchor = self.anchor_under(panel.tree.topLevelItem(0))
        panel.tree.setCurrentItem(anchor)
        panel.confirm(anchor.data(0, ROLE))
        dialog = panel.dialog
        self.assertFalse(dialog.primary.isEnabled())
        self.wait_until(lambda: dialog.panel.isVisible())
        dialog.scope.setText("build-42 / QA")
        QTest.mouseClick(dialog.primary, Qt.MouseButton.LeftButton)
        self.wait_until(lambda: panel.dialog is None and not panel.busy())
        records = [record for view in panel.result.report["projects"] for item in view["work_items"] for record in item["evidence"]]
        self.assertTrue(any(row["grade"] == "UserConfirmed" and row["scope"] == "build-42 / QA" for row in records))
        panel.edit(str(self.project), "undo")
        self.wait_until(lambda: not panel.busy())
        records = [record for view in panel.result.report["projects"] for item in view["work_items"] for record in item["evidence"]]
        self.assertFalse(any(row["grade"] == "UserConfirmed" for row in records))

    def test_activity_entry_and_drag_close_the_review(self):
        self.bottle.activity = {"id": "fixture", "thread": "thread-a", "state": "running"}
        self.bottle.toggle_activity_panel()
        self.assertEqual(self.bottle.activity_panel.mode, "activities")
        QTest.mouseClick(self.bottle.activity_panel.work_review, Qt.MouseButton.LeftButton)
        self.assertTrue(self.bottle.work_memory_visible())
        QTest.mousePress(self.bottle, Qt.MouseButton.LeftButton, pos=QPoint(3, 3))
        QTest.mouseMove(self.bottle, QPoint(30, 26))
        QTest.mouseRelease(self.bottle, Qt.MouseButton.LeftButton, pos=QPoint(30, 26))
        self.assertFalse(self.bottle.work_memory_visible())

    def test_confirmed_clear_removes_snapshot_and_retains_directory_selection(self):
        panel = self.show_scope()
        panel.loader = self.real_loader
        self.generate(panel)
        panel.scope_toggle.setChecked(True)
        QTest.mouseClick(panel.clear_button, Qt.MouseButton.LeftButton)
        dialog = panel.dialog
        self.assertIsNotNone(dialog)
        self.wait_until(lambda: dialog.panel.isVisible())
        QTest.mouseClick(dialog.primary, Qt.MouseButton.LeftButton)
        self.wait_until(lambda: panel.dialog is None and not panel.busy())
        self.assertIn("已清除", panel.status.text())
        self.assertIsNone(panel.result)
        self.assertEqual(panel.projects, [str(self.project)])
        with patch("codex_links.QDesktopServices.openUrl", return_value=True) as dispatch:
            self.assertFalse(open_codex_thread("../arbitrary"))
            self.assertTrue(open_codex_thread("thread-a"))
        self.assertEqual(dispatch.call_args.args[0].toString(), "codex://threads/thread-a")

    def test_merge_and_split_from_the_correction_menu(self):
        panel = self.show_scope()
        panel.loader = self.real_loader
        self.generate(panel)
        root = panel.tree.topLevelItem(0)
        root.child(0).setSelected(True)
        root.child(1).setSelected(True)
        QTest.mouseClick(panel.edit_button, Qt.MouseButton.LeftButton)
        merge = next(action for action in panel.edit_menu.actions() if "并入" in action.text())
        merge.trigger()
        panel.edit_menu.hide()
        self.wait_until(lambda: not panel.busy())
        items = panel.result.report["projects"][0]["work_items"]
        self.assertEqual(len(items), 3)
        merged = next(item for item in items if item["grouping"] == "manual")
        root = panel.tree.topLevelItem(0)
        nodes = [root.child(i) for i in range(root.childCount())]
        for node in nodes:
            if node.data(0, ROLE)["kind"] == "more":
                node.setExpanded(True)
                nodes.extend(node.child(i) for i in range(node.childCount()))
        merged_node = next(node for node in nodes if node.data(0, ROLE).get("item") == merged["id"])
        merged_node.setExpanded(True)
        anchor = next(merged_node.child(i) for i in range(merged_node.childCount())
                      if merged_node.child(i).data(0, ROLE)["kind"] == "anchor")
        panel.tree.setCurrentItem(anchor)
        QTest.mouseClick(panel.edit_button, Qt.MouseButton.LeftButton)
        split = next(action for action in panel.edit_menu.actions() if "拆为" in action.text())
        split.trigger()
        panel.edit_menu.hide()
        self.wait_until(lambda: not panel.busy())
        self.assertEqual(len(panel.result.report["projects"][0]["work_items"]), 4)

    def test_view_previous_can_restore_complete_result_after_partial_read(self):
        panel = self.show_scope()
        self.generate(panel)
        full = panel.result
        original = panel.loader

        def partial(*args):
            result = original(*args)
            if args[3] == "review":
                result.report.update(status="partial", cache="unchanged")
            return result

        panel.loader = partial
        QTest.mouseClick(panel.generate, Qt.MouseButton.LeftButton)
        self.wait_until(lambda: not panel.busy())
        self.assertEqual(panel.result.report["status"], "partial")
        self.assertTrue(panel.previous_button.isVisible())
        QTest.mouseClick(panel.previous_button, Qt.MouseButton.LeftButton)
        self.wait_until(lambda: not panel.busy())
        self.assertEqual(panel.result.report["projects"], full.report["projects"])
        self.assertEqual(panel.result.report["cache"], "hit")

    def test_reopen_requires_current_scope_before_showing_old_sources(self):
        panel = self.show_scope()
        panel.loader = self.real_loader
        self.generate(panel)
        selected = self.anchor_under(panel.tree.topLevelItem(0))
        panel.tree.setCurrentItem(selected)
        panel.hide()
        with Store(panel.database) as database:
            database.set_excluded([str(self.project)], True)
        self.bottle.toggle_work_memory()
        self.assertTrue(panel.checking_cache)
        self.assertFalse(panel.tree.isVisible())
        self.assertFalse(panel.open_button.isEnabled())
        self.wait_until(lambda: not panel.busy())
        self.assertIn("已排除", panel.status.text())
        self.assertIsNone(panel.result)
        self.assertEqual(panel.tree.topLevelItemCount(), 0)

    def test_date_switch_checks_disk_even_when_the_range_was_viewed_before(self):
        panel = self.show_scope()
        panel.loader = self.real_loader
        self.generate(panel)
        QTest.mouseClick(panel.range_buttons.buttons()[1], Qt.MouseButton.LeftButton)
        self.wait_until(lambda: not panel.busy())
        with Store(panel.database) as database:
            database.clear([str(self.project)])
        QTest.mouseClick(panel.range_buttons.buttons()[0], Qt.MouseButton.LeftButton)
        self.assertTrue(panel.checking_cache)
        self.wait_until(lambda: not panel.busy())
        self.assertIsNone(panel.result)

    def test_animated_open_completes_and_escape_stops_the_watcher(self):
        self.bottle.reduced_motion = False
        self.bottle.toggle_work_memory()
        panel = self.bottle.work_memory_panel
        self.assertTrue(panel.isVisible())
        self.wait_until(lambda: panel.content.isVisible() and panel.progress == 1.)
        self.assertTrue(panel.watch.isActive())
        QTest.keyClick(panel, Qt.Key.Key_Escape)
        self.assertFalse(panel.isVisible())
        self.assertFalse(panel.watch.isActive())


if __name__ == "__main__":
    unittest.main()
