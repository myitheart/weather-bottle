"""Translucent, non-activating focus completion capsule."""
from math import pi, sin

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from hourglass import glow
from landscape import color, ellipse
from glass_dialog import GlassButton
from pearl_style import glass, glyph, palette, themed, text_role
from typography import font


def smooth(value):
    value = min(1., max(0., value))
    return value * value * (3 - 2 * value)


def gold_light(p, point, strength, radius=3.2):
    x, y = point.x(), point.y()
    glow(p, x, y, radius * 4.3, "#ffcf81", round(230 * strength))
    ellipse(p, x, y, radius, radius, color("#ffe1a7", round(248 * strength)))
    ellipse(p, x - radius * .19, y - radius * .23, radius * .58, radius * .58,
            color("#fff6dc", round(250 * strength)))


class CompletionLight(QWidget):
    """A small, click-through window for the frames between the two widgets."""

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.start = QPointF()
        self.end = QPointF()
        self.progress = 0.
        self.opacity = 1.

    def follow(self, start, end, progress, opacity):
        bounds = QRectF(QPointF(start), QPointF(end)).normalized().adjusted(-20, -36, 20, 20)
        rect = bounds.toAlignedRect()
        if self.geometry() != rect:
            self.setGeometry(rect)
        origin = QPointF(rect.topLeft())
        self.start, self.end = QPointF(start) - origin, QPointF(end) - origin
        self.progress = progress
        self.opacity = opacity
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def point_at(self, progress):
        t = smooth((progress - .18) / .82)
        point = self.start + (self.end - self.start) * t
        point.setY(point.y() - sin(pi * t) * 19)
        return point

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            t = self.progress
            strength = smooth(t / .16) * self.opacity
            for i in range(3, 0, -1):
                trail = t - i * .044
                if trail > .18:
                    point = self.point_at(trail)
                    ellipse(p, point.x(), point.y() + i * .45, 1.02 - i * .15, 1.02 - i * .15,
                            color("#ffe8b5", round(110 * strength * (1 - i / 4))))
            gold_light(p, self.point_at(t), strength, 2.7 + .65 * sin(pi * t))


