"""Workday accents that leave the active weather scene running."""
from math import cos, pi, sin

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from typography import draw_line
from landscape import color, ellipse, linear


def draw_workday_indicator(p, progress, celebrating):
    p.save()
    if celebrating:
        badge = QRectF(47, 132, 66, 24)
        p.setBrush(QColor(31, 36, 54, 223))
        p.setPen(QPen(QColor("#e9bd81"), .8))
        p.drawRoundedRect(badge, 10, 10)
        p.setPen(QColor("#fff0d2"))
        draw_line(p, badge, "下班啦", "button", align=Qt.AlignmentFlag.AlignHCenter)
    else:
        p.setPen(QPen(color("#18324d", 146), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(54, 164), QPointF(106, 164))
        p.setPen(QPen(linear(54, 164, 106, 164, "#ffdea2", "#ffba73"), 1.8,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(54, 164), QPointF(54 + 52 * progress, 164))
    p.restore()


class WorkdayFireworks(QWidget):
    BURSTS = ((-18, 72, .0), (46, 104, 1.05), (-56, 111, 2.25), (20, 137, 3.5),
              (60, 78, 4.7), (-39, 97, 6.), (2, 131, 7.25))

    def __init__(self, bottle):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        super().__init__(bottle, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.elapsed = 0.
        self.origin = QPointF()
        self.burst_center = 0.
        self.direction = -1

    def paint_frame(self, bottle, elapsed):
        bounds = bottle.frameGeometry()
        area = bottle.screen().availableGeometry()
        cap = bounds.topLeft() + QPoint(bounds.width() // 2, round(15 * bottle.bottle_scale / 100))
        self.direction = -1 if cap.y() - area.top() >= 166 or cap.y() > area.center().y() else 1
        width, height = min(224, area.width()), min(180, area.height())
        left = max(area.left(), min(cap.x() - width // 2, area.right() - width + 1))
        top = cap.y() - height + 10 if self.direction < 0 else cap.y() - 10
        top = max(area.top(), min(top, area.bottom() - height + 1))
        origin = QPointF(cap.x() - left, cap.y() - top)
        # Keep bursts away from screen edges even when the bottle is dragged to a corner.
        margin = min(83, width / 2)
        self.burst_center = min(width - margin, max(margin, origin.x()))
        self.origin = origin
        self.elapsed = elapsed
        if (self.x(), self.y(), self.width(), self.height()) != (left, top, width, height):
            self.setGeometry(left, top, width, height)
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            for index, (dx, height, delay) in enumerate(self.BURSTS):
                elapsed = self.elapsed - delay
                target = QPointF(self.burst_center + dx, self.origin.y() + self.direction * height)
                target.setY(max(25, min(self.height() - 25, target.y())))
                if 0 <= elapsed < .42:
                    t = elapsed / .42
                    head = self.origin + (target - self.origin) * t
                    p.setPen(QPen(color("#ffca8b", 180), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    p.drawLine(head - (target - self.origin) * .10 * t, head)
                    p.setPen(Qt.PenStyle.NoPen)
                    ellipse(p, head.x(), head.y(), 2.15, 2.15, QColor("#fff0c2"))
                    continue
                age = (elapsed - .42) / 2.15
                if not 0 <= age < 1:
                    continue
                opacity = (1 - age) ** .84
                radius = (17 + index % 3 * 3) * (1 - (1 - age) ** 2)
                p.setPen(Qt.PenStyle.NoPen)
                halo = QRadialGradient(target, 24)
                halo.setColorAt(0, color("#ffc47d", round(152 * opacity)))
                halo.setColorAt(1, color("#ffc47d", 0))
                ellipse(p, target.x(), target.y(), 24, 24, halo)
                for spark in range(18):
                    angle = 2 * pi * spark / 18 + index * .7
                    vector = QPointF(cos(angle), sin(angle))
                    head = target + vector * (radius * (1 - .14 * (spark % 3))) + QPointF(0, 7 * age ** 2)
                    tint = ("#ffbd71", "#fff3d0", "#ffc0af")[spark % 3]
                    p.setPen(QPen(color(tint, round(180 * opacity)), 1.1, Qt.PenStyle.SolidLine,
                                  Qt.PenCapStyle.RoundCap))
                    p.drawLine(head - vector * (2 + radius * .24), head)
                    p.setPen(Qt.PenStyle.NoPen)
                    ellipse(p, head.x(), head.y(), 1.25, 1.25, color(tint, round(255 * opacity)))

