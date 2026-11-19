"""Original, cached QPainter artwork in 160 × 198 logical coordinates."""
from math import cos, sin
from random import Random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QPolygonF, QRadialGradient,
)

from scenes import GROUPS, PALETTES, WEATHER


SIZE = (160, 198)
SEASON = {key: season for season, group in GROUPS.items() for key in group}
# Meadow light, meadow shade, canopy light, canopy shade.
PLANTS = {
    "春": ("#9cbd55", "#255f42", "#d9eb82", "#174d39"),
    "夏": ("#95b861", "#216252", "#c3d97d", "#194d4c"),
    "秋": ("#c9a063", "#725649", "#fac47a", "#754737"),
    "冬": ("#e4f4ff", "#7099b4", "#e0f0f8", "#446d83"),
    "夜空": ("#71889b", "#213c51", "#7d9eac", "#182f48"),
}
RIDGES = (
    ((18, 110), (33, 104), (46, 97), (59, 102), (72, 110), (83, 108), (102, 96), (116, 90), (127, 97), (145, 104)),
    ((17, 113), (33, 108), (42, 110), (54, 116), (71, 123), (86, 118), (102, 106), (120, 97), (132, 102), (144, 115)),
    ((16, 129), (30, 127), (43, 120), (54, 116), (65, 120), (77, 126), (88, 130), (104, 126), (125, 113), (147, 119)),
)
LAKE = QPainterPath(QPointF(20, 135))
LAKE.cubicTo(58, 132, 74, 128, 94, 130)
LAKE.cubicTo(107, 129, 123, 124, 141, 128)
LAKE.lineTo(141, 177)
LAKE.lineTo(20, 177)
LAKE.closeSubpath()
LEFT_BANK = QPainterPath(QPointF(16, 139))
LEFT_BANK.cubicTo(37, 138, 37, 153, 59, 158)
LEFT_BANK.cubicTo(81, 166, 94, 161, 108, 175)
LEFT_BANK.lineTo(16, 177)
LEFT_BANK.closeSubpath()
RIGHT_BANK = QPainterPath(QPointF(87, 148))
RIGHT_BANK.cubicTo(96, 142, 105, 143, 118, 136)
RIGHT_BANK.cubicTo(129, 130, 137, 131, 149, 130)
RIGHT_BANK.lineTo(150, 150)
RIGHT_BANK.cubicTo(120, 148, 103, 153, 87, 148)
RIGHT_BANK.closeSubpath()
WATER = LAKE.subtracted(LEFT_BANK).subtracted(RIGHT_BANK)


def color(value, alpha):
    tint = QColor(value)
    tint.setAlpha(alpha)
    return tint


def mix(first, second, ratio):
    a, b = QColor(first), QColor(second)
    return QColor.fromRgbF(*(x * (1 - ratio) + y * ratio for x, y in zip(a.getRgbF(), b.getRgbF())))


def linear(x0, y0, x1, y1, *colors):
    brush = QLinearGradient(x0, y0, x1, y1)
    for index, tint in enumerate(colors):
        at, value = tint if isinstance(tint, tuple) else (index / (len(colors) - 1), tint)
        brush.setColorAt(at, QColor(value))
    return brush


def ellipse(p, x, y, rx, ry, brush):
    p.setBrush(brush)
    p.drawEllipse(QPointF(x, y), rx, ry)


def raster(dpr, paint, width=160, height=198):
    image = QPixmap(round(width * dpr), round(height * dpr))
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    with QPainter(image) as p:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        paint(p)
    return image


def polygon(p, points, brush):
    p.setBrush(brush)
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))


