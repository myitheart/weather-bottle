"""Glass, scene compositing and animation for the desktop widget."""
from collections import OrderedDict
from math import pi, sin
from random import Random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient

from landscape import WATER, cloud, color, draw_land, ellipse, linear, mix, raster, tree
from scenes import PALETTES, WEATHER, draw_air, draw_sky


def bottle_path(d=0):
    path = QPainterPath(QPointF(58 + d, 29 + d))
    path.lineTo(102 - d, 29 + d)
    path.lineTo(102 - d, 42)
    path.cubicTo(102 - d, 56, 135 - d, 53, 135 - d, 88)
    path.lineTo(135 - d, 147 - d * 0.48)
    path.cubicTo(135 - d, 170 - d * 0.8, 126 - d, 178 - d, 106, 178 - d)
    path.lineTo(54, 178 - d)
    path.cubicTo(34 + d, 178 - d, 25 + d, 170 - d * 0.8, 25 + d, 147 - d * 0.48)
    path.lineTo(25 + d, 88)
    path.cubicTo(25 + d, 53, 58 + d, 56, 58 + d, 42)
    path.closeSubpath()
    return path


OUTLINE = bottle_path()
INSIDE = bottle_path(5.1)


def reflection(p, start, curves, brush, width):
    path = QPainterPath(QPointF(*start))
    for curve in curves:
        path.cubicTo(*curve)
    p.setPen(QPen(brush, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)


def draw_back(p):
    p.save()
    p.translate(80, 179)
    p.scale(1, 0.13)
    shadow = QRadialGradient(0, 0, 73)
    shadow.setColorAt(0, QColor(13, 27, 46, 122))
    shadow.setColorAt(0.55, QColor(17, 36, 57, 69))
    shadow.setColorAt(1, QColor(17, 36, 57, 0))
    ellipse(p, 0, 0, 73, 73, shadow)
    p.restore()
    p.fillPath(OUTLINE, linear(25, 0, 135, 0, "#7fa5c7", "#395e83", "#537e9e", "#9ebdd4"))


def draw_front(p):
    clear = QColor(144, 205, 231, 0)
    glass = linear(25, 0, 135, 0,
                   (0, QColor("#c6e6f4")), (.025, color("#fcf0e5", 245)), (.047, color("#739ab6", 219)),
                   (.074, color("#e5f6ff", 172)), (.13, clear), (.55, clear), (.86, clear),
                   (.93, color("#a9e0f2", 104)), (.962, color("#dff9ff", 223)), (.984, color("#6b96b8", 202)),
                   (1, color("#e3f5fc", 236)))
    p.fillPath(OUTLINE, glass)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(linear(26, 54, 130, 178, "#e6f7ff", "#b7dbf0", "#eaf9ff"), .62))
    p.drawPath(OUTLINE)
    p.setPen(QPen(linear(22, 61, 134, 149, color("#fff8e7", 171), color("#a7ddf6", 5), color("#f7fdff", 167)), .68))
    p.drawPath(bottle_path(4.75))
    p.setPen(Qt.PenStyle.NoPen)
    reflection(p, (64, 36), [(65, 60, 55, 52, 42, 68), (31, 80, 33, 94, 34, 112)],
               linear(0, 37, 0, 113, color("#cdeaff", 15), color("#fff4e1", 222), color("#e3f5ff", 0)), 3.5)
    reflection(p, (61, 37), [(60, 57, 47, 53, 34, 73), (25, 84, 29, 113, 29, 133)],
               linear(0, 46, 0, 132, color("#e7faff", 30), color("#fff9ed", 243), color("#e1f4ff", 0)), 1.1)
    reflection(p, (97, 36), [(97, 58, 112, 57, 124, 75), (133, 89, 130, 115, 130, 139)],
               linear(0, 37, 0, 140, color("#c6f5ff", 132), color("#daf7ff", 117), clear), 2.1)
    p.save()
    p.setClipPath(OUTLINE)
    p.fillRect(QRectF(22, 161, 116, 17), linear(0, 161, 0, 178, clear, color("#9dd3ec", 40),
                                               color("#192e49", 180), color("#9ac4d9", 230)))
    reflection(p, (32, 154), [(35, 172, 48, 173, 78, 173), (110, 174, 127, 171, 131, 154)],
               linear(32, 0, 131, 0, (0, color("#ffe4c7", 178)), (.32, color("#9ed7ee", 62)),
                      (.66, color("#def9ff", 151)), (1, QColor("#fff4e6"))), 1.75)
    reflection(p, (44, 173), [(61, 178, 101, 178, 118, 173)],
               linear(44, 0, 118, 0, clear, color("#dffaff", 244), clear), .95)
    p.restore()

    # The glass lip and silver collar stay attached to the neck.
    p.setBrush(linear(0, 27, 0, 38, "#becdde", "#485c76", "#293e59", "#849db2"))
    p.drawRoundedRect(QRectF(57, 27, 46, 11), 3, 3)
    p.setBrush(linear(0, 27, 0, 34, "#fff7e5", "#c6ae9f", "#576b85", "#e2e5e8"))
    p.drawRoundedRect(QRectF(54, 27, 52, 6), 2.7, 2.7)


