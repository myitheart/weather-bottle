from dataclasses import dataclass
from math import cos, pi, sin
from random import Random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainterPath, QPen, QRadialGradient


@dataclass(frozen=True)
class Scene:
    name: str
    palette: str
    sky: str = ""
    air: str = ""
    rain: float = 0
    mist: float = 0


# Sky, horizon, ambient light, water surface, deep water, and three ridges.
PALETTES = {
    "rain": ("#253654", "#829aa8", "#b9defa", "#577f92", "#223c55", "#596f84", "#354e63", "#263d50"),
    "sun": ("#535778", "#efb49b", "#ffdc9c", "#9e8296", "#514963", "#a5899a", "#726982", "#464d68"),
    "fog": ("#526376", "#acbdc3", "#d3e5e8", "#748f9e", "#40586a", "#8297a3", "#647d8b", "#456073"),
    "spring": ("#5a82a0", "#c2dcae", "#fff0bd", "#78aa9f", "#365e65", "#8fae9c", "#668e80", "#456a68"),
    "blossom": ("#716e9d", "#efc3cb", "#ffe1d9", "#a88fa7", "#505474", "#ae92a9", "#817997", "#555e80"),
    "day": ("#3978ad", "#bce7e8", "#fff4d0", "#64adb7", "#285e83", "#7facbd", "#568b9f", "#3b718b"),
    "cloud": ("#4b5f79", "#b2bfc7", "#dceaf3", "#708a9e", "#334b66", "#8395a7", "#627b91", "#465e76"),
    "storm": ("#17223e", "#536484", "#c3d4ff", "#506f8b", "#192b45", "#475975", "#314562", "#21344e"),
    "autumn": ("#52516f", "#efb275", "#ffd28e", "#947d7a", "#4f475c", "#ae846d", "#946753", "#684e54"),
    "dusk": ("#302e59", "#ee9380", "#ffc383", "#a47492", "#463c63", "#a57089", "#795e83", "#4f4c71"),
    "snow": ("#54799e", "#cde2ed", "#ebf8ff", "#a2bdce", "#58768d", "#c3d7e5", "#92b4cb", "#7794ad"),
    "ice": ("#3b587e", "#afcddd", "#e7fbff", "#acd5df", "#507c9b", "#a3bed1", "#7c9fb5", "#627d9d"),
    "night": ("#101831", "#45547c", "#c2d9ff", "#475e86", "#1c2b4b", "#3b4d73", "#283a5e", "#1d2e50"),
    "aurora": ("#121934", "#386a77", "#a1f8d6", "#488887", "#213c52", "#456679", "#305568", "#234455"),
    "heat": ("#627aa0", "#f7c885", "#ffe7aa", "#a3a291", "#64697d", "#bba482", "#9a866e", "#736d67"),
}

GROUPS = {
    "春": {
        "sun": Scene("晴日暖阳", "spring", "sun"),
        "rain": Scene("春雨", "rain", "cloud", rain=0.75),
        "fog": Scene("晨雾", "fog", mist=1),
        "blossom": Scene("樱花风", "blossom", "sun", "petal"),
        "drizzle": Scene("蒙蒙细雨", "spring", "cloud", rain=0.34, mist=0.35),
        "rainbow": Scene("雨后彩虹", "day", "rainbow", rain=0.22),
    },
    "夏": {
        "heat": Scene("盛夏晴空", "heat", "sun", "heat"),
        "cumulus": Scene("积云", "day", "cloud"),
        "shower": Scene("午后阵雨", "day", "cloud", rain=1.05),
        "downpour": Scene("暴雨", "storm", "cloud", rain=1.5),
        "thunder": Scene("雷阵雨", "storm", "thunder", rain=1.26),
        "fireflies": Scene("夏夜萤火", "aurora", "moon", "firefly"),
    },
    "秋": {
        "overcast": Scene("秋阴", "cloud", "cloud"),
        "leaves": Scene("秋风落叶", "autumn", "sun", "leaf"),
        "dusk": Scene("深秋晚霞", "dusk", "sun"),
        "wind": Scene("阵风", "cloud", "cloud", "wind"),
        "haze": Scene("薄霾", "heat", "sun", mist=0.65),
        "coldrain": Scene("深秋冷雨", "cloud", "cloud", rain=0.8, mist=0.43),
    },
    "冬": {
        "snow": Scene("小雪", "snow", "cloud", "snow"),
        "blizzard": Scene("风雪", "ice", "cloud", "blizzard", mist=0.5),
        "sleet": Scene("雨夹雪", "snow", "cloud", "snow", rain=0.55),
        "hail": Scene("冰雹", "storm", "cloud", "hail"),
        "frost": Scene("霜冻", "ice", "sun", "frost"),
        "icefog": Scene("冰雾", "ice", "moon", "snow", mist=1.15),
    },
    "夜空": {
        "moon": Scene("月夜", "night", "moon"),
        "stars": Scene("晴夜星空", "night", "stars"),
        "aurora": Scene("极光", "aurora", "aurora"),
        "meteors": Scene("流星夜", "night", "stars", "meteor"),
    },
}
WEATHER = {key: scene for group in GROUPS.values() for key, scene in group.items()}