def draw_land(p, key):
    scene = WEATHER[key]
    season = SEASON[key]
    _, horizon, light, surface, depth, *ridge_colors = PALETTES[scene.palette]
    meadow, shade, _, _ = PLANTS[season]
    if scene.rain:
        meadow = mix(meadow, horizon, min(0.72, scene.rain * 0.39))
        shade = mix(shade, depth, 0.46)
    if key == "blossom":
        meadow = mix(meadow, "#eec0b7", 0.36)
    rng = Random(350)
    for i, ridge in enumerate(RIDGES):
        points = []
        for (x, y), (nx, ny) in zip(ridge, ridge[1:]):
            points.append((x, y))
            for f in (0.24, 0.48, 0.73):
                points.append((x + (nx - x) * f, y + (ny - y) * f + rng.uniform(-1.1, 1.1)))
        points.append(ridge[-1])
        top = mix(ridge_colors[i], meadow, 0.13 + i * 0.13)
        bottom = mix(ridge_colors[i], horizon, 0.64 - i * 0.15)
        polygon(p, [*points, (147, 155), (16, 155)], linear(0, 91 + 8 * i, 0, 142, top, bottom))
        for x, y in points:
            side = rng.uniform(4, 12)
            tint = color(light if side > 8 else shade, rng.randint(8, 31))
            polygon(p, [(x, y + 0.55), (x - side, y + 13), (x - 2, y + 9)],
                    linear(0, y, 0, y + 12, tint, color(tint, 0)))
        if i == 2:
            for (x, y), (nx, ny) in zip(points, points[1:]):
                for n in range(3):
                    tx = x + (nx - x) * n / 3
                    ty = y + (ny - y) * n / 3 + 0.45
                    height = rng.uniform(0.55, 1.85)
                    polygon(p, [(tx, ty - height), (tx - height * 0.38, ty + 0.8), (tx + height * 0.44, ty + 0.8)],
                            color(top, 145))

    water_light = mix(surface, horizon, 0.51)
    if key in {"sun", "rain", "cumulus", "rainbow", "shower"}:
        water_light = mix(water_light, "#58b9c6", 0.30)
        surface = mix(surface, "#278796", 0.32)
    p.fillPath(LAKE, linear(0, 131, 0, 174, water_light, surface, mix(depth, "#35a9b2", 0.26)))
    p.save()
    p.setClipPath(WATER)
    for ridge, tint in zip(RIDGES[1:], ridge_colors[1:]):
        reflected = [(x, 132 + (132 - y) * 0.33) for x, y in ridge]
        polygon(p, [*reflected, (147, 131), (16, 131)],
                linear(0, 132, 0, 145, color(tint, 65), color(tint, 38), color(tint, 0)))
    for _ in range(115):
        y = rng.uniform(132, 174)
        x = rng.uniform(19, 142)
        width = rng.uniform(0.7, 6) * (0.25 + (y - 130) / 31)
        ellipse(p, x, y, width, rng.uniform(0.09, 0.30), color(light, rng.randint(16, 88)))
    p.restore()

    for bank, start, end in ((RIGHT_BANK, 136, 153), (LEFT_BANK, 140, 174)):
        p.fillPath(bank, linear(0, start, 0, end, mix(meadow, light, 0.18), meadow, shade))
        p.save()
        p.setClipPath(bank)
        for _ in range(500 if bank is LEFT_BANK else 205):
            x, y = rng.uniform(20, 142), rng.uniform(start, end)
            size = rng.uniform(0.14, 0.63) * (0.65 + (y - 130) / 41)
            tint = rng.choice((meadow, light, shade, shade))
            p.fillRect(QRectF(x, y - size, size * 0.65, size * 1.8), color(tint, rng.randint(80, 190)))
        p.restore()
    for x, y, r in ((31, 146, 1.7), (36, 151, 2.5), (44, 156, 2.1), (52, 160, 3.2),
                    (61, 164, 2), (103, 148, 1.9), (111, 146, 2.4), (118, 145, 3),
                    (126, 143, 3.8), (132, 142, 2.5)):
        ellipse(p, x + 0.8, y + 0.8, r * 1.2, r * 0.32, color(depth, 150))
        ellipse(p, x, y, r, r * 0.64,
                linear(x - r, y - r, x + r, y + r, color(light, 235), "#768e9b", shade))
    for x, y in ((29, 147), (34, 148), (41, 153), (47, 156), (50, 155), (55, 160), (60, 161)):
        if season in {"春", "夏"}:
            ellipse(p, x, y, 0.76, 0.57, QColor("#fff1c4" if x % 2 else "#d7e8ff"))


