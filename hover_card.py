"""Non-interactive glass hover card for the desktop bottle."""
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from glass_dialog import popup_geometry
from pearl_style import DesignTokens, css_color, glass, palette
from typography import draw_line, font
from landscape import ellipse


@dataclass(frozen=True)
class HoverContent:
    heading: str
    primary: str
    detail: str = ""
    hint: str = ""
    wrap_primary: bool = False


class BottleHoverCard(QWidget):
    def __init__(self, bottle):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(bottle, flags)
        self.bottle = bottle
        self.setWindowTitle("灵动珠 · 状态")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(252)
        self.content = None
        self.dwell = 0.
        self.amount = 0.

    def reset(self):
        self.dwell = self.amount = 0.
        if self.isVisible():
            self.hide()

    def tick(self, elapsed, hovering, blocked):
        if blocked:
            self.reset()
            return
        self.dwell = self.dwell + elapsed if hovering else 0.
        target = 1. if hovering and (self.dwell >= .55 or self.isVisible()) else 0.
        step = elapsed / (.17 if target else .13)
        self.amount = min(1., self.amount + step) if target else max(0., self.amount - step)
        if self.amount == 0.:
            if self.isVisible():
                self.hide()
            return
        if not self.isVisible():
            self.set_content(self.bottle.hover_content())
            self.place()
            self.setWindowOpacity(0.)
            self.show()
        opacity = self.amount * self.amount * (3 - 2 * self.amount)
        if abs(self.windowOpacity() - opacity) > .004 or (opacity == 1. and self.windowOpacity() != 1.):
            self.setWindowOpacity(opacity)

    def set_content(self, content):
        if content == self.content:
            return
        self.content = content
        self.setAccessibleName(content.heading)
        self.setAccessibleDescription(" · ".join(filter(None, (content.primary, content.detail, content.hint))))
        self.primary_height = 23
        if content.wrap_primary:
            bounds = QFontMetrics(font("hover_title")).boundingRect(
                QRect(0, 0, self.width() - 32, 1000),
                Qt.TextFlag.TextWrapAnywhere, content.primary)
            self.primary_height = max(23, bounds.height() + 3)
        height = 42 + self.primary_height + (20 if content.detail else 0) + (28 if content.hint else 0)
        if height != self.height():
            self.setFixedHeight(height)
            if self.isVisible():
                self.place()
        self.update()

    def place(self):
        anchor = self.bottle.frameGeometry()
        area = self.bottle.screen().availableGeometry()
        gap = 7
        y = anchor.center().y() - self.height() // 2
        if area.right() - anchor.right() >= self.width() + gap:
            x = anchor.right() + gap + 1
        elif anchor.left() - area.left() >= self.width() + gap:
            x = anchor.left() - self.width() - gap
        else:
            pos, _ = popup_geometry(anchor, self.size(), area)
            self.move(pos)
            return
        self.move(QPoint(x, max(area.top(), min(y, area.bottom() + 1 - self.height()))))

    @staticmethod
    def draw_text(p, rect, text, role, tint):
        p.setPen(QColor(tint))
        draw_line(p, rect, text, role)

    def paintEvent(self, event):
        if self.content is None:
            return
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            box = QRectF(self.rect()).adjusted(3, 2, -3, -4)
            glass(p, box, "panel", radius=17)
            p.setPen(Qt.PenStyle.NoPen)
            ellipse(p, 18, 20, 2.25, 2.25, QColor(DesignTokens.GOLD))
            w = self.width() - 32
            self.draw_text(p, QRectF(27, 11, w - 11, 18), self.content.heading, "hint", DesignTokens.GOLD)
            if self.content.wrap_primary:
                p.setFont(font("hover_title"))
                p.setPen(QColor(DesignTokens.TEXT))
                p.drawText(QRectF(16, 31, w, self.primary_height), Qt.TextFlag.TextWrapAnywhere, self.content.primary)
            else:
                self.draw_text(p, QRectF(16, 31, w, 23), self.content.primary, "hover_title", DesignTokens.TEXT)
            y = 33 + self.primary_height
            if self.content.detail:
                self.draw_text(p, QRectF(16, y, w, 17), self.content.detail, "hint", DesignTokens.MUTED)
                y += 20
            if self.content.hint:
                p.setPen(QPen(css_color(palette().line), .75))
                p.drawLine(QPointF(16, y + 1), QPointF(self.width() - 16, y + 1))
                self.draw_text(p, QRectF(16, y + 5, w, 17), self.content.hint, "hint", DesignTokens.MUTED)

