"""Expandable, locally resolved activity for the desktop light orb."""
from collections import Counter
from hashlib import blake2s
import json
import re
import shutil
from time import monotonic, time

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QProcess, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from activity_visual import draw_compact, draw_pearl, smooth
from codex_activity import display_name
from glass_dialog import GlassButton, GlassGlyphButton, GlassTile, PopupAnimation, popup_geometry
from pearl_style import DesignTokens, css_color, glass, glyph, palette, snapshot, text_role, themed
from landscape import color, ellipse
from quick_panel import QuickPanel
from typography import draw_line, draw_number, font, metrics, number_width, text_baseline


LABELS = {"running": "处理中", "ended": "本轮已结束", "failed": "运行失败",
          "interrupted": "已中断", "unknown": "状态未确认"}
THREAD_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")


class CodexThreadNames(QObject):
    """Read optional display titles on demand through the local app server."""

    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.child = QProcess(self)
        self.child.started.connect(self.initialize)
        self.child.readyReadStandardOutput.connect(self.read_output)
        self.child.readyReadStandardError.connect(self.child.readAllStandardError)
        self.child.finished.connect(self.reset)
        self.child.errorOccurred.connect(self.reset)
        self.timeout = QTimer(self, singleShot=True, interval=8000)
        self.timeout.timeout.connect(self.stop)
        self.cache = {}
        self.pending = set()
        self.requests = {}
        self.serial = 1
        self.ready = False
        self.buffer = bytearray()

    def title(self, thread):
        entry = self.cache.get(thread)
        return entry[0] if entry else ""

    def fetch(self, threads):
        now = monotonic()
        visible = {thread for thread in threads if isinstance(thread, str) and THREAD_ID.fullmatch(thread)}
        self.cache = {thread: entry for thread, entry in self.cache.items()
                      if thread in visible or entry[1] > now}
        self.pending.update(thread for thread in visible.difference(self.requests.values())
                            if now >= self.cache.get(thread, ("", 0))[1])
        if not self.pending:
            return
        if self.ready:
            self.send_pending()
        elif self.child.state() == QProcess.ProcessState.NotRunning:
            executable = shutil.which("codex")
            if executable:
                self.child.start(executable, ["app-server"])
                self.timeout.start()
            else:
                self.reset()

    def send(self, method, params=None, request_id=None):
        message = {"method": method}
        if request_id is not None:
            message["id"] = request_id
        if params is not None:
            message["params"] = params
        self.child.write((json.dumps(message) + "\n").encode("utf-8"))

    def initialize(self):
        self.send("initialize", {"clientInfo": {"name": "dynamic_bottle", "version": "1.1"}}, 0)

    def send_pending(self):
        for thread in sorted(self.pending):
            self.requests[self.serial] = thread
            self.send("thread/read", {"threadId": thread, "includeTurns": False}, self.serial)
            self.serial += 1
        self.pending.clear()
        self.timeout.start()

    def read_output(self):
        self.buffer.extend(bytes(self.child.readAllStandardOutput()))
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()
        changed = False
        for line in lines:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            request_id = message.get("id")
            if request_id == 0 and "result" in message:
                self.ready = True
                self.send("initialized")
                self.send_pending()
            elif isinstance(request_id, int) and request_id in self.requests:
                thread = self.requests.pop(request_id)
                metadata = (message.get("result") or {}).get("thread") or {}
                # The preview often contains user text. Display only the chat name.
                title = display_name(metadata.get("name"))
                self.cache[thread] = (title, monotonic() + (60 if title else 15))
                changed = True
        if self.ready and not self.requests:
            self.timeout.stop()
        if changed:
            self.changed.emit()

    def reset(self, *_):
        retry_at = monotonic() + 15
        for thread in self.pending | set(self.requests.values()):
            self.cache[thread] = (self.title(thread), retry_at)
        self.timeout.stop()
        self.pending.clear()
        self.requests.clear()
        self.buffer.clear()
        self.ready = False

    def stop(self):
        self.reset()
        if self.child.state() != QProcess.ProcessState.NotRunning:
            self.child.kill()
            self.child.waitForFinished(50)