def tree(dpr, key):
    scene = WEATHER[key]
    season = SEASON[key]
    _, _, lit, shade = PLANTS[season]
    if key == "blossom":
        lit, shade = "#ffe0e5", "#875d83"
    if scene.rain > 0.6:
        lit, shade = mix(lit, "#a0c3d5", 0.3), mix(shade, "#25485f", 0.45)

    def paint(p):
        rng = Random(828)
        branches = QPainterPath(QPointF(22, 37))
        branches.cubicTo(23, 27, 20, 18, 22, 12)
        branches.moveTo(22, 30)
        branches.quadTo(18, 22, 12, 19)
        branches.moveTo(22, 27)
        branches.quadTo(26, 19, 32, 17)
        p.setPen(QPen(linear(19, 0, 24, 0, "#b7a288", "#35403d"), 1.45,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(branches)
        p.setPen(Qt.PenStyle.NoPen)
        if season == "冬":
            for y, radius in ((12, 4.1), (16, 6.1), (21, 8.7), (27, 11)):
                polygon(p, [(22, y - 7), (22 - radius, y + 2), (22 + radius, y + 2)],
                        linear(0, y - 6, 0, y + 3, lit, "#a4c7d8", shade))
            return
        for x, y, r in ((13, 18, 6), (27, 18, 8), (33, 15, 5), (11, 14, 6), (22, 12, 9), (29, 10, 6), (19, 7, 5)):
            ellipse(p, x, y, r, r * 0.72, linear(x - r, y - r, x + r * 0.4, y + r * 0.62, lit, mix(lit, shade, .48), shade))
            for _ in range(22):
                angle = rng.uniform(0, 6.283)
                radius = rng.uniform(0.18, 0.83)
                ellipse(p, x + cos(angle) * r * radius, y + sin(angle) * r * radius * 0.7,
                        rng.uniform(0.28, 0.9), 0.46, color(lit if sin(angle) < 0.22 else shade, 132))
    return raster(dpr, paint, 44, 38)


def cloud(dpr, dark=False):
    def paint(p):
        rng = Random(862)
        # Paint large shaded lobes back-to-front, then catch their sunward edges.
        masses = ((13, 27, 8), (21, 24, 10), (31, 23, 12), (39, 23, 12), (54, 23, 11),
                  (67, 27, 9), (58, 22, 9), (26, 19, 8), (37, 16, 10), (48, 14, 12),
                  (52, 10, 7), (59, 17, 8), (44, 22, 9))
        for x, y, r in masses:
            for _ in range(3):
                cx, cy = x + rng.uniform(-2, 2), y + rng.uniform(-1.5, 1.5)
                halo = QRadialGradient(cx, cy, r, cx - r * .23, cy - r * .47)
                halo.setColorAt(0, QColor("#dbedf9" if dark else "#fffcef"))
                halo.setColorAt(.38, QColor("#acc7df" if dark else "#eff8fd"))
                halo.setColorAt(.73, QColor(112, 151, 186, 169) if dark else QColor(182, 213, 237, 177))
                halo.setColorAt(1, QColor(128, 170, 201, 0))
                ellipse(p, cx, cy, r, r * .86, halo)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        p.fillRect(QRectF(0, 16, 80, 24), linear(0, 17, 0, 39, QColor(35, 68, 112, 0),
                                               QColor(35, 68, 112, 182 if dark else 81)))
    return raster(dpr, paint, 80, 42)
