"""Reusable glass controls and bottle-anchored input dialogs."""
from dataclasses import dataclass
import re

from PySide6.QtCore import QEvent, QEasingCurve, QPoint, QPointF, QRectF, Qt, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from landscape import color
from pearl_style import DesignTokens, css_color, glass, glyph, palette, snapshot, text_role, themed
from shiboken6 import isValid
from typography import draw_line, font


def form_label(text):
    label = QLabel(text)
    label.setFont(font("body"))
    label.setFixedHeight(18)
    text_role(label)
    return label


class GlassButton(QPushButton):
    def __init__(self, label, primary=False):
        super().__init__(label)
        self.setAutoDefault(False)
        self.setMinimumHeight(36)
        self.setFont(font("button"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        themed(self, lambda: button_style(primary))


def button_style(primary=False, *, chip=False):
    t = palette()
    bg = t.primary if primary else t.control
    hover = t.primary_hover if primary else t.hover
    return f"""
        QPushButton {{
            color: {t.text}; border: 1px solid {t.border if primary else t.line}; border-radius: {DesignTokens.CONTROL_RADIUS}px;
            padding: {"2px 5px" if chip else "3px 10px"}; background: {bg};
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:focus {{ border-color: {t.ice}; }}
        QPushButton:pressed {{ background: {t.pressed}; }}
        QPushButton:checked {{ background: {t.selected}; border-color: {t.border}; }}
        QPushButton:disabled {{ color: {t.muted}; background: transparent; }}
    """


class GlassChip(QPushButton):
    def __init__(self, label, *, numeric=False):
        super().__init__(label)
        self.setAutoDefault(False)
        self.setCheckable(True)
        self.setMinimumHeight(27)
        self.setFont(font("picker_chip" if numeric else "chip"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        themed(self, lambda: button_style(chip=True))


class GlassTile(QPushButton):
    def __init__(self, label, symbol, primary=False):
        super().__init__(label)
        self.symbol = symbol
        self.primary = primary
        self.setMinimumHeight(64)
        self.setFont(font("tile_title"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        t = palette()
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            box = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
            fill = (t.primary_hover if self.underMouse() else t.primary) if self.primary else (
                t.hover if self.underMouse() else t.control)
            if self.isDown():
                fill = t.pressed
            p.setBrush(css_color(fill))
            p.setPen(QPen(css_color(t.border if self.hasFocus() else t.line), .8))
            p.drawRoundedRect(box, 13, 13)
            glyph(p, self.symbol, QPointF(box.center().x(), 24), t.warm if self.primary else t.icon, 1.25)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.setPen(QColor(t.text))
            draw_line(p, QRectF(5, 36, self.width() - 10, 20), self.text(), "tile_title",
                      align=Qt.AlignmentFlag.AlignHCenter)


class GlassGlyphButton(QToolButton):
    def __init__(self, symbol, name, width, height):
        super().__init__()
        self.symbol = symbol
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoRepeat(symbol in {"left", "right", "up", "down"})

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            t = palette()
            if self.underMouse() or self.isDown() or self.hasFocus() or self.isChecked():
                p.setPen(QPen(color(t.ice, 185), .8) if self.hasFocus() else Qt.PenStyle.NoPen)
                p.setBrush(css_color(t.primary if self.isChecked() else t.pressed if self.isDown() else t.hover))
                p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
            if self.symbol in {"pin", "check"}:
                tint = t.success if self.symbol == "check" else t.warm if self.isChecked() else t.icon
                glyph(p, self.symbol, QRectF(self.rect()).center(), tint)
                return
            p.translate(self.width() / 2, self.height() / 2)
            p.setPen(QPen(QColor(DesignTokens.TEXT), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if self.symbol == "close":
                p.drawLine(QPointF(-4, -4), QPointF(4, 4))
                p.drawLine(QPointF(4, -4), QPointF(-4, 4))
            else:
                if self.symbol in {"left", "right"}:
                    p.rotate(90 if self.symbol == "left" else -90)
                direction = -1 if self.symbol == "up" else 1
                p.drawLine(QPointF(-4, -2 * direction), QPointF(0, 2 * direction))
                p.drawLine(QPointF(0, 2 * direction), QPointF(4, -2 * direction))


class GlassTextInput(QLineEdit):
    def __init__(self, value="", *, inset=False):
        super().__init__(value)
        self.setFont(font("input"))
        themed(self, lambda: f"""
            QLineEdit {{
                color: {palette().text}; selection-background-color: #5479a4; selection-color: white;
                background: {"transparent" if inset else palette().control};
                border: {"none" if inset else "1px solid " + palette().line};
                border-radius: 10px; padding: 3px 8px;
            }}
            QLineEdit:focus {{ border-color: {palette().ice}; }}
        """)
        if not inset:
            self.setMinimumHeight(38)


@dataclass(frozen=True)
class NumberSpec:
    minimum: int
    maximum: int
    unit: str
    step: int = 1
    multiplier: int = 1


class GlassNumberInput(QFrame):
    changed = Signal()

    def __init__(self, spec, value):
        super().__init__()
        self.spec = spec
        self.setFixedHeight(51)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 5, 4)
        row.setSpacing(7)
        self.editor = GlassTextInput(inset=True)
        self.editor.setFont(font("input_number"))
        self.editor.setMaxLength(32)
        self.editor.setAccessibleName("数值")
        self.editor.installEventFilter(self)
        self.editor.textChanged.connect(self.changed)
        self.editor.textChanged.connect(self.update)
        self.setFocusProxy(self.editor)
        row.addWidget(self.editor, 1)
        self.unit = QLabel()
        self.unit.setFont(font("unit"))
        text_role(self.unit, "muted")
        row.addWidget(self.unit)
        divider = QFrame()
        divider.setFixedSize(1, 29)
        themed(divider, lambda: f"background: {palette().line};")
        row.addWidget(divider)
        arrows = QVBoxLayout()
        arrows.setSpacing(0)
        self.arrows = []
        for direction, name in ((1, "增加"), (-1, "减少")):
            button = GlassGlyphButton("up" if direction == 1 else "down", name, 29, 20)
            button.clicked.connect(lambda checked=False, delta=direction: self.step_by(delta))
            arrows.addWidget(button)
            self.arrows.append(button)
        row.addLayout(arrows)
        self.configure(spec, value)

    def configure(self, spec, value):
        self.spec = spec
        self.unit.setText(spec.unit)
        self.editor.setAccessibleDescription(f"{spec.minimum} 至 {spec.maximum} {spec.unit}")
        self.set_value(value)

    def set_value(self, value):
        self.editor.setText(str(value) if value is not None else "")
        self.editor.selectAll()

    def validate(self):
        raw = self.editor.text().strip()
        if not raw:
            return None, f"请输入数值（{self.spec.unit}）。"
        if re.fullmatch(r"[+-]?[0-9]+", raw) is None:
            return None, f"请输入整数（{self.spec.unit}）。"
        value = int(raw)
        if not self.spec.minimum <= value <= self.spec.maximum:
            return None, f"请输入 {self.spec.minimum} 至 {self.spec.maximum} {self.spec.unit}。"
        return value, ""

    def step_by(self, direction):
        raw = self.editor.text().strip()
        value = int(raw) if re.fullmatch(r"[+-]?[0-9]+", raw) else self.spec.minimum - self.spec.step
        self.set_value(min(self.spec.maximum, max(self.spec.minimum, value + direction * self.spec.step)))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.step_by(1 if event.key() == Qt.Key.Key_Up else -1)
            return True
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.update()
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            box = QRectF(self.rect()).adjusted(.6, .6, -.6, -.6)
            active = self.editor.hasFocus()
            invalid = self.validate()[0] is None
            glass(p, box, "control", radius=10)
            if active or invalid:
                p.setPen(QPen(QColor(DesignTokens.ERROR if invalid else palette().ice), .8))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(box, 10, 10)


class PopupAnimation(QVariantAnimation):
    def play(self, start, end, *, easing=None):
        self.stop()
        self.setStartValue(float(start))
        self.setEndValue(float(end))
        self.setDuration(max(70, round((DesignTokens.OPEN_MS if end else DesignTokens.CLOSE_MS) * abs(end - start))))
        self.setEasingCurve(easing if easing is not None
                            else QEasingCurve.Type.OutCubic if end else QEasingCurve.Type.InCubic)
        self.start()


def popup_geometry(anchor, size, area):
    w, h = size.width(), size.height()
    x, y = anchor.center().x() - w // 2, anchor.center().y() - h // 2
    gap = 3
    candidates = (
        (QPoint(x, anchor.bottom() + 1 + gap), QPoint(0, -7), area.bottom() - anchor.bottom(), h),
        (QPoint(x, anchor.top() - h - gap), QPoint(0, 7), anchor.top() - area.top(), h),
        (QPoint(anchor.left() - w - gap, y), QPoint(7, 0), anchor.left() - area.left(), w),
        (QPoint(anchor.right() + 1 + gap, y), QPoint(-7, 0), area.right() - anchor.right(), w),
    )
    pos, offset, _, _ = next(
        (candidate for candidate in candidates if candidate[2] >= candidate[3] + gap),
        max(candidates, key=lambda candidate: candidate[2] - candidate[3]),
    )
    return QPoint(max(area.left(), min(pos.x(), area.right() - w + 1)),
                  max(area.top(), min(pos.y(), area.bottom() - h + 1))), offset


class GlassDialog(QDialog):
    def __init__(self, bottle, title, description, primary):
        flags = Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        if bottle.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(bottle, flags)
        self.bottle = bottle
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedWidth(DesignTokens.WIDTH)
        self.progress = 1.
        self.snapshot = None
        self.pending_result = None
        self.offset = QPoint()
        self.animation = PopupAnimation(self)
        self.animation.valueChanged.connect(self.draw_frame)
        self.animation.finished.connect(self.finish_animation)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*(DesignTokens.SHADOW,) * 4)
        self.panel = QWidget()
        outer.addWidget(self.panel)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(DesignTokens.PADDING, 14, DesignTokens.PADDING, 15)
        layout.setSpacing(DesignTokens.GAP)
        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(bottle.windowIcon().pixmap(26, 26))
        header.addWidget(mark)
        caption = QLabel(title)
        caption.setFont(font("dialog_title"))
        text_role(caption, "text")
        header.addWidget(caption, 1)
        self.close_button = GlassGlyphButton("close", "关闭", 27, 27)
        self.close_button.clicked.connect(self.reject)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.content = QVBoxLayout()
        self.content.setSpacing(8)
        self.content.addWidget(form_label(description))
        layout.addLayout(self.content)
        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.primary = GlassButton(primary, primary=True)
        self.primary.clicked.connect(self.accept)
        self.primary.setDefault(True)
        self.cancel_button = GlassButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.primary, 3)
        actions.addWidget(self.cancel_button, 2)
        layout.addLayout(actions)

    def open_near_bottle(self, focus):
        self.ensurePolished()
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())
        anchor = self.bottle.frameGeometry()
        screen = QApplication.screenAt(anchor.center()) or self.bottle.screen()
        pos, self.offset = popup_geometry(anchor, self.size(), screen.availableGeometry())
        self.move(pos)
        self.initial_focus = focus
        # Grab the composed panel once, then animate that image at the same window position.
        self.snapshot = snapshot(self)
        self.progress = 0.
        self.panel.setVisible(False)
        self.open()
        self.raise_()
        self.activateWindow()
        self.animation.play(0., 1.)

    def draw_frame(self, value):
        self.progress = value
        self.update()

    def finish_animation(self):
        if self.pending_result is not None:
            super().done(self.pending_result)
            return
        self.snapshot = None
        self.panel.show()
        self.initial_focus.setFocus(Qt.FocusReason.OtherFocusReason)
        if isinstance(self.initial_focus, QLineEdit):
            self.initial_focus.selectAll()
        self.update()

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    def done(self, result):
        if self.pending_result is not None:
            return
        if not self.isVisible():
            super().done(result)
            return
        self.pending_result = result
        if self.snapshot is None:
            self.snapshot = snapshot(self)
        self.panel.hide()
        self.animation.play(self.progress, 0.)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.snapshot is None:
                self.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self.snapshot is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.setOpacity(self.progress)
                box = QRectF(self.rect())
                shrink = (1 - self.progress) * .05
                box.adjust(box.width() * shrink / 2, box.height() * shrink / 2,
                           -box.width() * shrink / 2, -box.height() * shrink / 2)
                box.translate(QPointF(self.offset) * (1 - self.progress))
                p.drawPixmap(box, self.snapshot, QRectF(self.snapshot.rect()))
                return
            self.paint_glass(p)

    def paint_glass(self, p):
        box = QRectF(self.rect()).adjusted(9, 7, -9, -10)
        glass(p, box, "dialog")



class GlassNumberDialog(GlassDialog):
    def __init__(self, bottle, title, description, primary, spec, value, hint, *,
                 alternate=None, presets=()):
        super().__init__(bottle, title, description, primary)
        self.hint_text = hint
        self.alternate = alternate
        self.result_value = None
        self.exact_value = None
        self.changing_unit = False
        self.number = GlassNumberInput(spec, value)
        self.content.addWidget(self.number)
        tab_order = [self.number.editor, *self.number.arrows]
        if alternate:
            units = QHBoxLayout()
            units.setSpacing(6)
            self.unit_chips = {}
            for option in (spec, alternate):
                chip = GlassChip(option.unit)
                chip.clicked.connect(lambda checked=False, selected=option: self.select_unit(selected))
                self.unit_chips[option] = chip
                units.addWidget(chip)
                tab_order.append(chip)
            units.addStretch()
            self.content.addLayout(units)
        self.hint = QLabel()
        self.hint.setFont(font("dialog_hint"))
        self.hint.setWordWrap(True)
        self.hint.setFixedHeight(31)
        self.content.addWidget(self.hint)
        self.presets = {}
        self.preset_spec = spec
        if presets:
            row = QHBoxLayout()
            row.setSpacing(5)
            for preset in presets:
                chip = GlassChip(f"{preset} {self.preset_spec.unit}")
                chip.clicked.connect(lambda checked=False, selected=preset: self.apply_preset(selected))
                row.addWidget(chip, 1)
                self.presets[preset] = chip
                tab_order.append(chip)
            self.content.addLayout(row)
        tab_order.extend((self.primary, self.cancel_button, self.close_button))
        for first, second in zip(tab_order, tab_order[1:]):
            self.setTabOrder(first, second)
        self.number.changed.connect(self.on_input_changed)
        self.refresh_hint()

    def select_unit(self, spec):
        current = self.number.spec
        if current != spec:
            value, _ = self.number.validate()
            if value is not None:
                self.exact_value = value * current.multiplier
            self.changing_unit = True
            factor = spec.multiplier
            converted = None if self.exact_value is None or self.exact_value % factor else self.exact_value // factor
            self.number.configure(spec, converted)
            self.changing_unit = False
        self.refresh_hint()
        self.number.editor.setFocus()
        self.number.editor.selectAll()

    def apply_preset(self, value):
        self.select_unit(self.preset_spec)
        self.number.set_value(value)
        self.refresh_hint()

    def on_input_changed(self):
        if not self.changing_unit:
            self.exact_value = None
            self.refresh_hint()

    def refresh_hint(self):
        value, error = self.number.validate()
        spec = self.number.spec
        if self.alternate:
            for option, chip in self.unit_chips.items():
                chip.setChecked(option == spec)
        for preset, chip in self.presets.items():
            chip.setChecked(spec == self.preset_spec and value == preset)
        text_role(self.hint, "error" if error else "muted")
        if error and self.exact_value is not None:
            error = "请输入整分钟，或切回秒以保留原时长。"
        self.hint.setText(error or self.hint_text(value, spec.unit, spec.multiplier))

    def accept(self):
        if self.snapshot is not None:
            return
        value, error = self.number.validate()
        if error:
            self.refresh_hint()
            self.number.editor.setFocus()
            return
        self.result_value = value * self.number.spec.multiplier
        super().accept()



class CityDialog(GlassDialog):
    def __init__(self, bottle, search):
        super().__init__(bottle, "设置城市", "搜索城市，然后选择匹配地点。", "搜索")
        self.search = search
        self.generation = 0
        self.locations = []
        self.result_value = None
        self.editor = GlassTextInput()
        self.editor.setPlaceholderText("例如：上海")
        self.editor.setAccessibleName("城市名称")
        self.editor.setMaxLength(80)
        self.content.addWidget(self.editor)
        self.results = QListWidget()
        self.results.setFont(font("body"))
        self.results.setAccessibleName("城市搜索结果")
        self.results.setFixedHeight(108)
        themed(self.results, lambda: f"""
            QListWidget {{ color: {palette().text}; background: {palette().control};
                border: 1px solid {palette().line}; border-radius: 9px; padding: 4px; outline: none; }}
            QListWidget::item {{ padding: 5px 7px; border-radius: 5px; }}
            QListWidget::item:selected {{ color: {palette().text}; background: {palette().selected}; }}
            QListWidget::item:hover {{ background: {palette().hover}; }}
        """)
        self.content.addWidget(self.results)
        self.results.hide()
        self.hint = QLabel("支持中文或英文城市名")
        self.hint.setFont(font("dialog_hint"))
        self.hint.setWordWrap(True)
        text_role(self.hint, "muted")
        self.content.addWidget(self.hint)
        self.editor.textChanged.connect(self.reset_query)
        self.results.itemDoubleClicked.connect(lambda _: self.accept())
        self.setTabOrder(self.editor, self.results)
        self.setTabOrder(self.results, self.primary)

    def reset_query(self):
        self.generation += 1
        self.locations = []
        self.results.clear()
        if not self.results.isHidden():
            self.results.hide()
            self.reposition_contents()
        self.primary.setEnabled(True)
        self.primary.setText("搜索")
        self.hint.setText("支持中文或英文城市名")

    def reposition_contents(self):
        if not self.isVisible():
            return
        self.panel.layout().activate()
        self.layout().activate()
        self.setFixedHeight(self.sizeHint().height())
        anchor = self.bottle.frameGeometry()
        position, _ = popup_geometry(anchor, self.size(), self.bottle.screen().availableGeometry())
        self.move(position)

    def accept(self):
        if self.locations:
            row = self.results.currentRow()
            if 0 <= row < len(self.locations):
                self.result_value = self.locations[row]
                super().accept()
            return
        query = self.editor.text().strip()
        if not query:
            self.hint.setText("请输入城市名称")
            return
        self.generation += 1
        generation = self.generation
        self.primary.setEnabled(False)
        self.hint.setText("正在搜索…")

        def populate(locations):
            if not isValid(self) or not self.isVisible() or self.pending_result is not None:
                return
            if generation != self.generation:
                return
            self.primary.setEnabled(True)
            if not locations:
                self.hint.setText("搜索暂不可用，请重试" if locations is None else "未找到城市，可试试英文名")
                return
            self.locations = locations
            for location in locations:
                item = QListWidgetItem(f"{location.name}   ·   {location.latitude:.2f}, {location.longitude:.2f}")
                self.results.addItem(item)
            self.results.show()
            self.reposition_contents()
            self.results.setCurrentRow(0)
            self.results.setFocus()
            self.primary.setText("使用此城市")
            self.hint.setText(f"找到 {len(locations)} 个匹配地点")

        self.search(query, populate)


class GlassNotice(GlassDialog):
    def __init__(self, bottle, title, message):
        super().__init__(bottle, title, message, "关闭")
        self.result_value = None
        self.cancel_button.hide()
        for label in self.findChildren(QLabel):
            label.setWordWrap(True)
