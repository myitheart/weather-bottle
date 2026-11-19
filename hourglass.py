"""Procedural glass and gold sand for the focus hourglass."""
from math import pi, sin, sqrt
from random import Random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QRadialGradient

from typography import draw_number
from landscape import color, ellipse, linear, raster


BOTTLE = (
    (58, 29), (102, 29), (102, 42),
    (102, 56), (135, 53), (135, 88),
    (135, 98), (135, 108), (135, 117),
    (135, 127), (135, 137), (135, 147),
    (135, 170), (126, 178), (106, 178),
    (89, 178), (71, 178), (54, 178),
    (34, 178), (25, 170), (25, 147),
    (25, 137), (25, 127), (25, 117),
    (25, 108), (25, 98), (25, 88),
    (25, 53), (58, 56), (58, 42),
)
HOURGLASS = (
    (39, 24), (121, 24), (125, 31),
    (146, 67), (109, 82), (90, 99),
    (85, 103), (84, 106), (90, 111),
    (106, 126), (137, 140), (132, 162),
    (130, 170), (125, 177), (112, 177),
    (91, 177), (69, 177), (48, 177),
    (35, 177), (30, 170), (28, 162),
    (23, 140), (54, 126), (70, 111),
    (76, 106), (75, 103), (70, 99),
    (51, 82), (14, 67), (35, 31),
)
_rng = Random(171)
GRAINS = [(_rng.random(), _rng.uniform(-1.4, 1.4), _rng.random()) for _ in range(27)]
DUST = [(_rng.uniform(24, 136), _rng.uniform(38, 172), _rng.uniform(.13, .53), _rng.randrange(32, 170))
        for _ in range(1400)]


def morph_points(amount, inset=0):
    return [
        QPointF(80 + (x + (ex - x) * amount - 80) * (1 - inset),
                102 + (y + (ey - y) * amount - 102) * (1 - inset * .48))
        for (x, y), (ex, ey) in zip(BOTTLE, HOURGLASS, strict=True)
    ]


def outline_for(points):
    path = QPainterPath(points[0])
    path.lineTo(points[1])
    path.lineTo(points[2])
    for i in range(3, len(points), 3):
        path.cubicTo(*points[i:i + 3])
    path.lineTo(points[0])
    path.closeSubpath()
    return path


def morph_outline(amount):
    return outline_for(morph_points(amount))


def glow(p, x, y, radius, tint, alpha):
    light = QRadialGradient(x, y, radius)
    light.setColorAt(0, color(tint, alpha))
    light.setColorAt(.32, color(tint, round(alpha * .43)))
    light.setColorAt(1, color(tint, 0))
    ellipse(p, x, y, radius, radius, light)


