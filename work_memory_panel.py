"""Non-modal local work review for the Pearl and classic bottle."""

from datetime import date
from html import escape
from pathlib import Path
import sqlite3
from threading import Event
from time import time_ns

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from codex_activity import activity_path
from codex_links import open_codex_thread
from glass_dialog import GlassButton, GlassChip, GlassDialog, GlassGlyphButton, GlassTextInput, PopupAnimation, popup_geometry
from menu import FluentMenu
from pearl_style import glass, palette, text_role, themed
from quick_panel import QuickPanel
from typography import font
from work_memory.codex_rpc import Cancelled, identifier, path_key
from work_memory.review import COVERAGE, project_label
from work_memory.service import read_review
from work_memory.store import Store, StoreError
from work_memory.time_range import PERIODS, local_time
from work_memory.work_items import CorrectionError, GRADES
from work_memory.work_signals import MILESTONES, OUTCOMES


PROJECTS_SETTING = "work_memory_projects"
ROLE = Qt.ItemDataRole.UserRole
LOADING = "正在读取本机 Codex 历史…"


def load_panel_review(database, paths, period, action, cancel, correction):
    if action == "cached" and not database.is_file():
        return None
    if action == "review":
        database.parent.mkdir(parents=True, exist_ok=True)
    with Store(database) as store:
        as_of = None
        if action == "edit":
            project, result, kind, values = correction
            as_of = result.window.as_of
            if kind == "undo":
                store.undo_work(project, result.namespace)
            else:
                store.edit_work(project, result.namespace, result.key, kind, values, time_ns() // 1_000_000)
        elif action == "clear":
            store.clear([correction])
            return None
        return read_review(store, paths, period, cached=action != "review", save=True, include_work=True,
                           cancel=cancel, as_of=as_of)


class JobSignals(QObject):
    done = Signal(int, object, str)


class ReviewJob(QRunnable):
    def __init__(self, token, loader, database, paths, period, action, correction):
        super().__init__()
        self.token = token
        self.action = action
        self.loader = loader
        self.arguments = (database, paths, period, action)
        self.correction = correction
        self.cancel = Event()
        self.signals = JobSignals()

    def run(self):
        result, error = None, ""
        if not self.cancel.is_set():
            try:
                result = self.loader(*self.arguments, self.cancel, self.correction)
            except Cancelled:
                pass
            except (StoreError, CorrectionError) as failure:
                error = str(failure)
            except (OSError, sqlite3.Error):
                error = "无法读取本机缓存。请检查目录权限，或稍后重试。"
            except Exception:
                error = "工作回顾未能完成。请重试。"
        self.signals.done.emit(self.token, result, error)


def label(text="", role="body", tint="text"):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setFont(font(role))
    text_role(widget, tint)
    return widget


def list_style():
    t = palette()
    return (
        f"QAbstractItemView {{ color: {t.text}; background: {t.control}; border: 1px solid {t.line};"
        f" border-radius: 11px; padding: 4px; outline: none; selection-color: {t.text};"
        f" selection-background-color: {t.selected}; }}"
        "QAbstractItemView::item { min-height: 29px; }"
        f"QAbstractItemView::item:selected {{ color: {t.text}; }}"
        "QScrollBar:vertical { width: 6px; background: transparent; }"
        f"QScrollBar::handle:vertical {{ min-height: 24px; border-radius: 3px; background: {t.muted}; }}"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    )


class ConfirmWorkDialog(GlassDialog):
    def __init__(self, host):
        super().__init__(host, "确认业务状态", "填写本次确认适用的版本、环境或测试范围。", "保存确认")
        self.milestone = self.combo(MILESTONES.items())
        self.outcome = self.combo((key, OUTCOMES[key]) for key in ("success", "failed", "pending"))
        self.scope = GlassTextInput()
        self.scope.setPlaceholderText("例如 build-42 / 本地订单回归")
        self.scope.setAccessibleName("适用范围")
        self.scope.setMaxLength(160)
        self.content.addWidget(self.scope)
        self.primary.setEnabled(False)
        self.scope.textChanged.connect(lambda value: self.primary.setEnabled(bool(value.strip())))

    def combo(self, entries):
        combo = QComboBox(self)
        combo.setFont(font("body"))
        combo.setMinimumHeight(30)
        themed(combo, lambda: f"color: {palette().text}; background: {palette().base};")
        for key, title in entries:
            combo.addItem(title, key)
        self.content.addWidget(combo)
        return combo

    def accept(self):
        if self.scope.text().strip():
            super().accept()


class WorkMemoryPanel(QWidget):
    def __init__(self, bottle, *, loader=load_panel_review, database=None):
        super().__init__(bottle, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.bottle = bottle
        self.loader = loader
        self.database = Path(database) if database is not None else activity_path().with_name("work-memory.sqlite3")
        self.projects = list(dict.fromkeys(bottle.settings.value(PROJECTS_SETTING, [], type=list)))[:6]
        self.projects = [path for path in self.projects if isinstance(path, str) and Path(path).is_absolute()]
        self.period = "today"
        self.display_key = None
        self.result = None
        self.previous_available = False
        self.checking_cache = False
        self.by_project = {}
        self.by_item = {}
        self.job = None
        self.pending = None
        self.token = 0
        self.dialog = None
        self.progress = 1.
        self.last_keys = set()
        self.showing_outcomes = True
        self.setWindowTitle("工作回顾")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.animation = PopupAnimation(self)
        self.animation.valueChanged.connect(self.draw_progress)
        self.animation.finished.connect(self.content_ready)
        self.watch = QTimer(self, interval=40)
        self.watch.timeout.connect(self.watch_desktop)
        self.build()

    def build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        self.content = QWidget(self)
        policy = self.content.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.content.setSizePolicy(policy)
        outer.addWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(13, 10, 13, 11)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(label("工作回顾", "panel_title"), 1)
        close = GlassGlyphButton("close", "关闭工作回顾", 26, 26)
        close.clicked.connect(self.hide)
        header.addWidget(close)
        layout.addLayout(header)

        from work_outcomes_panel import OutcomePane
        tabs = QHBoxLayout()
        self.tabs = QButtonGroup(self)
        self.outcome_tab = GlassChip("成果")
        self.record_tab = GlassChip("工作记录")
        for button in (self.outcome_tab, self.record_tab):
            self.tabs.addButton(button)
            tabs.addWidget(button, 1)
            button.clicked.connect(lambda checked, tab=button: self.select_tab(tab is self.outcome_tab) if checked else None)
        self.outcome_tab.setChecked(True)
        layout.addLayout(tabs)
        self.outcomes = OutcomePane(self)
        layout.addWidget(self.outcomes, 1)
        self.records = QWidget(self.content)
        layout.addWidget(self.records, 1)
        layout = QVBoxLayout(self.records)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        ranges = QHBoxLayout()
        self.range_buttons = QButtonGroup(self)
        for key, title in PERIODS.items():
            button = GlassChip(title)
            button.setChecked(key == self.period)
            button.clicked.connect(lambda checked, selected=key: self.choose_period(selected) if checked else None)
            self.range_buttons.addButton(button)
            ranges.addWidget(button, 1)
        layout.addLayout(ranges)

        scope = QHBoxLayout()
        self.scope_summary = label("", "hint", "muted")
        scope.addWidget(self.scope_summary, 1)
        self.scope_toggle = GlassButton("项目设置")
        self.scope_toggle.setCheckable(True)
        self.scope_toggle.toggled.connect(self.show_projects)
        scope.addWidget(self.scope_toggle)
        layout.addLayout(scope)

        self.scope_editor = QWidget(self)
        editor = QVBoxLayout(self.scope_editor)
        editor.setContentsMargins(0, 0, 0, 0)
        self.scope_list = QListWidget(self.scope_editor)
        self.scope_list.setFont(font("list_meta"))
        self.scope_list.setAccessibleName("已选工作目录")
        self.scope_list.setMaximumHeight(78)
        self.scope_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        themed(self.scope_list, list_style)
        editor.addWidget(self.scope_list)
        edits = QHBoxLayout()
        self.add_button = GlassButton("添加目录…")
        self.add_button.clicked.connect(self.pick_directory)
        self.remove_button = GlassButton("移出范围")
        self.remove_button.clicked.connect(self.remove_project)
        self.clear_button = GlassButton("清除缓存…")
        self.clear_button.clicked.connect(self.confirm_clear)
        self.scope_list.currentItemChanged.connect(lambda *_: self.update_actions())
        edits.addWidget(self.add_button, 1)
        edits.addWidget(self.remove_button, 1)
        edits.addWidget(self.clear_button, 1)
        editor.addLayout(edits)
        layout.addWidget(self.scope_editor)
        self.scope_editor.hide()

        self.status = label("", "hint", "muted")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("工作回顾状态")
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        self.previous_button = GlassButton("上次快照")
        self.previous_button.clicked.connect(self.show_previous)
        status_row.addWidget(self.previous_button)
        layout.addLayout(status_row)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(13)
        self.tree.setUniformRowHeights(True)
        self.tree.setFont(font("list_title"))
        self.tree.setAccessibleName("项目、事项与证据")
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemExpanded.connect(self.expand_node)
        self.tree.itemSelectionChanged.connect(self.update_actions)
        themed(self.tree, list_style)
        layout.addWidget(self.tree, 1)
        self.tree.hide()

        actions = QHBoxLayout()
        self.edit_button = GlassButton("纠正…")
        self.edit_button.clicked.connect(self.show_edit_menu)
        self.open_button = GlassButton("打开 Codex")
        self.open_button.clicked.connect(self.open_source)
        self.copy_button = GlassButton("复制来源")
        self.copy_button.clicked.connect(self.copy_source)
        self.generate = GlassButton("生成回顾", primary=True)
        self.generate.clicked.connect(self.generate_or_cancel)
        for widget in (self.edit_button, self.open_button, self.copy_button, self.generate):
            actions.addWidget(widget, 1)
        layout.addLayout(actions)
        self.edit_menu = FluentMenu(self)
        self.refresh_projects()
        self.update_actions()
        self.records.hide()

    def select_tab(self, outcomes):
        if self.showing_outcomes == outcomes:
            return
        self.showing_outcomes = outcomes
        (self.outcome_tab if outcomes else self.record_tab).setChecked(True)
        self.records.setVisible(not outcomes)
        self.outcomes.setVisible(outcomes)
        if outcomes:
            self.cancel_request()
            self.outcomes.sync_scope()
        else:
            self.outcomes.cancel()
            self.show_projects(self.scope_toggle.isChecked() or not self.projects)
            self.change_view(recheck=True)
        if self.isVisible():
            self.place()

    def reveal(self):
        if self.isVisible():
            return
        if self.projects and not self.showing_outcomes:
            self.checking_cache = True
            self.tree.hide()
            self.status.setText("正在核对本机缓存…")
            self.update_actions()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,
                           bool(self.bottle.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        self.show_projects(self.scope_toggle.isChecked() or not self.projects)
        self.show()
        self.raise_()
        self.place()
        QApplication.instance().installEventFilter(self)
        self.last_keys = QuickPanel.desktop_keys()
        self.watch.start()
        self.activateWindow()
        if not self.bottle.reduced_motion:
            self.content.hide()
            self.draw_progress(0.)
            self.animation.play(0., 1.)
        else:
            self.content_ready()
        if self.showing_outcomes:
            self.outcomes.sync_scope()
        else:
            self.change_view(recheck=True)

    def content_ready(self):
        self.content.show()
        self.draw_progress(1.)
        if self.showing_outcomes:
            target = self.outcomes.project if self.projects else self.outcomes.add
        else:
            target = self.generate if self.projects else self.add_button
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def draw_progress(self, amount):
        self.progress = amount
        self.update()

    def place(self):
        anchor = self.bottle.visual_geometry()
        screen = QApplication.screenAt(anchor.center()) or self.bottle.screen()
        available = screen.availableGeometry()
        margin = min(8, available.width() // 20, available.height() // 20)
        area = available.adjusted(margin, margin, -margin, -margin)
        if self.showing_outcomes:
            height = 536
        else:
            height = 570 if self.by_project else 353 if self.projects and not self.scope_editor.isHidden() else 263
        size = QSize(min(416, area.width()), min(height, area.height()))
        if self.size() != size:
            self.resize(size)
        position, _ = popup_geometry(anchor, self.size(), area)
        if position != self.pos():
            self.move(position)

    def paintEvent(self, _):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setOpacity(self.progress)
            glass(p, QRectF(self.rect()).adjusted(4, 2, -4, -4), "panel")

    def hideEvent(self, event):
        self.cancel_request()
        self.outcomes.cancel()
        self.watch.stop()
        self.animation.stop()
        self.edit_menu.hide()
        QApplication.instance().removeEventFilter(self)
        if self.dialog is not None:
            dialog, self.dialog = self.dialog, None
            dialog.hide()
            dialog.deleteLater()
        self.content.show()
        self.update_actions()
        super().hideEvent(event)

    def watch_desktop(self):
        keys = QuickPanel.desktop_keys()
        pressed, self.last_keys = keys - self.last_keys, keys
        if self.dialog is not None or self.edit_menu.isVisible():
            return
        if 27 in pressed or (pressed and not self.pointer_inside(QCursor.pos())):
            self.hide()

    def pointer_inside(self, point):
        return self.frameGeometry().contains(point) or self.bottle.frameGeometry().contains(point)

    def eventFilter(self, watched, event):
        if not self.isVisible() or self.dialog is not None or self.edit_menu.isVisible():
            return False
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.hide()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            if not self.pointer_inside(event.globalPosition().toPoint()):
                self.hide()
        return False

    def show_projects(self, visible):
        self.scope_editor.setVisible(visible)
        self.scope_toggle.setChecked(visible)
        if self.isVisible():
            self.place()

    def refresh_projects(self):
        self.scope_list.clear()
        for path in self.projects:
            item = QListWidgetItem(project_label(path), self.scope_list)
            item.setData(ROLE, path)
            item.setToolTip(escape(path))
        if self.projects:
            self.scope_list.setCurrentRow(0)
        self.scope_summary.setText(f"已选 {len(self.projects)} 个本机目录" if self.projects else "尚未选择工作目录")
        self.scope_list.setVisible(bool(self.projects))
        self.remove_button.setVisible(bool(self.projects))
        self.clear_button.setVisible(bool(self.projects))
        self.add_button.setEnabled(len(self.projects) < 6)

    def pick_directory(self):
        if self.dialog is not None:
            return
        dialog = QFileDialog(self, "选择 Codex 工作目录")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.dialog = dialog
        dialog.fileSelected.connect(self.add_project)
        dialog.finished.connect(lambda _: self.release_dialog(dialog))
        dialog.show()

    def release_dialog(self, dialog):
        if self.dialog is dialog:
            self.dialog = None
            self.last_keys = QuickPanel.desktop_keys()
        dialog.deleteLater()

    def add_project(self, value):
        path = Path(value)
        if len(self.projects) >= 6 or not path.is_absolute() or not path.is_dir():
            return
        if any(path_key(str(path)) == path_key(old) for old in self.projects):
            self.status.setText("该目录已在回顾范围内。")
            return
        self.projects.append(str(path))
        if len(self.projects) == 1:
            self.scope_toggle.setChecked(False)
        self.scope_changed()

    def remove_project(self):
        item = self.scope_list.currentItem()
        if item is not None:
            self.projects.remove(item.data(ROLE))
            self.scope_changed()

    def scope_changed(self):
        self.bottle.settings.setValue(PROJECTS_SETTING, self.projects)
        self.refresh_projects()
        if self.showing_outcomes:
            self.outcomes.sync_scope()
        else:
            self.change_view()

    def choose_period(self, period):
        if self.period != period:
            self.period = period
            self.change_view()

    def change_view(self, *, recheck=False):
        key = (date.today(), self.period, tuple(self.projects))
        changed = key != self.display_key
        if changed:
            self.cancel_request()
            self.display_key = key
            self.previous_available = False
            self.checking_cache = False
            self.render_result(None)
        if self.projects and (changed or recheck):
            self.request("cached")
        else:
            self.update_status()

    def cancel_request(self):
        self.token += 1
        self.pending = None
        if self.job is not None:
            self.job.cancel.set()

    def request(self, action, correction=None):
        self.cancel_request()
        self.checking_cache = action == "cached"
        if self.checking_cache:
            self.tree.hide()
        self.pending = (self.token, action, tuple(self.projects), self.period, correction)
        self.start_pending()
        self.update_status()

    def start_pending(self):
        if self.job is not None or self.pending is None:
            return
        token, action, paths, period, correction = self.pending
        self.pending = None
        self.job = ReviewJob(token, self.loader, self.database, paths, period, action, correction)
        self.job.signals.done.connect(self.finish_job, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(self.job)

    def finish_job(self, token, result, error):
        action = self.job.action
        self.job = None
        if token == self.token and self.isVisible():
            self.checking_cache = False
            ready = result is not None and result.report is not None
            if action == "cached":
                self.previous_available = ready
                if ready and self.same_view(result):
                    self.result = result
                    self.tree.setVisible(bool(self.by_project))
                else:
                    self.render_result(result if ready else None)
            elif action == "clear" and not error:
                self.previous_available = False
                self.render_result(None)
                error = "已清除所选项目的本机缓存。"
            elif ready:
                self.previous_available |= result.report.get("cache") in {"saved", "hit"}
                if result.report["status"] != "unavailable" or self.result is None:
                    self.render_result(result)
                else:
                    error = "本机历史暂不可用，仍显示上次快照。"
            self.update_status(error)
        self.start_pending()

    def same_view(self, result):
        previous = self.result
        return bool(previous and previous.key == result.key and previous.generation == result.generation
                    and previous.report["projects"] == result.report["projects"])

    def busy(self):
        return self.pending is not None or (self.job is not None and self.job.token == self.token)

    def busy_action(self):
        if self.pending is not None:
            return self.pending[1]
        return self.job.action if self.job is not None and self.job.token == self.token else None

    def generate_or_cancel(self):
        if self.busy():
            self.cancel_request()
            if self.checking_cache:
                self.checking_cache = self.previous_available = False
                self.render_result(None)
            self.update_status("已取消。")
        elif self.projects:
            self.request("review")

    def show_previous(self):
        if self.previous_available:
            self.request("cached")

    def update_status(self, message=""):
        if not message and self.busy():
            message = {"cached": "正在核对本机缓存…", "edit": "正在保存纠正…",
                       "clear": "正在清除本机缓存…"}.get(self.busy_action(), LOADING)
            if self.result and not self.checking_cache:
                message += " 当前显示上次结果。"
        if not message and self.result is not None:
            report = self.result.report
            generated = report["window"]["generated_at"][:16].replace("T", " ")
            excluded = report.get("excluded_projects", [])
            message = f"{COVERAGE[report['status']]} · {generated}" + (" · 上次快照" if report["mode"] == "cached" else "")
            if report["status"] == "partial":
                message += "。仅显示可读记录。"
            if excluded:
                message += f" · 已排除 {len(excluded)} 个目录"
        if not message:
            message = ("点击生成，按当前范围读取本机历史。" if self.projects else
                       "添加工作目录后手动生成，快照保存在本机。")
        self.status.setText(message)
        self.update_actions()

    def add_node(self, parent, title, kind, **data):
        node = QTreeWidgetItem(parent, [title])
        node.setData(0, ROLE, {"kind": kind, **data})
        node.setToolTip(0, escape(title))
        return node

    def render_result(self, result):
        self.result = result
        self.tree.clear()
        self.by_item.clear()
        self.by_project = {view["path"]: view for view in result.report["projects"]} if result else {}
        for path, view in self.by_project.items():
            items = view["work_items"]
            root = self.add_node(self.tree, f"{view['project']} · {len(items)} 项", "project", path=path)
            root.setFont(0, font("section_title"))
            root.setToolTip(0, escape(path))
            if not items or view["status"] == "partial":
                self.add_node(root, COVERAGE[view["status"]], "note", path=path)
            for item in items[:2]:
                self.add_item(root, path, item)
            if len(items) > 2:
                more = self.add_node(root, f"查看其余 {len(items) - 2} 项", "more", path=path)
                more.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            if view["merge_suggestions"]:
                proposals = self.add_node(root, "待核对的归并建议", "note", path=path)
                for suggestion in view["merge_suggestions"]:
                    self.add_node(proposals, suggestion["reason"], "candidate", path=path, items=suggestion["items"])
            self.add_coverage(root, path, view)
            root.setExpanded(True)
        self.tree.setVisible(bool(self.by_project))
        self.update_status()
        if self.isVisible():
            self.place()

    def add_item(self, parent, path, item):
        self.by_item[item["id"]] = item
        node = self.add_node(parent, item["title"], "item", path=path, item=item["id"])
        node.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

    def add_coverage(self, root, path, view):
        coverage = self.add_node(root, "读取范围", "note", path=path)
        for key, name in (("ordinary", "普通聊天"), ("archived", "归档聊天")):
            listing = view["listings"].get(key)
            if listing is None or not listing["pages"]:
                description = "来源未读通"
            else:
                status = "列表读完" if listing["status"] == "complete" else "列表未读完"
                description = f"{listing['chats']} 条 · {status}"
            self.add_node(coverage, f"{name} · {description}", "note", path=path)
        if not self.result.report["archive_coverage_validated"]:
            self.add_node(coverage, "当前归档入口的真实样本覆盖待核对", "note", path=path)

    def expand_node(self, node):
        data = node.data(0, ROLE)
        if node.childCount() or not data:
            return
        path = data["path"]
        if data["kind"] == "more":
            for item in self.by_project[path]["work_items"][2:]:
                self.add_item(node, path, item)
        elif data["kind"] == "item":
            self.add_item_details(node, path, self.by_item[data["item"]])

    def add_item_details(self, parent, path, item):
        found = False
        for milestone, states in item["milestones"].items():
            for state in states:
                if state["grade"] != "Unknown":
                    text = f"{MILESTONES[milestone]} · {OUTCOMES[state['outcome']]} · {GRADES[state['grade']]}"
                    if state.get("scope"):
                        text += f" · {state['scope']}"
                    self.add_node(parent, text, "note", path=path)
                    found = True
        if not found:
            self.add_node(parent, "业务状态待核实", "note", path=path)
        for anchor in item["anchors"]:
            ref = anchor["source"]
            source_type = "Codex CLI" if ref["source"] == "exec" else "Codex 聊天"
            if ref["archived"]:
                source_type += "（归档）"
            self.add_node(parent, f"{source_type} · {ref['title']}", "anchor", path=path,
                          item=item["id"], anchor=anchor["id"], source=ref)
        evidence = self.add_node(parent, f"记录与线索 · {len(item['evidence'])} 条", "note", path=path)
        for record in item["evidence"]:
            when = local_time(record["at_ms"])[:16].replace("T", " ") if record["at_ms"] is not None else "时间待确认"
            prefix = "下一步 · " if record["kind"] == "follow_up" else ""
            self.add_node(evidence, f"{prefix}{record['label']} · {GRADES[record['grade']]} · {when}",
                          "evidence", path=path, source=record["source"], when=when)

    def selection(self):
        if self.checking_cache:
            return []
        return [node.data(0, ROLE) for node in self.tree.selectedItems() if node.data(0, ROLE)]

    def selected_source(self):
        rows = self.selection()
        return rows[0].get("source") if len(rows) == 1 else None

    def open_source(self):
        ref = self.selected_source()
        if ref:
            if open_codex_thread(ref.get("thread_id")):
                self.hide()
            else:
                self.status.setText("无法打开 Codex，可复制来源后在桌面端定位。")

    def copy_source(self):
        ref = self.selected_source()
        if ref and identifier(ref.get("thread_id")):
            row = self.selection()[0]
            fields = [ref["title"], row.get("when", ""), f"codex://threads/{ref['thread_id']}", f"回合 {ref['turn_id']}"]
            if ref.get("item_id"):
                fields.append(f"条目 {ref['item_id']}")
            QApplication.clipboard().setText("\n".join(field for field in fields if field))
            self.status.setText("已复制来源定位。")

    def update_actions(self):
        action = self.busy_action()
        writing = action in {"edit", "clear"}
        self.generate.setEnabled(bool(self.projects) and not writing)
        self.generate.setText("处理中…" if writing else "取消读取" if action else "重新生成" if self.result else "生成回顾")
        complete = self.result is not None and self.result.report.get("cache") in {"saved", "hit"}
        self.previous_button.setVisible(self.previous_available and not complete and not writing and not self.checking_cache)
        selected_project = self.scope_list.currentItem() is not None
        self.remove_button.setEnabled(selected_project and not writing)
        self.clear_button.setEnabled(selected_project and not self.busy())
        source = self.selected_source()
        valid = bool(source and identifier(source.get("thread_id")))
        for button in (self.edit_button, self.open_button, self.copy_button):
            button.setVisible(self.result is not None)
        self.open_button.setEnabled(valid)
        self.copy_button.setEnabled(valid)
        self.edit_button.setEnabled(bool(self.selection() and self.result and not self.busy() and
                                         self.result.report.get("cache") in {"saved", "hit"}))

    def show_edit_menu(self):
        if not self.edit_button.isEnabled():
            return
        rows = self.selection()
        path = rows[0]["path"]
        self.edit_menu.clear()
        if all(row["path"] == path for row in rows):
            if len(rows) == 2 and all(row["kind"] == "item" for row in rows):
                self.offer_merge(path, rows[0]["item"], rows[1]["item"])
            elif len(rows) == 1 and rows[0]["kind"] == "candidate":
                self.offer_merge(path, *rows[0]["items"])
            elif len(rows) == 1 and rows[0]["kind"] == "anchor":
                row = rows[0]
                if len(self.by_item[row["item"]]["anchors"]) > 1:
                    self.edit_menu.item("将该回合拆为新事项", "stack", lambda: self.edit(path, "split", item=row["item"],
                                        anchors=[row["anchor"]], title=""))
                self.edit_menu.item("确认此回合的业务状态…", "check", lambda: self.confirm(row))
            self.edit_menu.item("撤销此项目最近一次纠正", "follow", lambda: self.edit(path, "undo"))
        else:
            self.edit_menu.addAction("请选择同一项目的事项或回合").setEnabled(False)
        self.edit_menu.popup_at(self.edit_button.mapToGlobal(QPoint(0, self.edit_button.height())))

    def offer_merge(self, path, target, source):
        project = self.by_project[path]
        names = {item["id"]: item["title"] for item in project["work_items"]}
        keep, move = (names[ident][:25] for ident in (target, source))
        self.edit_menu.item(f"将「{move}」并入「{keep}」", "stack", lambda: self.edit(path, "merge", item=target, **{"from": source}))

    def confirm(self, row):
        dialog = ConfirmWorkDialog(self)
        self.dialog = dialog
        def finished(result):
            if result and self.isVisible():
                self.edit(row["path"], "confirm", anchor=row["anchor"], milestone=dialog.milestone.currentData(),
                          outcome=dialog.outcome.currentData(), scope=" ".join(dialog.scope.text().split()))
            self.release_dialog(dialog)
        dialog.finished.connect(finished)
        dialog.open_near_bottle(dialog.scope)

    def confirm_clear(self):
        selected = self.scope_list.currentItem()
        if selected is None or self.busy() or self.dialog is not None:
            return
        if not self.database.is_file():
            self.status.setText("当前没有本机工作回顾缓存。")
            return
        path = selected.data(ROLE)
        dialog = GlassDialog(self, "清除项目缓存", "清除该目录的回顾快照、人工纠正和已保存的成果。", "清除缓存")
        self.dialog = dialog

        def finished(accepted):
            self.release_dialog(dialog)
            if accepted and self.isVisible():
                self.previous_available = False
                self.render_result(None)
                self.request("clear", path)

        dialog.finished.connect(finished)
        dialog.open_near_bottle(dialog.cancel_button)

    def edit(self, path, kind, **values):
        if self.result is not None and not self.busy():
            self.request("edit", (path, self.result, kind, values))