class ActivityRow(QPushButton):
    def __init__(self, panel):
        entry = QWidget(panel.list)
        super().__init__(entry)
        self.entry = entry
        self.bottle = panel.bottle
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.project = self.title = self.state = self.status = ""
        self.record = None
        self.clock = ""
        self.unread = False
        self.clicked.connect(lambda: self.bottle.open_activity(self.record))
        self.review = GlassGlyphButton("check", "标为已查看", 30, 32)
        self.review.clicked.connect(lambda: self.bottle.mark_activity_reviewed(self.record))
        self.pin = GlassGlyphButton("pin", "挂到桌角", 31, 32)
        self.pin.setCheckable(True)
        self.pin.clicked.connect(lambda: self.bottle.toggle_activity_pin(self.record))
        row = QHBoxLayout(entry)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self, 1)
        row.addWidget(self.review)
        row.addWidget(self.pin)

    def set_record(self, project, title, record, now, pinned, unread):
        self.record = record
        self.project, self.title = project, title
        thread = record.get("thread")
        self.state = record["state"]
        self.status = LABELS[self.state]
        self.clock = ""
        if self.state == "running":
            mins, secs = divmod(max(0, int(now - record["started"])), 60)
            self.clock = f"{mins:02d}:{secs:02d}"
        self.unread = unread
        if pinned:
            self.project = f"已挂住 · {project}"
        self.setAccessibleName(f"{self.project} · {title}")
        self.setAccessibleDescription(" · ".join(part for part in (
            self.status, self.clock, "待查看" if unread else "") if part))
        can_open = isinstance(thread, str) and bool(THREAD_ID.fullmatch(thread))
        self.setEnabled(can_open)
        self.review.setVisible(unread)
        self.pin.setEnabled(can_open)
        self.pin.setChecked(pinned)
        label = "取消挂住" if pinned else "挂到桌角"
        self.pin.setText(label)
        self.pin.setToolTip(label)
        self.pin.setAccessibleName(label)
        self.update()

    def paintEvent(self, event):
        t = palette()
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            box = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
            if self.underMouse() or self.isDown() or self.hasFocus():
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(css_color(t.pressed if self.isDown() else t.hover))
                p.drawRoundedRect(box, 7, 7)
            p.setPen(QPen(css_color(t.line), .7))
            p.drawLine(QPointF(26, box.bottom()), QPointF(box.right(), box.bottom()))
            center = QPointF(12, 24)
            if self.state == "running":
                glyph(p, "running", center, t.warm, .88)
            elif self.state == "ended":
                glyph(p, "check", center, t.success, .88)
            else:
                glyph(p, "notice", center, t.error if self.state in {"failed", "interrupted"} else t.muted, .88)
            width = self.width() - 31
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.setPen(QColor(t.text))
            draw_line(p, QRectF(25, 4, width + 2, 20), self.title, "list_title")

            row = QRectF(26, 25, width, 17)
            baseline = text_baseline(p, row, "list_meta")
            meta = metrics(p, "list_meta")
            badge = "待查看" if self.unread else self.clock
            is_clock = bool(self.clock and not self.unread)
            detail_width = number_width(p, badge, "list_clock") if is_clock else meta.horizontalAdvance(badge)
            detail_end = row.right()
            if badge:
                detail = QRectF(detail_end - detail_width - 2, row.top(), detail_width + 2, row.height())
                p.setPen(QColor(t.warm if self.unread else t.muted))
                if is_clock:
                    draw_number(p, detail, badge, "list_clock", baseline=baseline)
                else:
                    draw_line(p, detail, badge, "list_meta", align=Qt.AlignmentFlag.AlignRight, baseline=baseline)
                detail_end = detail.left() - 6.

            status_width = meta.horizontalAdvance(self.status) + 2
            status = QRectF(detail_end - status_width, row.top(), status_width, row.height())
            p.setPen(QColor(t.muted))
            draw_line(p, QRectF(row.left(), row.top(), status.left() - row.left() - 7., row.height()),
                      self.project, "list_meta", baseline=baseline)
            p.setPen(QColor(t.success if self.state == "ended" else t.error if self.state == "interrupted" else t.muted))
            draw_line(p, status, self.status, "list_meta", align=Qt.AlignmentFlag.AlignRight, baseline=baseline)


class PearlMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(24, 24)

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_pearl(p, QPointF(12, 11), 8.1, 0., .71, None)


class ActivityScroll(QScrollArea):
    def __init__(self):
        super().__init__()
        self.wheel = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self.wheel.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.wheel.setDuration(135)

    def wheelEvent(self, event):
        if event.pixelDelta().y() or not event.angleDelta().y():
            self.wheel.stop()
            return super().wheelEvent(event)
        bar = self.verticalScrollBar()
        base = int(self.wheel.endValue()) if self.wheel.state() == QPropertyAnimation.State.Running else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), base - round(event.angleDelta().y() * .43)))
        self.wheel.stop()
        self.wheel.setStartValue(bar.value())
        self.wheel.setEndValue(target)
        self.wheel.start()
        event.accept()


class CapsulePreview(QWidget):
    def __init__(self, panel):
        super().__init__(panel.content)
        self.panel = panel
        self.face = None
        self.setFixedHeight(38)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_face(self, face):
        if self.face != face:
            self.face = face
            self.update()
        self.setVisible(face is not None)

    def paintEvent(self, event):
        if not self.face:
            return
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_compact(p, self.width(), self.height(), on_right=self.panel.on_right,
                         state="running", progress=1., hover=0., glint=1., active=0,
                         recent=None, finished=0, elapsed=0, change=(0, 1.), face=self.face)