def edge(p, points, start, end, brush, width):
    path = QPainterPath(points[start])
    for i in range(start + 1, end + 1, 3):
        path.cubicTo(*points[i:i + 3])
    p.setPen(QPen(brush, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(path)


def paint_glass_back(p, amount):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.translate(80, 182)
    p.scale(1, .105)
    glow(p, 0, 0, 73, "#132c4b", 193)
    glow(p, -23, -6, 37, "#ffd89a", 86)
    p.restore()
    path = morph_outline(amount)
    p.fillPath(path, linear(25, 29, 136, 174,
                           (0, color("#7ca6d1", 201)), (.28, color("#234c7e", 195)),
                           (.52, color("#183c68", 187)), (.77, color("#4b80ad", 176)),
                           (1, color("#badcee", 198))))
    p.save()
    p.setClipPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    glow(p, 108, 76, 71, "#8dbce8", 110)
    glow(p, 72, 154, 44, "#ffd395", 48)
    p.restore()


def paint_glass_front(p, amount):
    points = morph_points(amount)
    inset = morph_points(amount, .16)
    path = outline_for(points)
    p.setBrush(Qt.BrushStyle.NoBrush)
    rim = linear(32, 29, 121, 174, "#fff5df", "#acd9f3", "#ffe4ae", "#deeff9", "#fff6dc")
    p.setPen(QPen(linear(25, 0, 135, 0, color("#eff8ff", 161), color("#76a7d6", 60),
                         color("#b9e2fb", 63), color("#e7f5ff", 167)), 5.1))
    p.drawPath(path)
    p.setPen(QPen(rim, .88))
    p.drawPath(path)
    p.save()
    p.setClipPath(path, Qt.ClipOperation.IntersectClip)
    # Broad window reflections sit inside the glass wall and taper at the waist.
    gleam = QPainterPath(QPointF(35, 38))
    gleam.cubicTo(32, 58, 37, 72, 48, 82)
    gleam.cubicTo(40, 64, 44, 51, 51, 38)
    gleam.closeSubpath()
    p.fillPath(gleam, linear(35, 38, 53, 81, color("#f6f4f1", 151), color("#cde7ff", 55), color("#d4edff", 0)))
    gleam = QPainterPath(QPointF(40, 167))
    gleam.cubicTo(33, 149, 54, 133, 62, 128)
    gleam.cubicTo(54, 142, 49, 155, 52, 166)
    gleam.closeSubpath()
    p.fillPath(gleam, linear(37, 147, 58, 161, color("#edf6ff", 137), color("#cae9fd", 40), color("#d4edff", 0)))
    inset_rim = linear(0, 31, 0, 176, color("#eff8ff", 151), color("#b2dcfd", 9), color("#eff8ff", 105))
    p.setPen(QPen(inset_rim, .86))
    p.drawPath(outline_for(inset))
    edge(p, inset, 26, 29, linear(0, 32, 0, 92, color("#f1f5ff", 224), color("#e6f5ff", 0)), 3.6)
    edge(p, inset, 23, 26, linear(0, 64, 0, 99, color("#e4f3ff", 36), color("#ffe0b1", 173)), 1.25)
    edge(p, inset, 5, 11, linear(0, 79, 0, 147, color("#f6fcff", 21), color("#c2e2ff", 205)), 1.8)
    edge(p, inset, 20, 23, linear(0, 106, 0, 155, color("#ecf7ff", 40), color("#f9f8e8", 203)), 3.3)
    p.restore()
    p.setPen(Qt.PenStyle.NoPen)
    for x, y, w, h in ((51 - 16 * amount, 10 + 4 * amount, 58 + 32 * amount, 18 - 5 * amount),
                       (33 - 3 * amount, 174 - 2 * amount, 94 + 6 * amount, 12)):
        box = QRectF(x, y, w, h)
        p.setBrush(linear(0, y, 0, y + h, "#fff8ee", "#dce9f9", "#87a3ca", "#526b94", "#d9b994"))
        p.drawRoundedRect(box, h / 2, h / 2)
        p.save()
        cap = QPainterPath()
        cap.addRoundedRect(box, h / 2, h / 2)
        p.setClipPath(cap)
        glow(p, x + 11, y + h * .68, 34, "#ffe6bf", 143)
        glow(p, x + w * .76, y + 2, 25, "#e7f5ff", 156)
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(linear(x, y, x + w, y + h, "#fff3da", "#d5e8ff", "#a7bdd4"), .68))
        p.drawRoundedRect(box.adjusted(.3, .3, -.3, -.3), h / 2, h / 2)
        p.setPen(Qt.PenStyle.NoPen)


def sand_path(surface, sides, bottom):
    path = QPainterPath(QPointF(*surface[0]))
    path.cubicTo(*surface[1])
    path.cubicTo(*surface[2])
    path.lineTo(sides[1], bottom)
    path.lineTo(sides[0], bottom)
    path.closeSubpath()
    return path


def paint_sand(p, aperture, progress, time, flowing, finished, resting, grain_texture):
    p.save()
    p.setClipPath(aperture, Qt.ClipOperation.IntersectClip)
    p.setPen(Qt.PenStyle.NoPen)
    warm = "#b6e4fb" if resting else "#ffd993"
    glow(p, 79, 104, 39, warm, int(88 + 13 * sin(time * 1.45)))
    height = 47 * sqrt(progress)
    top = 103 - height
    drift = sin(time * .92) * .58 if flowing else 0
    upper = sand_path(((28, top + 2), (48, top - 6, 58, top - 4, 82, top + 1 + drift),
                       (101, top + 6, 114, top + 1, 132, top - 1)), (28, 132), 107)
    rise = 36 * sqrt(1 - progress)
    peak = 170 - rise
    lower = sand_path(((23, 169 - rise * .22), (47, 167 - rise * .25, 63, peak - 2, 80, peak + drift),
                       (94, peak - 1, 112, 169 - rise * .37, 137, 166 - rise * .14)), (23, 137), 180)
    layers = []
    if progress > .002:
        layers.append((upper, top, 106, min(1, progress * 42)))
    if rise > .8:
        layers.append((lower, peak, 176, min(1, rise / 4)))
    for path, y, base, opacity in layers:
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        p.fillPath(path, linear(0, y, 0, base, "#e0f4ff" if resting else "#ffe3ac",
                                "#76aeca" if resting else "#e8a55b", "#44778f" if resting else "#b1713d"))
        glow(p, 73, y + 3, 42, "#d8efff" if resting else "#fff6ca", 164)
        p.drawPixmap(0, 0, grain_texture)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(linear(35, 0, 127, 0, color(warm, 49), "#fff0ce", color(warm, 63)), 1.15))
        p.drawPath(path)
        p.restore()

    if flowing:
        end = max(114, peak + 1)
        p.setPen(QPen(linear(0, 105, 0, end, color(warm, 122), color(warm, 218), color(warm, 75)), .75))
        p.drawLine(QPointF(80, 105), QPointF(80.15, end))
        p.setPen(Qt.PenStyle.NoPen)
        for phase, offset, size in GRAINS:
            fall = (phase + time * 1.08) % 1
            ellipse(p, 80 + offset * fall, 106 + fall * (end - 106),
                    .22 + .35 * size, .45 + .39 * size, color("#fff2ca", int(96 + 152 * size)))
        glow(p, 80, end, 7, warm, 138)

    for index, (phase, offset, size) in enumerate(GRAINS[:10]):
        lift = (phase + time * (.18 if finished else .064)) % 1
        x = 80 + offset * (12 + 15 * lift) + sin(time * .48 + index) * 2
        y = 159 - 127 * lift
        ellipse(p, x, y, .23 + size * .64, .23 + size * .64, color(warm, int((190 if finished else 100) * sin(pi * lift))))
    p.restore()


