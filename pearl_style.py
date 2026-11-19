"""Shared Dynamic Pearl theme, glass surfaces and transparent animation frames."""
from dataclasses import dataclass
from functools import lru_cache
from weakref import WeakKeyDictionary

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainterPath, QPalette, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QToolTip, QWidget
from shiboken6 import isValid

from landscape import color, linear


@dataclass(frozen=True)
class Palette:
    text: str
    muted: str
    warm: str
    success: str
    error: str
    ice: str
    top: str
    base: str
    bottom: str
    border: str
    highlight: str
    control: str
    hover: str
    pressed: str
    selected: str
    primary: str
    primary_hover: str
    line: str
    icon: str


DARK = Palette("#f4f7fb", "#afc0d3", "#ffd198", "#78dfac", "#ffabab", "#afd9fb",
               "#35495f", "#192c40", "#274058", "rgba(185,213,242,85)", "#d7e9fc",
               "rgba(160,190,220,23)", "rgba(166,199,235,45)", "rgba(139,182,226,54)",
               "rgba(126,175,226,38)", "rgba(255,192,124,51)", "rgba(255,192,124,72)",
               "rgba(205,227,251,31)", "#c7dff6")
LIGHT = Palette("#15283d", "#52677d", "#825016", "#206c48", "#a43540", "#245883",
                "#f8fcff", "#eaf2f8", "#dce9f3", "rgba(103,142,177,101)", "#ffffff",
                "rgba(83,130,174,15)", "rgba(75,139,194,28)", "rgba(55,122,187,41)",
                "rgba(82,143,203,30)", "rgba(242,166,69,49)", "rgba(242,166,69,68)",
                "rgba(59,108,151,38)", "#315f89")

_palette = DARK
_styles = WeakKeyDictionary()


def palette():
    return _palette


class Tokens:
    BRAND = "灵动珠"
    WIDTH = 316
    RADIUS = 19
    CONTROL_RADIUS = 10
    SHADOW = 9
    PADDING = 17
    GAP = 10
    OPEN_MS = 240
    CLOSE_MS = 180

    @property
    def TEXT(self):
        return palette().text

    @property
    def MUTED(self):
        return palette().muted

    @property
    def GOLD(self):
        return palette().warm

    @property
    def ERROR(self):
        return palette().error

    @property
    def BORDER(self):
        return palette().border


DesignTokens = Tokens()


def apply_appearance(mode):
    global _palette
    app = QApplication.instance()
    light = mode == "light" or (mode == "system" and app is not None
                                and app.styleHints().colorScheme() == Qt.ColorScheme.Light)
    target = LIGHT if light else DARK
    tooltip = QPalette()
    tooltip.setColor(QPalette.ColorRole.ToolTipBase, QColor(target.base))
    tooltip.setColor(QPalette.ColorRole.ToolTipText, QColor(target.text))
    QToolTip.setPalette(tooltip)
    if target == _palette:
        return
    _palette = target
    for widget, sheet in list(_styles.items()):
        if isValid(widget):
            widget.setStyleSheet(sheet())
    if app:
        for widget in app.allWidgets():
            widget.update()


def themed(widget, sheet):
    _styles[widget] = sheet
    widget.setStyleSheet(sheet())


def text_role(widget, role="text"):
    themed(widget, lambda: f"color: {getattr(palette(), role)};")


