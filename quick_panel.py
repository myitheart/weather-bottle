"""Bottle-cap shortcuts and the temporary glass panel that hosts them."""
import sys

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from focus_visual import CompletionLight
from glass_dialog import GlassButton, GlassGlyphButton, PopupAnimation, popup_geometry
from pearl_style import glass, snapshot, text_role
from typography import font

if sys.platform == "win32":
    from ctypes import windll
    key_state = windll.user32.GetAsyncKeyState
else:
    key_state = None


class QuickPanel(QWidget):
    closed = Signal()

    def __init__(self, bottle):
        super().__init__(bottle, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.bottle = bottle
        self.setWindowTitle("经典天气快捷舱")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(252)
        self.amount = 0.
        self.closing = False
        self.pending_action = None
        self.anchor = QPoint()
        self.offset = QPoint()
        self.snapshot = None
        self.light = CompletionLight(bottle)
        self.animation = PopupAnimation(self)
        self.animation.valueChanged.connect(self.draw_frame)
        self.animation.finished.connect(self.finish_transition)
        self.dismiss_watch = QTimer(self)
        self.dismiss_watch.setInterval(30)
        self.dismiss_watch.timeout.connect(self.watch_desktop)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget()
        self.content.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        outer.addWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(17, 12, 17, 15)
        layout.setSpacing(7)
        header = QHBoxLayout()
        header.setContentsMargins(12, 0, 0, 0)
        title = QLabel("经典天气")
        title.setFont(font("panel_title"))
        text_role(title)
        header.addWidget(title, 1)
        close = GlassGlyphButton("close", "关闭快捷舱", 24, 24)
        close.clicked.connect(self.dismiss)
        header.addWidget(close)
        layout.addLayout(header)
        self.weather = self.label()
        self.weather.setFixedHeight(32)
        layout.addWidget(self.weather)
        self.start_button = GlassButton("专注 25 分钟", primary=True)
        self.start_button.clicked.connect(lambda: self.run(lambda: bottle.start_focus(25 * 60)))
        self.reminder_button = GlassButton("添加提醒")
        self.reminder_button.clicked.connect(lambda: self.run(bottle.choose_reminder))
        self.work_button = GlassButton("下班进度")
        self.work_button.setCheckable(True)
        self.work_button.toggled.connect(self.toggle_work)
        for button in (self.start_button, self.reminder_button, self.work_button):
            layout.addWidget(button)
        self.work_detail = self.label()
        self.work_detail.setFixedHeight(34)
        layout.addWidget(self.work_detail)
        self.work_settings = GlassButton("设置上下班时间…")
        self.work_settings.clicked.connect(lambda: self.run(bottle.choose_workday))
        layout.addWidget(self.work_settings)
        self.work_detail.hide()
        self.work_settings.hide()
        self.review_button = GlassButton("工作回顾")
        self.review_button.clicked.connect(lambda: self.run(bottle.toggle_work_memory))
        layout.addWidget(self.review_button)

    @staticmethod
    def label():
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setFont(font("hint"))
        text_role(label, "muted")
        return label

    def run(self, callback):
        if self.closing:
            return
        self.pending_action = callback
        self.dismiss()

    def toggle_work(self, expanded):
        self.work_detail.setVisible(expanded)
        self.work_settings.setVisible(expanded)
        self.refresh()
        self.resize(self.width(), self.sizeHint().height())
        self.reposition()

    def refresh(self):
        b = self.bottle
        location = b.location.name if b.location else "自动定位"
        data = b.current_weather
        self.weather.setText(f"{data.condition} · {data.temperature:.1f} °C · {location}"
                             if data else f"{location} · {b.weather_status}")
        if self.work_button.isChecked():
            self.work_detail.setText(b.workday_status())

    def reveal(self):
        self.closing = False
        self.pending_action = None
        self.amount = 0.
        self.work_button.setChecked(False)
        self.refresh()
        self.content.show()
        self.ensurePolished()
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())
        self.layout().activate()
        self.freeze_content()
        self.reposition()
        self.setWindowOpacity(0.)
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)
        self.last_keys = self.desktop_keys()
        self.dismiss_watch.start()
        self.animation.play(0., 1., easing=QEasingCurve.Type.InOutQuad)

    def freeze_content(self):
        if self.snapshot is None:
            self.snapshot = snapshot(self.content)
        # Keep the layout and window geometry while painting the animated snapshot.
        policy = self.content.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.content.setSizePolicy(policy)
        self.content.hide()

    def dismiss(self):
        if self.isVisible() and not self.closing:
            self.closing = True
            if self.amount <= .01:
                self.finish_transition()
            else:
                self.freeze_content()
                self.animation.play(self.amount, 0., easing=QEasingCurve.Type.InOutQuad)

    def reposition(self):
        bottle = self.bottle.frameGeometry()
        area = self.bottle.screen().availableGeometry()
        gap = 4
        left = bottle.left() - self.width() - gap
        right = bottle.right() + gap + 1
        candidates = ((left, 9, bottle.left() - area.left()), (right, -9, area.right() - bottle.right()))
        x, slide, room = max(candidates, key=lambda candidate: candidate[2])
        if room >= self.width() + gap:
            y = max(area.top(), min(bottle.top() + 9, area.bottom() - self.height() + 1))
            self.anchor, self.offset = QPoint(x, y), QPoint(slide, 0)
        else:
            self.anchor, self.offset = popup_geometry(bottle, self.size(), area)
        self.move_frame()

    def move_frame(self):
        area = self.bottle.screen().availableGeometry()
        position = self.anchor + self.offset * (1 - self.amount)
        self.move(max(area.left(), min(position.x(), area.right() - self.width() + 1)),
                  max(area.top(), min(position.y(), area.bottom() - self.height() + 1)))

    def draw_frame(self, value):
        self.amount = value
        self.setWindowOpacity(value)
        self.move_frame()
        if self.isVisible() and 0 < value < .98:
            scale = self.bottle.bottle_scale / 100
            start = self.bottle.mapToGlobal(QPoint(round((80 + 10 * self.cap_side()) * scale), round(27 * scale)))
            end = self.mapToGlobal(self.dock().toPoint())
            self.light.follow(start, end, value, min(1., (1 - value) * 5))
        else:
            self.light.hide()
        self.update()
        self.bottle.update()

    def cap_side(self):
        return -1 if self.dock().x() > self.width() / 2 else 1

    def cap_opening(self):
        if not self.isVisible():
            return 0.
        duration = .28 if self.closing else .52
        phase = min(1., self.amount / duration)
        return phase * phase * (3 - 2 * phase)

    def finish_transition(self):
        if self.closing:
            callback = self.pending_action
            self.hide()
            if callback is not None:
                callback()
            self.closed.emit()
        else:
            self.snapshot = None
            self.content.show()
            self.update()

    def dock(self):
        start = self.bottle.mapToGlobal(self.bottle.cap_center())
        x = self.width() - 15 if start.x() > self.geometry().center().x() else 15
        return QPointF(x, 24)

    def hideEvent(self, event):
        self.pending_action = None
        self.animation.stop()
        self.snapshot = None
        self.light.hide()
        self.dismiss_watch.stop()
        QApplication.instance().removeEventFilter(self)
        self.bottle.update()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            point = event.globalPosition().toPoint()
            if not self.frameGeometry().contains(point) and not self.bottle.global_cap_contains(point):
                self.dismiss()
        return super().eventFilter(watched, event)

    @staticmethod
    def desktop_keys():
        if key_state is None:
            return set()
        return {key for key in (1, 2, 4, 27) if key_state(key) & 0x8000}

    def watch_desktop(self):
        keys = self.desktop_keys()
        pressed = keys - self.last_keys
        self.last_keys = keys
        if 27 in pressed or (pressed and not self.frameGeometry().contains(QCursor.pos())
                             and not self.bottle.global_cap_contains(QCursor.pos())):
            self.dismiss()

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            box = QRectF(self.rect()).adjusted(3, 2, -3, -4)
            if self.snapshot is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                # The edge nearest the bottle stays fixed while the glass unfolds.
                dock = self.dock()
                sx = .23 + .77 * self.amount
                sy = .66 + .34 * self.amount
                p.translate(dock)
                p.scale(sx, sy)
                p.translate(-dock)
            glass(p, box, "panel")
            if self.snapshot is not None:
                p.drawPixmap(0, 0, self.snapshot)