class HourglassRenderer:
    def __init__(self):
        self.dpr = 0

    def prepare(self, dpr):
        dpr = round(max(1.5, min(dpr, 3)), 2)
        if dpr != self.dpr:
            self.dpr = dpr
            self.back = raster(dpr, lambda p: paint_glass_back(p, 1))
            self.front = raster(dpr, lambda p: paint_glass_front(p, 1))
            self.aperture = outline_for(morph_points(1, .077))
            self.grain_texture = raster(dpr, self.paint_grain_texture)

    @staticmethod
    def paint_grain_texture(p):
        for x, y, radius, alpha in DUST:
            ellipse(p, x, y, radius, radius * .86, color("#fff7df" if alpha > 83 else "#704325", alpha))

    def paint(self, p, amount, progress, time, flowing, finished, clock_text, hover, resting):
        p.save()
        p.setOpacity(amount)
        if amount == 1:
            aperture = self.aperture
            p.drawPixmap(0, 0, self.back)
        else:
            aperture = outline_for(morph_points(amount, .077))
            paint_glass_back(p, amount)
        paint_sand(p, aperture, progress, time, flowing, finished, resting, self.grain_texture)
        if amount == 1:
            p.drawPixmap(0, 0, self.front)
        else:
            paint_glass_front(p, amount)
        p.save()
        p.setClipPath(aperture, Qt.ClipOperation.IntersectClip)
        p.setPen(Qt.PenStyle.NoPen)
        glow(p, 43, 48, 19, "#edf7ff", round(33 + 13 * sin(time * .86)))
        p.restore()
        if .02 < amount < .92:
            p.setPen(Qt.PenStyle.NoPen)
            glow(p, 80, 78 + 29 * amount, 19, "#ffdb98", round(135 * sin(pi * amount)))
        if hover > .01 and clock_text:
            p.setOpacity(amount * hover)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color("#142638", 228))
            p.drawRoundedRect(QRectF(52, 139, 56, 25), 9, 9)
            p.setPen(QColor("#d8f2ff" if resting else "#fff3d6"))
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            role = "hourglass_clock_compact" if len(clock_text) > 6 else "hourglass_clock"
            draw_number(p, QRectF(52, 139, 56, 25), clock_text, role, center=True)
        p.restore()