def snapshot(widget):
    """Render explicitly into a cleared premultiplied buffer without Qt's window brush."""
    dpr = widget.devicePixelRatioF()
    rendered = QPixmap(round(widget.width() * dpr), round(widget.height() * dpr))
    rendered.setDevicePixelRatio(dpr)
    rendered.fill(Qt.GlobalColor.transparent)
    widget.render(rendered, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
    return rendered


@dataclass(frozen=True)
class GlassSurface:
    opacity: tuple[int, int, int]
    shadow: int
    light: int


SURFACES = {
    "capsule": GlassSurface((220, 239, 222), 37, 43),
    "panel": GlassSurface((230, 244, 231), 46, 42),
    "dialog": GlassSurface((240, 249, 239), 43, 31),
    "menu": GlassSurface((240, 250, 242), 37, 28),
    "control": GlassSurface((27, 21, 29), 0, 0),
}


LIGHT_CAPSULE = GlassSurface((207, 224, 202), 32, 76)
LIGHT_CAPSULE_FILL = ("#eff8ff", "#dcebf7", "#b0cde4")


@lru_cache(maxsize=1)
def frost_texture():
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    for y in range(image.height()):
        for x in range(image.width()):
            shade = 255 if (x + 13 * y) % 3 else 18
            alpha = (19 * x + 13 * y + 7 * x * y) % 4
            image.setPixelColor(x, y, QColor(shade, shade, shade, alpha))
    return QBrush(QPixmap.fromImage(image))


def glass(p, box, kind="panel", *, radius=None, reflected_at=None):
    if not box.isValid():
        return
    t = palette()
    light_capsule = kind == "capsule" and t is LIGHT
    surface = LIGHT_CAPSULE if light_capsule else SURFACES[kind]
    corner = min(box.width() / 2, box.height() / 2)
    if radius is not None or kind != "capsule":
        corner = min(corner, radius if radius is not None else DesignTokens.RADIUS)
    outline = QPainterPath()
    outline.addRoundedRect(box, corner, corner)
    if surface.shadow:
        p.fillPath(outline.translated(0, 2.55), color("#0b1421", surface.shadow // 2))
        p.fillPath(outline.translated(0, 1.15), color("#0b1421", surface.shadow // 3))
    a, b, c = surface.opacity
    top, base, bottom = LIGHT_CAPSULE_FILL if light_capsule else (t.top, t.base, t.bottom)
    p.fillPath(outline, linear(box.left(), box.top(), box.right(), box.bottom(),
                              color(top, a), (.52, color(base, b)), color(bottom, c)))
    if surface.light:
        point = reflected_at if reflected_at is not None else QPointF(box.left() + box.width()*.22, box.top())
        highlight = QRadialGradient(point, max(24., box.width()*.53))
        highlight.setColorAt(0, color(t.highlight, surface.light if t is DARK else surface.light + 8))
        if light_capsule:
            highlight.setColorAt(.46, color("#d7eeff", 31))
        highlight.setColorAt(1, color(t.highlight, 0))
        p.fillPath(outline, highlight)
    if light_capsule:
        # A restrained cool refraction at the bottom preserves the pale center behind text.
        p.fillPath(outline, linear(0, box.top(), 0, box.bottom(),
                                  color("#8fb7d6", 0), (.57, color("#91b9dc", 2)),
                                  (.83, color("#8bb5d5", 31)), color("#d4edff", 82)))
    if kind in {"panel", "dialog"}:
        p.fillPath(outline, frost_texture())
    p.setBrush(Qt.BrushStyle.NoBrush)
    if light_capsule:
        edge = linear(0, box.top(), 0, box.bottom(), color("#ffffff", 207),
                      (.46, color("#5f8bb1", 62)), color("#d3eafd", 157))
    else:
        edge = linear(0, box.top(), 0, box.bottom(), color(t.highlight, 137 if t is LIGHT else 96),
                      color(t.icon, 54 if t is LIGHT else 38), color(t.icon, 88))
    p.setPen(QPen(edge, .72))
    p.drawPath(outline)


def css_color(value):
    if value.startswith("rgba("):
        return QColor(*(int(part) for part in value[5:-1].split(",")))
    return QColor(value)


def glyph(p, kind, center, tint, scale=1.):
    p.save()
    p.translate(center)
    p.scale(scale, scale)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(tint), 1.35, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    path = QPainterPath()
    if kind == "play":
        path.moveTo(-2.4, -4)
        path.lineTo(4, 0)
        path.lineTo(-2.4, 4)
        path.closeSubpath()
    elif kind == "pause":
        p.drawLine(QPointF(-2, -3.7), QPointF(-2, 3.7))
        p.drawLine(QPointF(2, -3.7), QPointF(2, 3.7))
    elif kind == "check":
        path.moveTo(-4.1,.15)
        path.lineTo(-1.4,2.9)
        path.lineTo(4.3,-3.)
    elif kind == "stack":
        path.moveTo(0,-4.9)
        path.lineTo(5.6,-1.7)
        path.lineTo(0,1.45)
        path.lineTo(-5.6,-1.7)
        path.closeSubpath()
        path.moveTo(-5.2,1.25)
        path.lineTo(0,4.25)
        path.lineTo(5.2,1.25)
    elif kind == "bell":
        path.moveTo(-4.2,2.3)
        path.cubicTo(-2.4,.6,-3.8,-3.9,0,-4.15)
        path.cubicTo(3.8,-3.9,2.4,.6,4.2,2.3)
        path.closeSubpath()
        p.drawLine(QPointF(-.8,4.2),QPointF(.8,4.2))
    elif kind == "bars":
        for x,h in ((-3.8,2.6),(0,5.2),(3.8,8.1)):
            p.drawLine(QPointF(x,3.8),QPointF(x,3.8-h))
        p.drawLine(QPointF(-5,5),QPointF(5,5))
    elif kind == "pin":
        path.moveTo(-2.5,-4.9)
        path.lineTo(3.8,-3.8)
        path.lineTo(2.2,-.6)
        path.lineTo(3.7,1.8)
        path.lineTo(-3.5,1.8)
        path.lineTo(-1.6,-.8)
        path.closeSubpath()
        p.drawLine(QPointF(0,2),QPointF(0,5.7))
    elif kind == "running":
        p.setPen(QPen(color(tint, 78), 1.35))
        p.drawEllipse(QPointF(),4.6,4.6)
        pen = QPen(QColor(tint), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(-4.6,-4.6,9.2,9.2), 35*16, 215*16)
    else:
        p.drawEllipse(QPointF(),4.8,4.8)
        p.drawLine(QPointF(0,-2.4),QPointF(0,.8))
        p.drawPoint(QPointF(0,2.6))
    p.drawPath(path)
    p.restore()
