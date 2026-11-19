"""Fluent-inspired Qt popup styling with a translucent fallback."""
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QSizePolicy, QWidgetAction


from pearl_style import SURFACES, palette, themed
from typography import font


def menu_style():
    t = palette()
    alpha = SURFACES["menu"].opacity

    def fill(hex_color, opacity):
        rgb = QColor(hex_color)
        return f"rgba({rgb.red()},{rgb.green()},{rgb.blue()},{opacity})"

    return f"""
        QMenu {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {fill(t.top, alpha[0])}, stop:.56 {fill(t.base, alpha[1])}, stop:1 {fill(t.bottom, alpha[2])});
            color: {t.text}; border: 1px solid {t.border}; border-radius: 13px;
            padding: 5px;
        }}
        QMenu::item {{ padding: 5px 27px 5px 10px; border-radius: 6px; }}
        QMenu::item:selected {{ background: {t.hover}; }}
        QMenu::item:disabled {{ color: {t.muted}; }}
        QMenu::separator {{ height: 1px; background: {t.line}; margin: 4px 7px; }}
        QMenu::indicator {{ width: 13px; height: 13px; left: 4px; }}
    """


def line_icon(kind, checked=False):
    pixmap = QPixmap(32, 32)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    with QPainter(pixmap) as p:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tint = {"春": "#bd5283", "夏": "#338466", "秋": "#a7542c", "冬": "#2c70ae", "夜空": "#4663ab"}.get(kind, palette().icon)
        p.setPen(QPen(QColor(tint), 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath()

        def stroke(*points):
            path.moveTo(*points[0])
            for point in points[1:]:
                path.lineTo(*point)

        if kind in {"follow", "locate", "show", "size"}:
            if kind in {"follow", "locate"}:
                p.drawEllipse(QPointF(8, 8), 5.5, 5.5)
            if kind == "follow":
                stroke((7, 5.5), (10.7, 8), (7, 10.5), (7, 5.5))
            elif kind == "locate":
                for a, b in (((1, 8), (5, 8)), ((11, 8), (15, 8)), ((8, 1), (8, 5)), ((8, 11), (8, 15))):
                    stroke(a, b)
                p.drawEllipse(QPointF(8, 8), 1.4, 1.4)
            elif kind == "size":
                stroke((3, 6), (3, 3), (6, 3))
                stroke((10, 13), (13, 13), (13, 10))
                stroke((4, 12), (12, 4))
                stroke((8.5, 4), (12, 4), (12, 7.5))
            else:
                path.addRoundedRect(QRectF(2, 4, 12, 8), 2, 2)
                p.drawEllipse(QPointF(8, 8), 1.8, 1.8)
        elif kind == "city":
            path.moveTo(8, 14)
            path.cubicTo(6, 11, 3.8, 9, 3.8, 6.4)
            path.cubicTo(3.8, .8, 12.2, .8, 12.2, 6.4)
            path.cubicTo(12.2, 9, 10, 11, 8, 14)
            p.drawEllipse(QPointF(8, 6.5), 1.35, 1.35)
        elif kind == "shuffle":
            stroke((2, 4), (4.7, 4), (11.3, 12), (14, 12))
            stroke((2, 12), (4.7, 12), (6.2, 10.2))
            stroke((9.8, 5.8), (11.3, 4), (14, 4))
            stroke((12, 2), (14, 4), (12, 6))
            stroke((12, 10), (14, 12), (12, 14))
        elif kind == "clock":
            p.drawEllipse(QPointF(8, 8), 5.5, 5.5)
            stroke((8, 4.5), (8, 8), (10.6, 9.4))
        elif kind == "weather":
            path.moveTo(4.3, 12.5)
            path.cubicTo(.2, 12.5, .5, 7, 4.5, 7)
            path.cubicTo(5.4, 2.2, 11.5, 2.6, 12.1, 7.4)
            path.cubicTo(16.3, 7.6, 16, 12.5, 12.4, 12.5)
            path.closeSubpath()
        elif kind == "scenes":
            path.addRoundedRect(QRectF(2, 3, 12, 10), 1.8, 1.8)
            stroke((2.8, 11.2), (6.1, 7.8), (8, 9.6), (10.1, 7.5), (13.2, 10.9))
            p.drawEllipse(QPointF(10.4, 5.8), .65, .65)
        elif kind == "tray":
            stroke((2, 8), (4, 3.5), (12, 3.5), (14, 8), (14, 13), (2, 13), (2, 8),
                   (5.3, 8), (6.4, 10), (9.6, 10), (10.7, 8), (14, 8))
        elif kind == "quit":
            p.drawArc(QRectF(2.6, 3, 10.8, 10.8), 132 * 16, 276 * 16)
            stroke((8, 1.8), (8, 7.5))
        elif kind == "pin":
            p.drawEllipse(QPointF(8, 8), 5.7, 5.7)
            if checked:
                stroke((5.2, 8), (7.1, 9.9), (11, 6))
            else:
                p.drawEllipse(QPointF(8, 8), 1, 1)
        elif kind == "夜空":
            path.moveTo(9.8, 2.3)
            path.cubicTo(3.6, 1.2, .8, 8, 4.1, 11.9)
            path.cubicTo(6.6, 15, 12.1, 14.3, 13.7, 9.6)
            path.cubicTo(8.4, 11.5, 5.8, 5.8, 9.8, 2.3)
        elif kind == "冬":
            stroke((8, 1.7), (8, 14.3))
            stroke((2.5, 4.8), (13.5, 11.2))
            stroke((2.5, 11.2), (13.5, 4.8))
            stroke((6, 3), (8, 4.5), (10, 3))
            stroke((6, 13), (8, 11.5), (10, 13))
        elif kind == "春":
            for x, y in ((8, 4), (11.6, 7), (10.2, 11), (5.8, 11), (4.4, 7)):
                p.drawEllipse(QPointF(x, y), 2.25, 2.25)
        else:
            path.moveTo(3, 13)
            path.cubicTo(1.4, 6, 6, 3, 13.7, 2.8)
            path.cubicTo(14, 10.2, 8.5, 14, 3, 13)
            stroke((2, 14), (10.6, 6))
        p.drawPath(path)
    return QIcon(pixmap)


class FluentMenu(QMenu):
    def __init__(self, parent=None, title=""):
        super().__init__(title, parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFont(font("menu"))
        themed(self, menu_style)
        self.aboutToShow.connect(self.refresh_icons)

    def item(self, label, kind, callback=None):
        action = self.addAction(line_icon(kind), label)
        action.setProperty("pearlIcon", kind)
        if callback is not None:
            action.triggered.connect(callback)
        return action

    def submenu(self, label, kind):
        child = FluentMenu(self, label)
        child.setIcon(line_icon(kind))
        self.addMenu(child).setProperty("pearlIcon", kind)
        return child

    def refresh_icons(self):
        for action in self.actions():
            kind = action.property("pearlIcon")
            if kind:
                action.setIcon(line_icon(kind, action.isChecked()))

    def showEvent(self, event):
        super().showEvent(event)
        if isinstance(self.parentWidget(), QMenu):
            QTimer.singleShot(0, self, self.clamp_to_work_area)

    def clamp_to_work_area(self):
        if not self.isVisible():
            return
        parent = self.parentWidget()
        screen = QApplication.screenAt(parent.frameGeometry().center()) or parent.screen()
        area = screen.availableGeometry()
        self.move(max(area.left(), min(self.x(), area.right() + 1 - self.width())),
                  max(area.top(), min(self.y(), area.bottom() + 1 - self.height())))

    def status(self, width=280, wrap=True):
        label = QLabel(self)
        label.setFont(font("hint"))
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(wrap)
        label.setFixedWidth(width)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        themed(label, lambda: f"background: transparent; color: {palette().muted}; padding: 5px 8px;")
        action = QWidgetAction(self)
        action.setDefaultWidget(label)
        self.addAction(action)
        self.addSeparator()
        return label

    def popup_at(self, pos):
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        area = screen.availableGeometry()

        def place(size):
            width, height = size.width(), size.height()
            x = pos.x() if pos.x() + width <= area.right() + 1 else pos.x() - width
            y = pos.y() if pos.y() + height <= area.bottom() + 1 else pos.y() - height
            return QPoint(max(area.left(), x), max(area.top(), y))

        self.popup(place(self.sizeHint()))
        # Qt may recompute a wrapping status label after the native popup appears.
        QTimer.singleShot(0, self, lambda: self.move(place(self.size())) if self.isVisible() else None)