def draw_cap(p):
    p.setBrush(linear(0, 10, 0, 29, "#fffdfa", "#e4eef6", "#a8bed4", "#6e89a7", "#d7c7bc"))
    p.drawRoundedRect(QRectF(51, 10, 58, 18.8), 7.2, 7.2)
    cap_glint = QRadialGradient(54, 9, 39)
    cap_glint.setColorAt(0, QColor("#fffdf0"))
    cap_glint.setColorAt(.5, color("#fff5e7", 122))
    cap_glint.setColorAt(1, color("#fff5e7", 0))
    p.setBrush(cap_glint)
    p.drawRoundedRect(QRectF(51, 10, 58, 18.8), 7.2, 7.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(linear(51, 10, 109, 29, "#fffefa", "#d8efff", "#ece2dd"), .72))
    p.drawRoundedRect(QRectF(51.25, 10.25, 57.5, 18.3), 7, 7)
    p.setPen(Qt.PenStyle.NoPen)


class BottleRenderer:
    def __init__(self):
        self.dpr = 0
        self.scenes = OrderedDict()
        rng = Random(184)
        self.drops = [(rng.uniform(29, 156), rng.random(), rng.uniform(0.57, 1.13)) for _ in range(62)]
        self.lake_drops = []
        while len(self.lake_drops) < 12:
            x, y = rng.uniform(48, 128), rng.uniform(133, 168)
            if WATER.contains(QPointF(x, y)):
                self.lake_drops.append((x, y, rng.random(), rng.uniform(.65, 1.1)))

    def prepare(self, dpr):
        dpr = round(max(1.5, min(dpr, 3.0)), 2)
        if dpr != self.dpr:
            self.dpr = dpr
            self.scenes.clear()
            self.back = raster(dpr, draw_back)
            self.front = raster(dpr, draw_front)
            self.cap = raster(dpr, draw_cap)
            self.clouds = (cloud(dpr), cloud(dpr, dark=True))

    def scenery(self, key):
        if key in self.scenes:
            self.scenes.move_to_end(key)
            return self.scenes[key]
        scene = WEATHER[key]
        sky, horizon, glow, *_ = PALETTES[scene.palette]
        if key == "sun":
            sky, horizon = "#367bae", "#c1e4de"
        elif key in {"rain", "shower"}:
            sky, horizon = "#2b4e77", "#b5d7e1"
        elif key == "dusk":
            sky, horizon = "#555b9a", "#ffc09b"
        layers = (linear(0, 44, 0, 132, sky, mix(sky, horizon, 0.62), horizon),
                  raster(self.dpr, lambda p: draw_land(p, key)), tree(self.dpr, key), glow)
        self.scenes[key] = layers
        if len(self.scenes) > 6:
            self.scenes.popitem(last=False)
        return layers

    def snapshot(self, key, t, tilt, previous=None, opacity=0):
        return raster(self.dpr, lambda p: self.interior(p, key, t, tilt, previous, opacity))

    def interior(self, p, key, t, tilt, previous=None, opacity=0):
        scene = WEATHER[key]
        sky, land, canopy, light = self.scenery(key)
        # All dynamic scenery shares one aperture. Glass is composited afterwards.
        p.save()
        p.setClipPath(INSIDE, Qt.ClipOperation.IntersectClip)
        p.fillRect(QRectF(21, 30, 118, 147), sky)
        if scene.sky in {"sun", "moon", "stars", "aurora"}:
            draw_sky(p, scene, light, t, tilt)
        elif scene.sky == "thunder":
            pulse = (t + 4) % 10.7
            if pulse < .33:
                flash = sin(pi * pulse / .33)
                p.fillRect(QRectF(24, 30, 112, 116), color("#bbd6ff", int(61 * flash)))
                reflection(p, (96, 64), [(94, 71, 90, 76, 88, 81), (92, 79, 92, 79, 95, 79),
                                          (93, 85, 90, 92, 86, 98)], color("#eaf6ff", int(227 * flash)), .9)
        self.draw_clouds(p, key, t, tilt)
        if scene.sky == "rainbow":
            draw_sky(p, scene, light, t, tilt)
        p.drawPixmap(0, 0, land)
        self.draw_water(p, key, t)
        if scene.mist or scene.rain or scene.sky == "cloud":
            for i in range(2):
                p.save()
                p.translate(62 + i * 42 + sin(t * .20 + i * 2) * 14, 116 + i * 12)
                p.scale(39 - 4 * i, 3.4 + i)
                haze = QRadialGradient(0, 0, 1)
                haze.setColorAt(0, color("#d6edf1", int(25 + 85 * scene.mist + 15 * min(scene.rain, 1))))
                haze.setColorAt(1, color("#d6edf1", 0))
                ellipse(p, 0, 0, 1, 1, haze)
                p.restore()
        for x, y, scale, phase in ((46, 151, .43, 1.5), (118, 141, .88, 0)):
            p.save()
            p.translate(x, y)
            p.rotate(sin(t * .95 + phase) * (1.0 + 1.1 * scene.rain) + tilt * .09)
            p.scale(scale, scale)
            p.drawPixmap(-22, -37, canopy)
            p.restore()
        if scene.rain:
            self.draw_rain(p, scene.rain, t, tilt)
        if scene.air:
            draw_air(p, scene.air, t, tilt)
        p.restore()
        if previous is not None and opacity > 0:
            p.setOpacity(opacity)
            p.drawPixmap(0, 0, previous)
            p.setOpacity(1)

    def draw_clouds(self, p, key, t, tilt):
        scene = WEATHER[key]
        if scene.sky in {"moon", "stars", "aurora"} and key != "icefog":
            return
        dark = scene.rain > .48 or scene.palette in {"cloud", "fog", "ice"}
        sprite = self.clouds[int(dark)]
        source = QRectF(sprite.rect())
        banks = ((44, 89, 64, .55), (102, 75, 91, .96), (124, 89, 56, .72))
        for i, (x, y, width, speed) in enumerate(banks):
            if key == "dusk":
                x, y = x - 49 - i * 3, y + 15 + i * 2
                width *= .80
            elif key in {"sun", "heat"} and i == 1:
                x, y, width = 108, 65, 65
            dx = sin(t * .13 * speed + i * .9) * (10 + i * 3) + tilt * (.07 + i * .025)
            p.setOpacity((.61, .93, .63)[i] * (.69 if key == "dusk" else 1))
            p.drawPixmap(QRectF(x - width / 2 + dx, y - width * .26, width, width * .525), sprite, source)
        p.setOpacity(1)

    def draw_water(self, p, key, t):
        scene = WEATHER[key]
        light = PALETTES[scene.palette][2]
        p.save()
        p.setClipPath(WATER, Qt.ClipOperation.IntersectClip)
        if scene.sky in {"sun", "moon"}:
            if key == "dusk":
                p.save()
                p.translate(96, 149)
                p.scale(1, 0.39)
                reflection_glow = QRadialGradient(0, 0, 27)
                reflection_glow.setColorAt(0, color("#ffd891", 143))
                reflection_glow.setColorAt(1, color("#ffbe8a", 0))
                ellipse(p, 0, 0, 27, 27, reflection_glow)
                p.restore()
            for i in range(15):
                y = 130 + i * 2.7
                width = (1.8 + .43 * i) * (.66 + .32 * sin(i * 2.8 + t * 1.3))
                ellipse(p, 96 + sin(t * .53 + i) * 1.3, y, width, .31 + .009 * i,
                        color(light, max(16, 124 - 6 * i)))
        for i in range(10):
            y = 133 + (i * 13 % 38)
            x = 36 + (i * 39 % 98) + sin(t * .65 + i) * 5
            ellipse(p, x, y, 1.2 + y * .019, .20,
                    color("#e1f9ff", int(30 + 19 * sin(t * 1.32 + i * 1.6))))
        if scene.rain:
            for x, y, cycle in self.lake_impacts(scene.rain, t):
                if cycle < .59:
                    continue
                phase = (cycle - .59) / .41
                r = 0.5 + phase * (2 + (y - 130) * .17)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(color("#dcf7ff", int(162 * (1 - phase))), .47))
                p.drawEllipse(QPointF(x, y), r, r * .28)
            p.setPen(Qt.PenStyle.NoPen)
        p.restore()

    def lake_impacts(self, amount, t):
        for x, y, offset, speed in self.lake_drops[:max(2, round(amount * 8))]:
            yield x, y, (t * (.7 + amount * .2) * speed + offset) % 1

    def draw_rain(self, p, amount, t, tilt):
        for x, offset, speed in self.drops[:round(amount * 40)]:
            phase = (t * (.85 + amount * .23) * speed + offset) % 1
            y = 43 + phase * 120
            x -= phase * (12 + amount * 4)
            length = (4 + amount * 7) * speed
            opacity = int(min(156, 32 + amount * 75) * min(phase * 12, (1 - phase) * 8, 1))
            pen = QPen(linear(x, y, x - length * .26, y + length, color("#d7f5ff", 0),
                              color("#e3f7ff", opacity)), .36 + amount * .16)
            p.setPen(pen)
            p.drawLine(QPointF(x, y), QPointF(x - length * .26 + tilt * .045, y + length))
        for x, y, cycle in self.lake_impacts(amount, t):
            if cycle >= .59:
                continue
            remaining = 1 - cycle / .59
            tail = min(7, cycle * 82)
            tip = QPointF(x + remaining * 15, y - remaining * 96)
            p.setPen(QPen(color("#d7f5ff", int(84 + amount * 27)), .52))
            p.drawLine(QPointF(tip.x() + tail * .16, tip.y() - tail), tip)
        p.setPen(Qt.PenStyle.NoPen)

    def paint(self, p, key, t, tilt=0, hover=0, previous=None, opacity=0, *, cap_open=0., cap_side=1):
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPixmap(0, 0, self.back)
        self.interior(p, key, t, tilt, previous, opacity)
        p.drawPixmap(0, 0, self.front)
        self.paint_cap(p, cap_open, cap_side)
        scene = WEATHER[key]
        if scene.rain:
            p.save()
            p.setClipPath(INSIDE, Qt.ClipOperation.IntersectClip)
            for i, (x, y, radius) in enumerate(((38, 107, 1.2), (125, 100, .8), (121, 118, 1.1), (36, 126, .68))):
                if scene.rain < .6 and i > 1:
                    break
                tint = QRadialGradient(x, y, radius * 1.55, x - radius * .3, y - radius * .6)
                tint.setColorAt(0, color("#e9faff", 163))
                tint.setColorAt(.5, color("#79a7c9", 36))
                tint.setColorAt(1, color("#1c3f5d", 99))
                ellipse(p, x, y, radius, radius * 1.23, tint)
            p.restore()
        alpha = int(19 + 12 * sin(t * .72) + 61 * hover)
        if scene.sky == "sun":
            tint = "#fff0d5"
            alpha += 27
        else:
            tint = "#d5f3ff"
        reflection(p, (34, 92), [(34, 74, 44, 65, 55, 59)],
                   linear(0, 57, 0, 92, color(tint, 0), color(tint, alpha), color(tint, 0)), 1.9)

    def paint_cap(self, p, amount, side):
        if amount == 0.:
            p.drawPixmap(0, 0, self.cap)
            return

        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.translate(80 + 10 * side, 27)
        p.scale(1, .30)
        halo = QRadialGradient(0, 0, 27)
        halo.setColorAt(0, color("#fff3ce", round(226 * amount)))
        halo.setColorAt(.42, color("#ffc478", round(122 * amount)))
        halo.setColorAt(1, color("#ffc478", 0))
        ellipse(p, 0, 0, 27, 27, halo)
        p.restore()

        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pivot = 80 - 24 * side
        p.translate(pivot + side * amount, 26 - 3.5 * amount)
        p.rotate(-side * 5.5 * amount)
        p.translate(-pivot, -26)
        p.drawPixmap(0, 0, self.cap)
        p.restore()