_rng = Random(632)
STARS = tuple((_rng.uniform(36, 124), _rng.uniform(37, 115), _rng.random()) for _ in range(42))
PARTICLES = tuple((_rng.uniform(30, 133), _rng.random(), _rng.uniform(0.6, 1.4)) for _ in range(40))


def draw_sky(p, scene, glow, time, tilt):
    x = 97 + tilt * 0.15
    y = (88 if scene.palette == "dusk" else 79) + sin(time * 0.46) * 0.72
    p.setPen(Qt.PenStyle.NoPen)
    halo = QRadialGradient(x, y, 49)
    light = QColor(glow)
    light.setAlpha(174 if scene.sky == "sun" else 90)
    halo.setColorAt(0, light)
    light.setAlpha(0)
    halo.setColorAt(1, light)
    p.setBrush(halo)
    p.drawEllipse(QPointF(x, y), 49, 49)

    if scene.sky in {"moon", "stars", "aurora"}:
        for sx, sy, phase in STARS:
            radius = 0.35 + phase * 0.55
            p.setBrush(QColor(227, 242, 255, int(80 + 100 * (0.5 + 0.5 * sin(time * 1.5 + phase * 20)))))
            p.drawEllipse(QPointF(sx, sy), radius, radius)
    if scene.sky in {"sun", "moon"}:
        disc = QLinearGradient(0, y - 10, 0, y + 10)
        disc.setColorAt(0, QColor("#fff9de" if scene.sky == "sun" else "#f5fbff"))
        disc.setColorAt(1, QColor("#efad70" if scene.sky == "sun" else "#9cbad6"))
        p.setBrush(disc)
        p.drawEllipse(QPointF(x, y), 9, 9)
        if scene.sky == "moon":
            p.setBrush(QColor(125, 154, 190, 85))
            p.drawEllipse(QPointF(x + 2, y - 2), 2.5, 2)
            p.drawEllipse(QPointF(x - 3, y + 3), 1.8, 1.6)
    elif scene.sky == "rainbow":
        p.setBrush(Qt.BrushStyle.NoBrush)
        bands = ("#ffa38b", "#ffca91", "#f8ef9d", "#b9efaf", "#91e1f2", "#b2aef3")
        fade = QLinearGradient(0, 72, 0, 116)
        for i, tint in enumerate(bands):
            color = QColor(tint)
            color.setAlpha(122)
            fade.setColorAt(0, color)
            color.setAlpha(106)
            fade.setColorAt(.44, color)
            color.setAlpha(0)
            fade.setColorAt(1, color)
            p.setPen(QPen(fade, 1.95))
            p.drawArc(QRectF(24 + i * 1.28, 71 + i * 1.28, 110 - i * 2.56, 100 - i * 2.56), 0, 180 * 16)
    elif scene.sky == "aurora":
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(13):
            wave = sin(time * 0.65 + i * 0.12) * 6
            path = QPainterPath(QPointF(30, 101 - i))
            path.cubicTo(61, 77 - i + wave, 85, 109 - i - wave, 132, 74 - i)
            p.setPen(QPen(QColor(110 + i * 5, 229, 200 + i * 3, 17 + i * 3), 1.9))
            p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)


