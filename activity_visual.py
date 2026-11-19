"""Paint the orb and activity capsule as a single glass surface."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from math import ceil, cos, pi, sin, tau

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

from pearl_style import glass, glyph, palette
from typography import draw_line, draw_number, metrics, number_width, text_baseline
from landscape import color, ellipse, linear


ORB_SIZE = 38
CAPSULE_WIDTH = 196
GLINT_SECONDS = .42

STATUS = {"ended": "本轮已结束", "failed": "运行失败", "interrupted": "已中断", "unknown": "状态未确认"}
DETAIL = {"failed": "有任务失败", "interrupted": "有任务中断", "unknown": "状态未确认"}


def smooth(value):
    value = max(0., min(1., value))
    return value * value * (3 - 2 * value)


def compact_geometry(progress, scale=1.):
    return (ORB_SIZE + (CAPSULE_WIDTH - ORB_SIZE) * smooth(progress)) * scale, ORB_SIZE * scale


def glow(center, radius, tint, opacity):
    gradient = QRadialGradient(center, radius)
    gradient.setColorAt(0., color(tint, opacity))
    gradient.setColorAt(1., color(tint, 0))
    return gradient


def draw_glass(p, box, core, glint, on_right, warning, progress):
    direction = -1 if on_right else 1
    shift = max(0., box.width()-box.height()) * .34 * smooth(progress)
    reflected_at = QPointF(core.x() + direction * shift, box.top() + 1.)
    glass(p, box, "capsule", reflected_at=reflected_at)
    if 0 < glint < 1 and not warning:
        outline = QPainterPath()
        r = box.height()/2
        outline.addRoundedRect(box, r, r)
        tip = QPointF(core.x() + direction * smooth(glint) * (box.width() - 14), box.top() + .7)
        p.save()
        p.setClipPath(outline)
        p.fillRect(box, glow(tip, 27, "#ffc28b", int(95 * sin(pi * glint))))
        p.restore()


@lru_cache(maxsize=1)
def pearl_source():
    path = Path(__file__).with_name("assets") / "pearl" / "glass-pearl-v2.png"
    return QImage(str(path)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


@lru_cache(maxsize=1)
def pearl_pixmap():
    return QPixmap.fromImage(pearl_source())


@lru_cache(maxsize=28)
def pearl_level(pixels):
    master = pearl_source()
    if master.isNull():
        return QPixmap()
    img = master.scaled(pixels, pixels, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return QPixmap.fromImage(img)


@lru_cache(maxsize=1)
def floor_gradients():
    return (glow(QPointF(0, .17), 1, "#162334", 102),
            glow(QPointF(0, -.19), .91, "#ffd09c", 132))


def draw_pearl_floor(p, x, y, exposure, hover):
    shadow, reflection = floor_gradients()
    p.save()
    p.translate(x, y)
    p.scale(15.7, 2.72)
    opacity = p.opacity()
    p.setOpacity(opacity * exposure)
    ellipse(p, 0, .17, 1, 1, shadow)
    p.setOpacity(opacity * exposure * (.34 + .62 * hover))
    ellipse(p, 0, -.17, 1., .78, reflection)
    p.restore()


@dataclass(frozen=True)
class PearlLight:
    mode: str = "idle"
    motion: float | None = None
    reflection: float = 0.
    charge: float = 0.
    direction: int = 1
    dense: bool = False
    paused: bool = False
    completed: bool = False


@lru_cache(maxsize=2)
def amber_light(kind):
    # Prefilter the radial falloff once. Keep the warm core broad enough to sample at 1x.
    size = 72
    center = QPointF(size / 2, size / 2)
    gradient = QRadialGradient(center, size / 2)
    stops = ((0., "#fff1d1", 249), (.26, "#ffdfa6", 227), (.48, "#ffc981", 132),
             (.76, "#ffb772", 42), (1., "#ffb772", 0)) if kind == "core" else (
             (0., "#ffc78a", 112), (.35, "#ffcd96", 78), (.72, "#ffb971", 22), (1., "#ffb971", 0))
    for position, tint, opacity in stops:
        gradient.setColorAt(position, color(tint, opacity))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    with QPainter(image) as bake:
        bake.fillRect(image.rect(), gradient)
    return QPixmap.fromImage(image)


def paint_amber(p, kind, center, horizontal, vertical):
    sprite = amber_light(kind)
    bounds = QRectF(center.x() - horizontal, center.y() - vertical, 2 * horizontal, 2 * vertical)
    p.drawPixmap(bounds, sprite, QRectF(sprite.rect()))


def draw_active_light(p, core, r, light):
    now = light.motion
    phase = 0. if now is None else tau * (now % 9.6) / 9.6
    travel = phase + .36 * sin(phase + .42)
    x = .46 * sin(travel) + .10 * sin(travel * 2 + .64)
    y = -.10 - .19 * cos(travel + .46) + .11 * sin(2 * travel - .31)

    # The broader refraction trails the core and stays below the baked cool highlight.
    lag = travel - .44
    mist = core + QPointF(r * .34 * sin(lag), r * (.12 - .13 * cos(lag)))
    p.save()
    p.translate(mist)
    p.rotate(-27. + 11. * sin(travel + .86))
    p.setOpacity(p.opacity() * (.55 if now is None else .75 + .14 * cos(travel - .7)))
    paint_amber(p, "mist", QPointF(), .79 * r, .30 * r)
    p.restore()
    if light.dense:
        echo = core + QPointF(-.17 * r * cos(travel + .5), -.31 * r + .07 * r * sin(travel))
        ellipse(p, echo.x(), echo.y(), .57 * r, .35 * r, glow(echo, .61 * r, "#bad7f6", 34))
    if now is not None:
        paint_amber(p, "core", core + QPointF(r * x, r * y), .265 * r, .265 * r)


def draw_inner_light(p, sphere, core, radius, light):
    if light is None:
        return
    mode, now = light.mode, light.motion
    wave = .5 if now is None else .5 - .5 * cos(tau * now / 6.4)
    shift = 0. if now is None else sin(tau * now / 9.7)
    blink = sin(pi * light.reflection) ** 2
    r = radius
    p.save()
    p.setClipPath(sphere, Qt.ClipOperation.IntersectClip)
    if now is not None:
        upper = core + QPointF(r * (-.32 + .22 * shift), r * (-.36 + .06 * shift))
        lower = core + QPointF(r * (.20 - .10 * shift), r * .61)
        cool = 17 + 45 * wave + 16 * blink if mode == "idle" else 8 + 21 * wave
        p.fillPath(sphere, glow(upper, r * (.48 + .19 * wave), "#dfedff", round(cool)))
        p.fillPath(sphere, glow(lower, r * .65, "#ffd399", round(8 + 26 * (1 - wave))))
    if mode == "active":
        draw_active_light(p, core, r, light)
    elif mode != "idle":
        tint = {"focus": "#ffbb6b", "rest": "#92dcff"}[mode]
        period = {"focus": 10.4, "rest": 11.2}[mode]
        flow = 0. if now is None else tau * now / period
        center = core + QPointF(r * .30 * sin(flow), r * (.18 + .19 * sin(flow * .76)))
        alpha = 48 + 15 * (1 + sin(flow)) if not light.paused else 25
        p.translate(center)
        p.rotate(-26 + 8 * sin(flow * .62))
        p.scale(r, r * .42)
        ellipse(p, 0, 0, 1.19, 1., glow(QPointF(), 1.10, tint, round(alpha)))
        p.restore()
        p.save()
        p.setClipPath(sphere, Qt.ClipOperation.IntersectClip)
        if now is not None and not light.paused:
            mote = core + QPointF(r * (.46 * sin(flow) + .10 * sin(flow * 1.79)), r * .31 * cos(flow * 1.22))
            ellipse(p, mote.x(), mote.y(), r * .20, r * .20, glow(mote, r * .20, tint, 133))
            ellipse(p, mote.x(), mote.y(), r * .038, r * .038, color("#fff5df", 150))
    if light.charge:
        charge_at = core + QPointF(light.direction * r * .52, r * .10)
        p.fillPath(sphere, glow(charge_at, r * 1.07, "#ffe0a5", round(109 * light.charge)))
    p.restore()


def draw_pearl(p, core, radius, hover, docked, state, light=None):
    x, y = core.x(), core.y()
    p.setPen(Qt.PenStyle.NoPen)
    exposure = 1 - docked
    hovering = hover * exposure
    if exposure > .01:
        ellipse(p, x, y + 4.4, 18.2, 17.2,
                glow(QPointF(x, y + 5.9), 17.3, "#ffd5a4", int((24 + 79 * hover) * exposure)))
        breath = .07 * sin(tau * light.motion / 6.4) if light and light.motion is not None else 0.
        draw_pearl_floor(p, x, y + 16.1, exposure, max(0., hovering + .05 + breath))

    r = radius
    gold = docked if state in {"running", "ended"} else 0.
    if gold:
        reflection = min(12., r * 1.15)
        ellipse(p, x, y, reflection, reflection, glow(core, reflection, "#ffcb91", round(31 * gold)))
    sphere = QRectF(x - r, y - r, r * 2, r * 2)
    surface = QPainterPath()
    surface.addEllipse(sphere)
    inner = QPainterPath()
    inner.addEllipse(sphere.adjusted(r * .05, r * .05, -r * .05, -r * .05))
    dest = sphere.adjusted(-.38, -.38, .38, .38)
    device_width = p.deviceTransform().mapRect(dest).width()
    # Prefilter once per physical size, always from the premultiplied master.
    pixmap = pearl_level(min(512, max(16, ceil(device_width / 2) * 4)))
    if not pixmap.isNull():
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(dest, pixmap, QRectF(pixmap.rect()))
        draw_inner_light(p, inner, core, r, light)
        if hovering > .005:
            p.fillPath(surface, glow(QPointF(x-r*.35-r*.10*hovering, y-r*.39),
                                     1.15*r, "#edf7ff", int(91*hovering)))
            p.fillPath(surface, glow(QPointF(x+r*.11, y+r*.67), r, "#ffdfb0", int(62*hovering)))
        p.restore()
        return
    glass = linear(x - r * .75, y - r, x + r * .4, y + r, color("#f8eee9", 252),
                   color("#819fbf", 244), color("#385578", 230), color("#7d9bb9", 241), color("#ffedce", 255))
    p.fillPath(surface, glass)
    draw_inner_light(p, inner, core, r, light)
    p.save()
    p.setClipPath(surface)
    lower = QPointF(x + r * .30, y + r * .84)
    p.fillPath(surface, glow(lower, r * 1.39, "#ffc387", 226))
    p.fillPath(surface, glow(lower + QPointF(-r * .04, r * .12), r * .57, "#fff4d6", 227))
    p.fillPath(surface, glow(QPointF(x + r * .44, y - r * .34), r * 1.08, "#a8d4fa", 155))
    p.fillPath(surface, glow(QPointF(x - r * .81, y - r * .41), r * .65, "#e0ebff", 137))

    if gold:
        p.fillPath(surface, glow(QPointF(x + r * .1, y + r * .25), r * 1.55,
                                 "#ffcc90", int(148 * gold)))
    if hovering > .005:
        p.fillPath(surface, linear(0, y-r, 0, y+r, color("#f5faff", int(136 * hovering)),
                                   color("#dbecff", int(99 * hovering)),
                                   color("#ffd498", int(177 * hovering))))
        p.fillPath(surface, glow(QPointF(x - .06 * r, y + .67 * r), r * .91,
                                 "#fff0c6", int(170 * hovering)))

    refraction = QPainterPath(QPointF(x - r, y + r * .28))
    refraction.cubicTo(x - r * .32, y + r * .78, x + r * .46, y - r * .22, x + r, y + r * .03)
    refraction.lineTo(x + r, y + r)
    refraction.lineTo(x - r, y + r)
    refraction.closeSubpath()
    p.fillPath(refraction, linear(0, y - r * .12, 0, y + r * .72,
                                  color("#eef2ff", 79), color("#accdf4", 0)))
    if r > 7:
        light_bend = QPainterPath(QPointF(x - r * .92, y + r * .28))
        light_bend.cubicTo(x - r * .27, y + r * .80, x + r * .35, y - r * .19, x + r * .93, y + r * .04)
        p.setPen(QPen(linear(x-r, y, x+r, y, color("#c9e1ff", 3), color("#e4f0ff", 65),
                              color("#fff5e9", 8)), .54))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(light_bend)
    p.restore()

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(linear(x - r, y - r, x + r, y + r, color("#fff9ef", 247),
                          color("#e3f1ff", 126), color("#ffdfac", 216)), .82 if r > 6 else .57))
    p.drawEllipse(sphere)
    if r > 7:
        p.setPen(QPen(color("#fff0c8", 194 + round(58 * hovering)), .82 + .38 * hovering))
        p.drawArc(sphere.adjusted(.52, .52, -.52, -.52), 219 * 16, 95 * 16)
        p.setPen(QPen(color("#fffcf2", 206 + round(47 * hovering)), .72 + .3 * hovering))
        p.drawArc(sphere.adjusted(.44, .44, -.44, -.44), 63 * 16, 91 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.save()
    p.translate(x - r * (.37 + .08 * hover), y - r * .43)
    p.rotate(-43)
    specular = r * (1 + .25 * hovering)
    ellipse(p, 0, 0, specular * .57, specular * .33,
            glow(QPointF(0, 0), specular * .53, "#fff9ee", 249))
    ellipse(p, -.11 * r, 0, r * .29, r * .131,
            glow(QPointF(-.17 * r, 0), r * .35, "#fffefa", 251))
    p.restore()


def draw_activity(p, width, height, on_right, state, active, recent, finished, elapsed, change, detail_opacity):
    left = 13 if on_right else 35
    right = width - (35 if on_right else 13)
    t = palette()
    tone = QColor(t.error if recent in {"interrupted", "failed"} else t.success if recent == "ended" else t.muted)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    line = QRectF(left, 2, right - left, height - 6)
    baseline = text_baseline(p, line, "capsule_title")
    p.setPen(QColor(t.text))
    if not active:
        if state in {"interrupted", "failed"}:
            p.setPen(QColor(t.error))
        label = f"{finished} 项已结束" if finished > 1 and state == "ended" else STATUS[state]
        draw_line(p, line, label, "capsule_title", baseline=baseline)
        return

    duration = ""
    if recent == "ended":
        duration = f"{finished} 项结束"
    elif recent:
        duration = DETAIL[recent]
    elif active == 1:
        mins, secs = divmod(int(max(0, elapsed)), 60)
        duration = f"{mins:02d}:{secs:02d}"

    p.save()
    numeral = QRectF(left, 2, number_width(p, str(max(10, active, change[0])), "count"), height - 6)
    previous, blend = change
    opacity = p.opacity()
    p.setPen(QColor(t.warm))
    if previous and blend < 1:
        p.setOpacity(opacity * (1 - blend))
        draw_number(p, numeral, str(previous), "count", baseline=baseline - 3 * blend)
    p.setOpacity(opacity * (blend if previous else 1))
    draw_number(p, numeral, str(active), "count", baseline=baseline + 3 * (1 - blend))
    p.restore()

    text_left = numeral.right() + 5
    line = QRectF(text_left, 2, right - text_left, height - 6)
    draw_line(p, line, "项处理中", "capsule_title", baseline=baseline)
    p.setOpacity(p.opacity() * detail_opacity)
    if duration:
        p.setPen(tone)
        if ":" in duration:
            draw_number(p, line, duration, "clock", baseline=baseline)
        else:
            draw_line(p, line, duration, "capsule_detail", align=Qt.AlignmentFlag.AlignRight, baseline=baseline)
    else:
        arrow = QPen(tone, .85)
        arrow.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arrow)
        x, y = right - 3, height / 2 - 1
        p.drawLine(QPointF(x - 2, y - 2), QPointF(x + .5, y))
        p.drawLine(QPointF(x + .5, y), QPointF(x - 2, y + 2))


@dataclass(frozen=True)
class CapsuleFace:
    label: str
    detail: str
    progress: float | None = None
    symbol: str = ""
    tone: str = "warm"


def draw_face(p, box, on_right, face, detail_opacity):
    left = 14 if on_right else 34
    right = box.right() - (32 if on_right else 9)
    t = palette()
    accent = getattr(t, face.tone)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    line = QRectF(left, 1., right - left, box.height() + 3)
    baseline = text_baseline(p, line, "capsule_title")
    detail_is_clock = ":" in face.detail
    detail_width = 0.
    if face.detail:
        if detail_is_clock:
            detail_width = number_width(p, face.detail, "clock")
        else:
            detail_width = metrics(p, "capsule_detail").horizontalAdvance(face.detail)
        measured = detail_width
        detail_width = min(line.width() * .49, measured + 2.)
        detail = QRectF(right - detail_width, line.top(), detail_width, line.height())
        p.save()
        p.setOpacity(p.opacity() * detail_opacity)
        p.setPen(QColor(accent))
        if detail_is_clock and measured <= detail_width:
            draw_number(p, detail, face.detail, "clock", baseline=baseline)
        else:
            draw_line(p, detail, face.detail, "capsule_detail", align=Qt.AlignmentFlag.AlignRight, baseline=baseline)
        p.restore()
    label_width = max(0., line.width() - (detail_width + 7. if face.detail else 0.))
    p.setPen(QColor(accent if face.tone == "error" else t.text))
    draw_line(p, QRectF(left, line.top(), label_width, line.height()), face.label,
              "capsule_title", baseline=baseline)
    if face.progress is not None:
        y = box.bottom() - 4
        track_start, track_end = left, right
        track = QPen(color(accent, 52), 1.15)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track)
        p.drawLine(QPointF(track_start, y), QPointF(track_end, y))
        track.setColor(QColor(accent))
        p.setPen(track)
        p.drawLine(QPointF(track_start, y), QPointF(track_start + (track_end - track_start) * face.progress, y))


def draw_compact(p, width, height, *, on_right, state, progress, hover, glint,
                 active, recent, finished, elapsed, change, face=None, unread=False, quiet=False, pressed=False,
                 light=None, alert=False):
    morph = smooth(progress)
    docked = smooth((progress - .19) / .66)
    # Hold the resting optical center through the last part of the morph.
    core = QPointF(width - ORB_SIZE / 2 if on_right else ORB_SIZE / 2,
                   height / 2 - 3.3 + 2.8 * smooth((progress - .30) / .62))
    inset = 4.0 - morph
    half_height = 14.8 + .7 * morph
    box = QRectF(inset, core.y()-half_height, width-2*inset, 2*half_height)
    # Fade the tint and rim while the end is still wide enough to read as a capsule.
    glass_opacity = smooth((progress - .115) / .52)
    warning = state in {"interrupted", "failed"}
    if glass_opacity:
        p.save()
        p.setOpacity(p.opacity() * glass_opacity)
        draw_glass(p, box, core, glint if state and not quiet else 1, on_right, warning, progress)
        p.restore()
    t = palette()
    symbol = face.symbol if face and face.symbol else (
        "notice" if warning else "check" if state == "ended" or recent == "ended"
        else "stack" if active > 1 else "running" if state == "running" else "")
    tone = getattr(t, face.tone) if face else (t.error if warning else t.success if symbol == "check"
                                            else t.icon if symbol == "stack" else t.warm)
    icon_mix = smooth((progress - .52) / .40)
    pearl_alpha = 1. - smooth((progress - .20) / .66)
    if pearl_alpha > 0. or not symbol:
        p.save()
        p.setOpacity(p.opacity() * pearl_alpha if symbol else p.opacity())
        radius = (14.65 - docked * 8.65) * (.95 if pressed else 1.)
        draw_pearl(p, core, radius, hover, docked, state, light)
        p.restore()
    if symbol and icon_mix > 0.:
        p.save()
        p.setOpacity(p.opacity() * icon_mix)
        glyph(p, symbol, core, tone, 1.05)
        p.restore()
    if unread:
        badge_x = core.x() + (8 if on_right else -8)
        badge_y = core.y() - (5 if docked > .75 else 9)
        p.setPen(QPen(QColor(t.base), .8))
        pulse = sin(pi * glint) if quiet else 0
        size = 2.65 + .85 * pulse
        ellipse(p, badge_x, badge_y, size, size, QColor(t.error if alert else t.highlight if pulse > .18 else t.warm))
        p.setPen(Qt.PenStyle.NoPen)
    if light and (light.paused or light.completed) and docked < .50:
        center = core + QPointF(-5 if on_right else 5, 4)
        ellipse(p, center.x(), center.y(), 4., 4., color("#1b304a", 193))
        glyph(p, "check" if light.completed else "pause", center, "#fff1dc", .63)
    fade = smooth((progress - .66) / .28)
    if state and fade > 0:
        p.save()
        p.setOpacity(p.opacity() * fade)
        detail_opacity = smooth((progress - .80) / .19)
        if face is None:
            draw_activity(p, width, height, on_right, state, active, recent, finished, elapsed, change, detail_opacity)
        else:
            draw_face(p, box, on_right, face, detail_opacity)
        p.restore()