class ActivityPanel(QWidget):
    def __init__(self, bottle):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(bottle, flags)
        self.bottle = bottle
        self.setWindowTitle("灵动珠")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(318)
        self.records = []
        self.rows = {}
        self.order = ()
        self.mode = "activities"
        self.unread_first = False
        self.on_right = False
        self.seed = QRectF()
        self.amount = 1.
        self.closing = False
        self.snapshot = None
        self.pending_action = None
        self.names = CodexThreadNames(self)
        self.names.changed.connect(self.refresh)
        self.animation = PopupAnimation(self)
        self.animation.valueChanged.connect(self.draw_frame)
        self.animation.finished.connect(self.finish_transition)
        self.watch = QTimer(self, interval=30)
        self.watch.timeout.connect(self.watch_desktop)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget(self)
        self.content.setAutoFillBackground(False)
        self.content.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        policy = self.content.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.content.setSizePolicy(policy)
        outer.addWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(15, 12, 15, 14)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(PearlMark())
        self.title = QLabel()
        self.title.setFont(font("panel_title"))
        text_role(self.title)
        header.addWidget(self.title, 1)
        self.summary = QLabel()
        self.summary.setFont(font("hint"))
        text_role(self.summary, "muted")
        header.addWidget(self.summary)
        close = GlassGlyphButton("close", "收起面板", 24, 24)
        close.clicked.connect(self.dismiss)
        header.addWidget(close)
        layout.addLayout(header)

        self.preview = CapsulePreview(self)
        layout.addWidget(self.preview)
        self.focus_controls = QWidget(self.content)
        focus_row = QHBoxLayout(self.focus_controls)
        focus_row.setContentsMargins(0, 0, 0, 0)
        self.focus_primary = GlassButton("暂停", primary=True)
        self.focus_primary.clicked.connect(self.focus_action)
        focus_row.addWidget(self.focus_primary, 1)
        self.focus_end = GlassButton("结束")
        self.focus_end.clicked.connect(lambda: self.dismiss_then(bottle.end_focus))
        focus_row.addWidget(self.focus_end, 1)
        layout.addWidget(self.focus_controls)
        self.focus_switch = GlassButton("查看 Codex 活动")
        self.focus_switch.clicked.connect(self.switch_focus_view)
        layout.addWidget(self.focus_switch)
        self.work_review = GlassButton("工作回顾")
        self.work_review.clicked.connect(lambda: self.dismiss_then(bottle.toggle_work_memory))
        layout.addWidget(self.work_review)
        self.quick = QWidget(self.content)
        quick_layout = QGridLayout(self.quick)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(8)
        for index, (label, icon, action) in enumerate((
            ("专注 25 分钟", "play", lambda: self.dismiss_then(lambda: bottle.start_focus(25 * 60))),
            ("查看 Codex 活动", "stack", self.show_activities),
            ("添加提醒", "bell", lambda: self.dismiss_then(bottle.choose_reminder)),
            ("下班进度", "bars", self.show_workday),
        )):
            tile = GlassTile(label, icon, primary=index == 0)
            tile.clicked.connect(action)
            quick_layout.addWidget(tile, index // 2, index % 2)
        layout.addWidget(self.quick)
        self.workday = QWidget(self.content)
        work_layout = QVBoxLayout(self.workday)
        work_layout.setContentsMargins(0, 0, 0, 0)
        self.work_status = QLabel()
        self.work_status.setFont(font("section_title"))
        self.work_status.setWordWrap(True)
        self.work_status.setMinimumHeight(33)
        text_role(self.work_status)
        work_layout.addWidget(self.work_status)
        work_controls = QHBoxLayout()
        self.work_toggle = GlassButton("启用下班日落")
        self.work_toggle.clicked.connect(self.toggle_workday)
        work_controls.addWidget(self.work_toggle)
        work_setup = GlassButton("设置时间…")
        work_setup.clicked.connect(lambda: self.dismiss_then(bottle.choose_workday))
        work_controls.addWidget(work_setup)
        work_layout.addLayout(work_controls)
        layout.addWidget(self.workday)

        self.scroll = ActivityScroll()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        themed(self.scroll, lambda: (
            "QScrollArea { background: transparent; }"
            "QScrollBar:vertical { width: 5px; background: transparent; }"
            f"QScrollBar::handle:vertical {{ min-height: 20px; border-radius: 2px; background: {palette().muted}; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        ))
        self.list = QWidget()
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 3, 0)
        self.list_layout.setSpacing(5)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list)
        self.list.setAutoFillBackground(False)
        self.scroll.viewport().setAutoFillBackground(False)
        layout.addWidget(self.scroll)
        self.empty = QWidget(self.content)
        no_activity = QHBoxLayout(self.empty)
        no_activity.setContentsMargins(0, 1, 0, 1)
        no_activity.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_activity.addWidget(PearlMark())
        empty_text = QLabel("当前没有 Codex 活动")
        empty_text.setFont(font("hint"))
        text_role(empty_text, "muted")
        no_activity.addWidget(empty_text)
        self.empty.setFixedHeight(48)
        layout.addWidget(self.empty)

    def set_records(self, records):
        self.records = records
        if self.isVisible() and self.mode != "quick":
            self.refresh()
            self.fetch_names()

    def fetch_names(self):
        if self.mode == "activities" and not self.closing:
            self.names.fetch(record.get("thread") for record in self.records)

    def focus_action(self):
        phase = self.bottle.focus.phase
        if phase == "focus_done":
            self.dismiss_then(self.bottle.start_break)
        elif phase == "break_done":
            self.dismiss_then(self.bottle.end_focus)
        elif self.bottle.focus.running:
            self.bottle.toggle_focus_pause()
            self.refresh()

    def switch_focus_view(self):
        if self.mode == "focus":
            self.show_activities()
        else:
            self.mode = "focus"
            self.refresh()

    def show_activities(self):
        self.mode = "activities"
        self.refresh()
        self.fetch_names()

    def show_workday(self):
        self.mode = "workday"
        self.refresh()

    def toggle_workday(self):
        self.bottle.work_action.toggle()
        self.refresh()

    def reveal(self, mode="activities", *, unread_first=False):
        if self.isVisible() and self.closing:
            self.closing = False
            self.pending_action = None
            self.play_transition(1.)
            return
        self.mode = mode
        self.unread_first = unread_first
        self.amount = 0.
        self.refresh()
        self.freeze_content()
        self.show()
        self.raise_()
        self.last_keys = QuickPanel.desktop_keys()
        QApplication.instance().installEventFilter(self)
        self.watch.start()
        self.play_transition(1.)
        self.fetch_names()

    def play_transition(self, target):
        if self.bottle.reduced_motion:
            self.animation.stop()
            self.draw_frame(target)
            self.finish_transition()
        else:
            self.animation.play(self.amount, target, easing=QEasingCurve.Type.InOutCubic)

    def freeze_content(self):
        if self.snapshot is None:
            self.content.layout().activate()
            self.snapshot = snapshot(self.content)
            self.content.hide()

    def dismiss_then(self, action):
        self.pending_action = action
        self.dismiss()

    def dismiss(self):
        if self.isVisible() and not self.closing:
            self.closing = True
            self.freeze_content()
            if self.amount <= .01:
                self.finish_transition()
            else:
                self.play_transition(0.)

    def draw_frame(self, value):
        self.amount = value
        self.update()

    def finish_transition(self):
        if self.closing:
            action = self.pending_action
            self.hide()
            if action:
                action()
        else:
            self.snapshot = None
            self.content.show()
            self.refresh()
            self.update()

    def refresh(self):
        if self.snapshot is not None:
            return
        phase = self.bottle.focus.phase
        if self.mode == "focus" and phase == "idle":
            self.mode = "activities" if self.records else "quick"
        showing = self.mode == "activities"
        focus_view = self.mode == "focus"
        session_title = "休息计时" if phase.startswith("break") else "专注计时"
        self.title.setText({"activities": "Codex 活动", "workday": "下班进度",
                            "quick": DesignTokens.BRAND, "focus": session_title}[self.mode])
        self.focus_controls.setVisible(focus_view)
        self.focus_switch.setVisible(focus_view or showing and phase != "idle")
        self.focus_switch.setText("查看 Codex 活动" if focus_view else session_title)
        self.work_review.setVisible(showing or focus_view or self.mode == "quick")
        if focus_view:
            action = {"focus_done": "休息 5 分钟", "break_done": "结束"}.get(phase)
            self.focus_primary.setText(action or ("继续" if self.bottle.focus.deadline is None else "暂停"))
            self.focus_end.setVisible(phase != "break_done")
        self.quick.setVisible(self.mode == "quick")
        self.workday.setVisible(self.mode == "workday")
        if self.mode == "workday":
            self.work_status.setText(self.bottle.workday_status())
            self.work_toggle.setText("关闭下班日落" if self.bottle.work_action.isChecked() else "启用下班日落")
        self.preview.set_face(self.bottle.activity_panel_face() if showing or focus_view else None)
        records = self.records if showing else []
        if showing and self.unread_first:
            records = sorted(records, key=lambda item: not item.get("unread"))
        self.update_rows(records)
        self.empty.setVisible(showing and not records)
        self.scroll.setVisible(bool(records))
        available = self.bottle.screen().availableGeometry()
        above = self.bottle.frameGeometry().top() - available.top()
        below = available.bottom() - self.bottle.frameGeometry().bottom()
        reserve = (105 if self.preview.face else 63) + 44 + (41 if showing and phase != "idle" else 0)
        rows_count = min(len(records), 4, max(1, (max(above, below) - reserve) // 53))
        if rows_count:
            self.scroll.setFixedHeight(rows_count * 53 - 5)
        self.setFixedWidth(min(318, available.width()))
        self.content.layout().activate()
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())
        self.place()

    def update_rows(self, records):
        order = tuple(record["id"] for record in records)
        if order != self.order:
            keep = set(order)
            for key in self.order:
                row = self.rows[key]
                self.list_layout.removeWidget(row.entry)
                if key not in keep:
                    row.entry.hide()
                    row.entry.deleteLater()
                    del self.rows[key]
            for key in order:
                if key not in self.rows:
                    self.rows[key] = ActivityRow(self)
                self.list_layout.addWidget(self.rows[key].entry)
            self.order = order
        active = sum(record["state"] == "running" for record in records)
        pending = sum(bool(record.get("unread")) for record in records)
        count_in_preview = self.mode == "activities" and self.preview.face and self.bottle.visible_pin is None
        status = [f"{active} 项处理中"] if active and not count_in_preview else []
        pending_text = f"{pending} 项待查看"
        if pending and (not self.preview.face or pending_text not in (self.preview.face.label, self.preview.face.detail)):
            status.append(pending_text)
        self.summary.setText(" · ".join(status))
        entries = []
        for record in records:
            project = display_name(record.get("project")) or ("灵动瓶" if record.get("in_project") else "未分组")
            short = blake2s((record.get("thread") or record["id"]).encode("utf-8"), digest_size=2).hexdigest()
            title = self.names.title(record.get("thread")) or f"聊天 {short}"
            entries.append((record, project, title, short))
        duplicates = Counter((project, title) for _, project, title, _ in entries)
        now = time()
        for record, project, title, short in entries:
            if duplicates[project, title] > 1:
                title = f"{short} · {title}"
            self.rows[record["id"]].set_record(
                project, title, record, now, bool(record.get("pinned")), bool(record.get("unread")))

    def place(self):
        if self.isVisible() and self.snapshot is not None:
            return
        anchor = self.bottle.visual_geometry()
        area = self.bottle.screen().availableGeometry()
        self.on_right = self.bottle.compact_on_right
        left = anchor.right() + 1 - self.width() if self.on_right else anchor.left()
        x = max(area.left(), min(left, area.right() - self.width() + 1))
        above, below = anchor.top() - area.top(), area.bottom() - anchor.bottom()
        if above + 4 >= self.height():
            position = QPoint(x, anchor.top() - self.height() + 4)
        elif below + 4 >= self.height():
            position = QPoint(x, anchor.bottom() - 3)
        else:
            position, _ = popup_geometry(anchor, self.size(), area)
        if position != self.pos():
            self.move(position)
        w = min(anchor.width() - 6, self.width() - 6)
        source_x = anchor.right() - w - position.x() - 2 if self.on_right else anchor.left() - position.x() + 3
        seed_x = max(3, min(source_x, self.width() - w - 3))
        seed_y = max(2, min(anchor.center().y() - position.y() - 4, self.height() - 13))
        self.seed = QRectF(seed_x, seed_y, w, 11)

    def watch_desktop(self):
        keys = QuickPanel.desktop_keys()
        pressed = keys - self.last_keys
        self.last_keys = keys
        pointer = QCursor.pos()
        if 27 in pressed or (pressed and not self.frameGeometry().contains(pointer)
                             and not self.bottle.frameGeometry().contains(pointer)):
            self.dismiss()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            point = event.globalPosition().toPoint()
            if not self.frameGeometry().contains(point) and not self.bottle.frameGeometry().contains(point):
                self.dismiss()
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.animation.stop()
        self.watch.stop()
        self.names.stop()
        self.snapshot = None
        self.pending_action = None
        self.closing = False
        self.content.show()
        super().hideEvent(event)

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            full = QRectF(self.rect()).adjusted(3, 2, -3, -4)
            t = self.amount
            if self.snapshot is None:
                box = full
            else:
                a = self.seed
                contour = smooth(t / .91)
                box = QRectF(a.x() + (full.x() - a.x()) * contour, a.y() + (full.y() - a.y()) * contour,
                             a.width() + (full.width() - a.width()) * contour,
                             a.height() + (full.height() - a.height()) * contour)
            p.setOpacity(smooth(t / .22))
            reflection_x = self.seed.center().x() * (1-t) + (box.right()-box.width()*.21
                           if self.on_right else box.left()+box.width()*.21)*t
            glass(p, box, "panel", reflected_at=QPointF(reflection_x, box.top()))
            if self.snapshot is not None:
                clip = QPainterPath()
                clip.addRoundedRect(box, min(19., box.height() / 2), min(19., box.height() / 2))
                p.setClipPath(clip)
                p.setOpacity(smooth((t - .76) / .24))
                p.drawPixmap(0, 0, self.snapshot)