class CapsuleButton(GlassButton):
    def __init__(self, label, primary=False):
        super().__init__(label, primary)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class FocusCapsule(QWidget):
    def __init__(self, bottle):
        super().__init__(bottle, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(252, 113)
        self.setWindowTitle("灵动珠 · 专注提醒")
        self.opens_left = False
        self.anchor = QPoint()
        self.amount = 0.
        self.timeline = 0.
        self.closing = False
        self.reminder_id = None
        self.bottle = bottle
        self.light = CompletionLight(bottle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(19, 13, 19, 16)
        layout.setSpacing(9)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setFont(font("callout_title"))
        layout.addWidget(self.title, 1)
        self.detail = QLabel()
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setFont(font("hint"))
        text_role(self.detail, "muted")
        self.detail.hide()
        layout.addWidget(self.detail)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.break_button = CapsuleButton("休息 5 分钟", primary=True)
        self.break_button.clicked.connect(lambda: bottle.start_break())
        self.end_button = CapsuleButton("结束")
        self.end_button.clicked.connect(bottle.end_focus)
        actions.addWidget(self.break_button, 3)
        actions.addWidget(self.end_button, 2)
        self.snooze_button = CapsuleButton("稍后 10 分钟")
        self.snooze_button.clicked.connect(lambda: bottle.resolve_reminder(snooze=True))
        self.complete_button = CapsuleButton("完成", primary=True)
        self.complete_button.clicked.connect(bottle.resolve_reminder)
        for button in (self.snooze_button, self.complete_button):
            actions.addWidget(button, 2)
            button.hide()
        layout.addLayout(actions)
        self.reveal = QVariantAnimation(self)
        self.reveal.setEasingCurve(QEasingCurve.Type.Linear)
        self.reveal.valueChanged.connect(self.update_reveal)
        self.reveal.finished.connect(self.finish_reveal)

    def animate_to(self, target, duration):
        self.reveal.stop()
        self.reveal.setDuration(duration)
        self.reveal.setEasingCurve(QEasingCurve.Type.InCubic if self.closing else QEasingCurve.Type.Linear)
        self.reveal.setStartValue(self.amount if self.closing else 0.)
        self.reveal.setEndValue(target)
        self.reveal.start()

    def update_reveal(self, value):
        self.timeline = value
        self.amount = value if self.closing else smooth((value - .44) / .56)
        self.setWindowOpacity(self.amount)
        self.position_reveal()
        self.update_light()
        self.update()

    def dock(self):
        return QPoint(231 if self.opens_left else 20, 42)

    def update_light(self):
        if self.closing or self.timeline >= .94:
            self.light.hide()
        else:
            if self.bottle.fold == 0.:
                source = self.bottle.frameGeometry().center()
            else:
                scale = self.bottle.bottle_scale / 100
                source = self.bottle.mapToGlobal(QPoint(round(80 * scale), round(105 * scale)))
            blend = smooth((self.timeline - .73) / .21)
            self.light.follow(source, self.pos() + self.dock(), min(1., self.timeline / .73), 1 - blend)

    def position_reveal(self):
        distance = round((1 - self.amount) * (22 if self.opens_left else -22))
        self.move(self.anchor + QPoint(distance, 0))

    def finish_reveal(self):
        if self.closing:
            self.hide()
        else:
            self.setEnabled(True)

    def open_for(self, bottle, phase):
        if self.isVisible() and not self.closing:
            return
        self.reminder_id = None
        self.setFixedHeight(113)
        self.title.setWordWrap(False)
        self.title.setText("专注完成" if phase == "focus_done" else "休息结束")
        self.detail.hide()
        self.snooze_button.hide()
        self.complete_button.hide()
        self.end_button.show()
        self.break_button.setVisible(phase == "focus_done")
        self.end_button.setText("结束" if phase == "focus_done" else "返回天气")
        self.open_capsule(bottle)

    def open_reminder(self, bottle, reminder):
        self.reminder_id = reminder.id
        self.setFixedHeight(152)
        title = reminder.interval_label() if reminder.interval_minutes else reminder.time_label()
        self.title.setText(reminder.text)
        self.title.setWordWrap(True)
        self.detail.setText(f"提醒 · {title}")
        self.detail.show()
        self.break_button.hide()
        self.end_button.hide()
        self.snooze_button.show()
        self.complete_button.show()
        self.open_capsule(bottle)

    def open_capsule(self, bottle):
        self.closing = False
        self.setEnabled(False)
        self.timeline = self.amount = 0.
        self.reposition(bottle)
        self.setWindowOpacity(0.)
        self.show()
        self.update_light()
        self.animate_to(1., 330)

    def retract(self):
        if self.isVisible() and not self.closing:
            self.closing = True
            self.setEnabled(False)
            self.light.hide()
            if self.amount == 0:
                self.hide()
                return
            self.animate_to(0., 220)

    def reposition(self, bottle):
        bounds = bottle.frameGeometry()
        screen = QApplication.screenAt(bounds.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        gap = -round(11 * bottle.bottle_scale / 100)
        left_room = bounds.left() - area.left()
        right_room = area.right() - bounds.right()
        self.opens_left = left_room > right_room
        themed(self.title, lambda: f"color: {palette().text}; padding-left: {23 if self.opens_left else 30}px;")
        x = bounds.left() - self.width() - gap if self.opens_left else bounds.right() + gap
        y = bounds.center().y() - self.height() // 2
        self.anchor = QPoint(max(area.left(), min(x, area.right() - self.width() + 1)),
                             max(area.top(), min(y, area.bottom() - self.height() + 1)))
        self.position_reveal()
        if self.isVisible() and not self.closing:
            self.update_light()

    def hideEvent(self, event):
        self.reveal.stop()
        self.light.hide()
        self.closing = False
        self.amount = 0.
        self.reminder_id = None
        super().hideEvent(event)

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            box = QRectF(self.rect()).adjusted(3, 2, -3, -5)
            glass(p, box, "panel")
            title_x = 29 if self.opens_left else 33
            glyph(p, "bell" if self.reminder_id else "check", QPointF(title_x, 35),
                  palette().ice if self.reminder_id else palette().success, 1.12)
