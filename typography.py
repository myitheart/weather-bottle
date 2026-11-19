"""Typography for native controls and QPainter text in Dynamic Pearl."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF
from PySide6.QtWidgets import QApplication, QToolTip


REGULAR = QFont.Weight.Normal
MEDIUM = QFont.Weight.Medium
SEMIBOLD = QFont.Weight.DemiBold
FONT_RESOURCE = Path(__file__).with_name("assets") / "fonts" / "NotoSansSC-VF.ttf"
NOTO_FAMILIES = ("Noto Sans SC", "Noto Sans CJK SC")


@dataclass(frozen=True)
class TextStyle:
    pixels: int
    weight: QFont.Weight = REGULAR
    tracking: float = 0.
    tabular: bool = False


STYLES = {
    "capsule_title": TextStyle(13, SEMIBOLD, .10),
    "capsule_detail": TextStyle(11),
    "clock": TextStyle(13, MEDIUM, tabular=True),
    "count": TextStyle(13, MEDIUM, tabular=True),
    "panel_title": TextStyle(16, SEMIBOLD),
    "list_title": TextStyle(13, MEDIUM),
    "list_meta": TextStyle(12),
    "list_clock": TextStyle(12, MEDIUM, tabular=True),
    "dialog_title": TextStyle(16, SEMIBOLD),
    "body": TextStyle(13),
    "section_title": TextStyle(14, MEDIUM),
    "menu": TextStyle(13),
    "button": TextStyle(13, MEDIUM),
    "tile_title": TextStyle(13, MEDIUM, .08),
    "chip": TextStyle(12, MEDIUM),
    "input": TextStyle(14),
    "input_number": TextStyle(16, MEDIUM, .12, tabular=True),
    "unit": TextStyle(12),
    "hint": TextStyle(12),
    "dialog_hint": TextStyle(12, tracking=.06),
    "picker_number": TextStyle(13, MEDIUM, tabular=True),
    "picker_chip": TextStyle(12, MEDIUM, tabular=True),
    "calendar_day": TextStyle(12, tabular=True),
    "calendar_selected": TextStyle(12, MEDIUM, tabular=True),
    "calendar_heading": TextStyle(14, MEDIUM, tabular=True),
    "hover_title": TextStyle(15, MEDIUM),
    "callout_title": TextStyle(15, SEMIBOLD),
    "hourglass_clock": TextStyle(17, MEDIUM, tabular=True),
    "hourglass_clock_compact": TextStyle(15, MEDIUM, tabular=True),
}


def select_families(available, default, bundled=()):
    names = {family.casefold(): family for family in available}
    project = {family.casefold(): family for family in bundled}
    latin = names.get("segoe ui variable") or names.get("segoe ui") or default
    noto = next((family for name in NOTO_FAMILIES
                 if (family := project.get(name.casefold()) or names.get(name.casefold()))), None)
    chinese = names.get("microsoft yahei ui") or names.get("microsoft yahei") or default
    # Including the system CJK family also in the cascade lets Qt prefer the
    # preceding Noto family and keeps a final fallback for missing glyphs.
    return tuple(dict.fromkeys(family for family in (latin, noto, chinese) if family))


@lru_cache(maxsize=1)
def installed_families():
    font_id = QFontDatabase.addApplicationFont(str(FONT_RESOURCE)) if FONT_RESOURCE.is_file() else -1
    bundled = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else ()
    default = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    return select_families(QFontDatabase.families(), default, bundled)


@lru_cache(maxsize=1)
def variable_styles():
    return frozenset(QFontDatabase.styles("Segoe UI Variable"))


@lru_cache(maxsize=len(STYLES))
def font(role):
    token = STYLES[role]
    families = installed_families()
    result = QFont()
    result.setFamilies(list(families))
    result.setPixelSize(token.pixels)
    result.setWeight(token.weight)
    result.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    if families[0].casefold() == "segoe ui variable":
        optical = "Small" if token.pixels < 14 else "Text"
        name = f"{optical} Semibold" if token.weight == SEMIBOLD else optical
        if name in variable_styles():
            result.setStyleName(name)
        if token.weight == MEDIUM and hasattr(result, "setVariableAxis"):
            result.setVariableAxis(QFont.Tag("wght"), token.weight.value)
    if token.tracking:
        result.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, token.tracking)
    if token.tabular:
        result.setFeature(QFont.Tag("tnum"), 1)
    return result


def install_typography(app: QApplication):
    app.setFont(font("body"))
    QToolTip.setFont(font("hint"))


def metrics(painter, role):
    return QFontMetricsF(font(role), painter.device())


def text_baseline(painter, bounds, role):
    guess = metrics(painter, role)
    baseline = bounds.center().y() + (guess.ascent() - guess.descent()) / 2
    # The text may be painted in a scaled widget. Snap once in device coordinates.
    device = painter.deviceTransform()
    scale = device.m22()
    return (round(baseline * scale + device.dy()) - device.dy()) / scale if scale else baseline


def draw_line(painter, bounds, text, role, *, align=Qt.AlignmentFlag.AlignLeft, baseline=None):
    if not text or bounds.width() <= 0:
        return
    text_metrics = metrics(painter, role)
    text = text_metrics.elidedText(text, Qt.TextElideMode.ElideRight, bounds.width())
    width = text_metrics.horizontalAdvance(text)
    x = bounds.left()
    if align == Qt.AlignmentFlag.AlignRight:
        x = bounds.right() - width
    elif align == Qt.AlignmentFlag.AlignHCenter:
        x = bounds.center().x() - width / 2
    y = text_baseline(painter, bounds, role) if baseline is None else baseline
    painter.setFont(font(role))
    painter.drawText(QPointF(x, y), text)


@lru_cache(maxsize=len(STYLES))
def digit_advances(role):
    return tuple(QFontMetricsF(font(role)).horizontalAdvance(char) for char in "0123456789")


def number_width(painter, text, role):
    widths = digit_advances(role)
    if max(widths) - min(widths) < .04:
        return metrics(painter, role).horizontalAdvance(text)
    measure = metrics(painter, role)
    widest = max(measure.horizontalAdvance(digit) for digit in "0123456789")
    return sum(widest if char in "0123456789" else measure.horizontalAdvance(char) for char in text)


def draw_number(painter, bounds, text, role, *, baseline=None, center=False):
    if not text:
        return
    width = number_width(painter, text, role)
    left = bounds.center().x() - width / 2 if center else bounds.right() - width
    y = text_baseline(painter, bounds, role) if baseline is None else baseline
    painter.setFont(font(role))
    widths = digit_advances(role)
    if max(widths) - min(widths) < .04:
        painter.drawText(QPointF(left, y), text)
        return
    measure = metrics(painter, role)
    widest = max(measure.horizontalAdvance(digit) for digit in "0123456789")
    for char in text:
        native = measure.horizontalAdvance(char)
        slot = widest if char in "0123456789" else native
        painter.drawText(QPointF(left + (slot - native) / 2, y), char)
        left += slot