def draw_air(p, effect, time, tilt):
    if effect in {"petal", "leaf", "snow", "blizzard", "hail"}:
        count, fall, sway, drift, tint = {
            "petal": (16, 0.18, 7, 4, "#ffd6e4"),
            "leaf": (14, 0.23, 10, 10, "#efb374"),
            "snow": (26, 0.14, 5, 2, "#edf8ff"),
            "blizzard": (40, 0.43, 3, 28, "#f1faff"),
            "hail": (24, 0.94, 1, 5, "#d9edff"),
        }[effect]
        for i, (start, phase, speed) in enumerate(PARTICLES[:count]):
            progress = (phase + time * speed * fall) % 1
            x = (start - 30 + sin(time * speed + i) * sway + progress * (drift + tilt * 0.8)) % 103 + 30
            y = 64 + progress * 87
            color = QColor(tint)
            color.setAlpha(int(80 + speed * 92))
            p.setBrush(color)
            if effect in {"petal", "leaf"}:
                p.save()
                p.translate(x, y)
                p.rotate(sin(time * speed * 1.7 + i) * 72 + tilt)
                width = 2.0 if effect == "petal" else 2.8
                p.drawEllipse(QPointF(0, 0), width * speed, 1.05 * speed)
                p.restore()
            else:
                radius = 0.7 + speed * (1.15 if effect == "hail" else 0.67)
                p.drawEllipse(QPointF(x, y), radius, radius)
    elif effect == "firefly":
        for i, (start, phase, speed) in enumerate(PARTICLES[:14]):
            x = start + sin(time * speed + i) * 7 + tilt * 0.4
            y = 137 + cos(time * 0.7 + i) * 17
            light = int(48 + 144 * (0.5 + 0.5 * sin(time * 2 + phase * 24)))
            glow = QRadialGradient(x, y, 4.5)
            glow.setColorAt(0, QColor(246, 255, 157, light))
            glow.setColorAt(1, QColor(246, 255, 157, 0))
            p.setBrush(glow)
            p.drawEllipse(QPointF(x, y), 4.5, 4.5)
    elif effect in {"wind", "heat"}:
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(6):
            x = 37 + (time * (19 if effect == "wind" else 5) + i * 17) % 83
            y = 86 + i * 8
            offset = sin(time * 2 + i) * (5 if effect == "wind" else 2)
            path = QPainterPath(QPointF(x - 14, y))
            path.cubicTo(x - 4, y + offset, x + 7, y - offset, x + 16, y)
            p.setPen(QPen(QColor(232, 246, 255, 58 if effect == "wind" else 37), 0.8))
            p.drawPath(path)
    elif effect == "frost":
        p.setPen(QPen(QColor(223, 247, 255, 145), 0.65))
        for i in range(9):
            x = 38 + i * 10.5
            height = 7 + 6 * sin(i * 2.6) ** 2
            tip = QPointF(x + sin(i) * 3, 159 - height)
            p.drawLine(QPointF(x, 162), tip)
            p.drawLine(QPointF(x, 156), QPointF(x - 3, 152 - height * 0.35))
            p.drawLine(QPointF(x, 155), QPointF(x + 4, 152 - height * 0.35))
    elif effect == "meteor":
        for i in range(3):
            phase = (time * (0.28 + i * 0.07) + i * 0.41) % 1
            if phase > 0.27:
                continue
            x = 119 - phase * 224
            y = 70 + i * 12 + phase * 105
            tail = QPointF(x + 17, y - 8)
            head = QPointF(x, y)
            glow = QLinearGradient(tail, head)
            glow.setColorAt(0, QColor(207, 230, 255, 0))
            glow.setColorAt(1, QColor(227, 245, 255, int(215 * sin(pi * phase / 0.27))))
            p.setPen(QPen(QBrush(glow), 1.1))
            p.drawLine(tail, head)
    p.setPen(Qt.PenStyle.NoPen)
