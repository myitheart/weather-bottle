"""Persistent local reminders and their input panel."""
from dataclasses import asdict, dataclass, replace
import json
from time import time
from uuid import uuid4

from PySide6.QtCore import QDate, QDateTime, QLocale, QPoint, QRectF, QTime, Qt, Signal
from PySide6.QtGui import QColor, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QCalendarWidget, QFrame, QGridLayout, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout,
    QWidget, QWidgetAction,
)

from glass_dialog import (
    GlassChip, GlassDialog, GlassGlyphButton, GlassNumberInput, GlassTextInput, NumberSpec, form_label,
)
from menu import FluentMenu
from pearl_style import css_color, palette, text_role, themed
from typography import draw_number, font


MAX_INTERVAL_MINUTES = 1440
SNOOZE_SECONDS = 600


def picker_style():
    return f"""QFrame#reminderPicker {{
        background: {palette().control}; border: 1px solid {palette().line}; border-radius: 10px;
    }}
    QFrame#reminderPicker[active="true"] {{ border-color: {palette().ice}; }}
    """


class ReminderCalendar(QCalendarWidget):
    def __init__(self):
        super().__init__()
        self.setLocale(QLocale("zh_CN"))
        self.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.SingleLetterDayNames)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setNavigationBarVisible(False)
        self.setFont(font("calendar_day"))
        self.setFixedSize(254, 198)
        themed(self, lambda: f"""
            QCalendarWidget QAbstractItemView {{
                background: {palette().base}; color: {palette().muted};
                selection-background-color: {palette().base}; outline: none;
            }}
        """)
        self.refresh_weekday_colors()

    def refresh_weekday_colors(self):
        for day in Qt.DayOfWeek:
            fmt = self.weekdayTextFormat(day)
            fmt.setForeground(QColor(palette().muted))
            fmt.setBackground(QColor(palette().base))
            self.setWeekdayTextFormat(day, fmt)

    def paintCell(self, painter, rect, date):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        today = date == QDate.currentDate()
        selected = date == self.selectedDate()
        box = QRectF(rect).adjusted(2, 2, -2, -2)
        t = palette()
        disabled = date < self.minimumDate() or date > self.maximumDate()
        if (selected or today) and not disabled:
            painter.setPen(QPen(css_color(t.border) if selected else QColor(t.ice), .8))
            painter.setBrush(css_color(t.selected if selected else t.control))
            painter.drawRoundedRect(box, 7, 7)
        tint = QColor(t.text if date.month() == self.monthShown() and not disabled else t.muted)
        if disabled:
            tint.setAlpha(117)
        painter.setPen(tint)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        role = "calendar_selected" if selected or today else "calendar_day"
        draw_number(painter, QRectF(rect), str(date.day()), role, center=True)
        painter.restore()


class ReminderDatePicker(QFrame):
    def __init__(self, value):
        super().__init__()
        self.setObjectName("reminderPicker")
        themed(self, picker_style)
        self.setMinimumHeight(38)
        self.initial_date = value
        row = QHBoxLayout(self)
        row.setContentsMargins(5, 2, 3, 2)
        row.setSpacing(2)
        self.editor = GlassTextInput(value.toString(Qt.DateFormat.ISODate), inset=True)
        self.editor.setFont(font("picker_number"))
        self.editor.setAccessibleName("提醒日期")
        self.editor.setPlaceholderText("年-月-日")
        self.editor.setMaxLength(10)
        row.addWidget(self.editor, 1)
        self.arrow = GlassGlyphButton("down", "选择日期", 27, 28)
        self.arrow.setAutoRepeat(False)
        self.arrow.clicked.connect(self.open_calendar)
        row.addWidget(self.arrow)

        self.popup = FluentMenu(self)
        panel = QFrame()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 2, 4, 3)
        layout.setSpacing(3)
        self.calendar = ReminderCalendar()
        self.calendar.setDateRange(QDate.currentDate(), QDate(9999, 12, 31))
        self.popup.aboutToShow.connect(self.calendar.refresh_weekday_colors)
        self.calendar.clicked.connect(self.choose)
        self.calendar.activated.connect(self.choose)
        header = QHBoxLayout()
        previous = GlassGlyphButton("left", "上个月", 27, 28)
        following = GlassGlyphButton("right", "下个月", 27, 28)
        previous.clicked.connect(self.calendar.showPreviousMonth)
        following.clicked.connect(self.calendar.showNextMonth)
        self.month = QLabel()
        self.month.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_role(self.month, "text")
        self.month.setFont(font("calendar_heading"))
        self.calendar.currentPageChanged.connect(self.show_month)
        header.addWidget(previous)
        header.addWidget(self.month, 1)
        header.addWidget(following)
        layout.addLayout(header)
        layout.addWidget(self.calendar)
        today = GlassChip("今天")
        today.setCheckable(False)
        today.clicked.connect(lambda: self.choose(QDate.currentDate()))
        layout.addWidget(today, alignment=Qt.AlignmentFlag.AlignRight)
        action = QWidgetAction(self.popup)
        action.setDefaultWidget(panel)
        self.popup.addAction(action)

    def show_month(self, year, month):
        self.month.setText(f"{year} 年 {month} 月")

    def open_calendar(self):
        value = self.date()
        if not value.isValid():
            value = self.initial_date
        self.calendar.setMinimumDate(QDate.currentDate())
        value = max(self.calendar.minimumDate(), value)
        self.calendar.setSelectedDate(value)
        self.calendar.setCurrentPage(value.year(), value.month())
        self.show_month(value.year(), value.month())
        self.popup.popup_at(self.mapToGlobal(QPoint(0, self.height())))
        self.calendar.setFocus(Qt.FocusReason.PopupFocusReason)

    def choose(self, value):
        self.editor.setText(value.toString(Qt.DateFormat.ISODate))
        self.popup.hide()
        self.editor.setFocus()

    def date(self):
        return QDate.fromString(self.editor.text().strip(), Qt.DateFormat.ISODate)


class ReminderTimePart(QFrame):
    changed = Signal()

    def __init__(self, name, limit, value):
        super().__init__()
        self.limit = limit
        self.setMinimumHeight(38)
        self.setObjectName("reminderPicker")
        themed(self, picker_style)
        row = QHBoxLayout(self)
        row.setContentsMargins(5, 2, 3, 2)
        row.setSpacing(2)
        self.editor = GlassTextInput(f"{value:02d}", inset=True)
        self.editor.setFont(font("picker_number"))
        self.editor.setAccessibleName(name)
        self.editor.setMaxLength(2)
        self.editor.setValidator(QIntValidator(0, limit, self))
        self.editor.textChanged.connect(self.changed)
        self.setFocusProxy(self.editor)
        row.addWidget(self.editor, 1)
        self.arrow = GlassGlyphButton("down", f"选择{name}", 27, 28)
        self.arrow.setAutoRepeat(False)
        self.arrow.clicked.connect(self.open_grid)
        row.addWidget(self.arrow)
        self.popup = FluentMenu(self)
        action = QWidgetAction(self.popup)
        panel = QFrame()
        grid = QGridLayout(panel)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setSpacing(3)
        columns = 6 if limit == 23 else 10
        self.options = []
        for number in range(limit + 1):
            chip = GlassChip(f"{number:02d}", numeric=True)
            chip.setFixedWidth(30)
            chip.clicked.connect(lambda checked=False, selected=number: self.choose(selected))
            grid.addWidget(chip, number // columns, number % columns)
            self.options.append(chip)
        action.setDefaultWidget(panel)
        self.popup.addAction(action)

    def number(self):
        text = self.editor.text()
        if text.isdecimal() and int(text) <= self.limit:
            return int(text)
        return -1

    def open_grid(self):
        current = self.number()
        for number, chip in enumerate(self.options):
            chip.setChecked(number == current)
        self.popup.popup_at(self.mapToGlobal(QPoint(0, self.height())))

    def choose(self, number):
        self.editor.setText(f"{number:02d}")
        self.popup.hide()
        self.editor.setFocus()


@dataclass(frozen=True)
class Reminder:
    id: str
    text: str
    due: int
    interval_minutes: int = 0
    scheduled_due: int = 0

    def time_label(self):
        return QDateTime.fromSecsSinceEpoch(self.due).toString("MM-dd HH:mm")

    def interval_label(self):
        return f"每 {self.interval_minutes} 分钟"


class ReminderSchedule:
    def __init__(self, settings):
        self.settings = settings
        try:
            stored = json.loads(settings.value("local_reminders", "[]", type=str))
        except ValueError:
            stored = []
        self.items = {}
        for entry in stored if isinstance(stored, list) else []:
            if (isinstance(entry, dict) and isinstance(entry.get("id"), str)
                    and isinstance(entry.get("text"), str) and entry["text"].strip()
                    and type(entry.get("due")) is int and 0 < entry["due"] <= 253402300799):
                interval = entry.get("interval_minutes", 0)
                if type(interval) is not int or not 0 <= interval <= MAX_INTERVAL_MINUTES:
                    interval = 0
                scheduled = entry.get("scheduled_due", 0)
                if not interval or type(scheduled) is not int or not 0 < scheduled <= entry["due"]:
                    scheduled = 0
                reminder = Reminder(entry["id"], entry["text"][:40], entry["due"], interval, scheduled)
                self.items[reminder.id] = reminder

    def ordered(self):
        return sorted(self.items.values(), key=lambda item: item.due)

    def next_due(self):
        now = time()
        return min((item for item in self.items.values() if item.due <= now),
                   key=lambda item: item.due, default=None)

    def add(self, text, due, interval_minutes=0):
        reminder = Reminder(uuid4().hex, text, due, interval_minutes)
        self.items[reminder.id] = reminder
        self.save()
        return reminder

    def remove(self, reminder_id):
        if self.items.pop(reminder_id, None) is not None:
            self.save()

    def resolve(self, reminder_id, snooze=False):
        item = self.items.get(reminder_id)
        if item is None:
            return
        now = int(time())
        scheduled = item.scheduled_due or item.due
        if snooze:
            self.items[item.id] = replace(item, due=now + SNOOZE_SECONDS,
                                          scheduled_due=scheduled if item.interval_minutes else 0)
        elif item.interval_minutes:
            interval = item.interval_minutes * 60
            # Keep the original cadence and collapse missed occurrences into the current alert.
            next_due = scheduled + max(1, (now - scheduled) // interval + 1) * interval
            self.items[item.id] = replace(item, due=next_due, scheduled_due=0)
        else:
            self.remove(reminder_id)
            return
        self.save()

    def save(self):
        self.settings.setValue("local_reminders", json.dumps([asdict(item) for item in self.ordered()], ensure_ascii=False))
        self.settings.sync()


class ReminderDialog(GlassDialog):
    def __init__(self, bottle):
        super().__init__(bottle, "添加本地提醒", "提醒内容", "添加提醒")
        self.editor = GlassTextInput()
        self.editor.setPlaceholderText("例如：起来喝杯水")
        self.editor.setAccessibleName("提醒内容")
        self.editor.setMaxLength(40)
        self.content.addWidget(self.editor)
        modes = QHBoxLayout()
        group = QButtonGroup(self)
        self.once = GlassChip("单次")
        self.repeat = GlassChip("循环")
        for button in (self.once, self.repeat):
            group.addButton(button)
            modes.addWidget(button, 1)
        self.once.setChecked(True)
        self.content.addLayout(modes)

        self.pages = QStackedWidget()
        self.content.addWidget(self.pages)
        once_page = QWidget()
        once_layout = QVBoxLayout(once_page)
        once_layout.setContentsMargins(0, 0, 0, 0)
        once_layout.setSpacing(8)
        self.pages.addWidget(once_page)
        once_layout.addWidget(form_label("提醒日期"))
        now = QDateTime.currentDateTime()
        default = now.addSecs(300 - now.time().second())
        self.date = ReminderDatePicker(default.date())
        once_layout.addWidget(self.date)
        once_layout.addWidget(form_label("提醒时间（24 小时制）"))
        row = QHBoxLayout()
        row.setSpacing(7)
        self.hour = ReminderTimePart("小时", 23, default.time().hour())
        self.minute = ReminderTimePart("分钟", 59, default.time().minute())
        for picker, unit in ((self.hour, "时"), (self.minute, "分")):
            row.addWidget(picker, 1)
            caption = QLabel(unit)
            text_role(caption, "muted")
            caption.setFont(font("unit"))
            row.addWidget(caption)
        once_layout.addLayout(row)

        repeat_page = QWidget()
        repeat_layout = QVBoxLayout(repeat_page)
        repeat_layout.setContentsMargins(0, 0, 0, 0)
        repeat_layout.setSpacing(8)
        self.pages.addWidget(repeat_page)
        repeat_layout.addWidget(form_label("提醒间隔"))
        self.interval = GlassNumberInput(NumberSpec(1, MAX_INTERVAL_MINUTES, "分钟"), 20)
        self.interval.editor.setAccessibleName("提醒间隔")
        repeat_layout.addWidget(self.interval)
        presets = QHBoxLayout()
        self.interval_chips = {}
        for minutes in (10, 20, 30, 60):
            chip = GlassChip(f"{minutes} 分钟")
            chip.clicked.connect(lambda checked=False, value=minutes: self.interval.set_value(value))
            presets.addWidget(chip, 1)
            self.interval_chips[minutes] = chip
        repeat_layout.addLayout(presets)
        self.repeat_hint = QLabel()
        self.repeat_hint.setWordWrap(True)
        self.repeat_hint.setFixedHeight(32)
        self.repeat_hint.setFont(font("hint"))
        text_role(self.repeat_hint, "muted")
        repeat_layout.addWidget(self.repeat_hint)
        self.error = QLabel()
        self.error.setFixedHeight(19)
        self.error.setFont(font("hint"))
        text_role(self.error, "error")
        self.content.addWidget(self.error)
        self.editor.textChanged.connect(self.error.clear)
        self.date.editor.textChanged.connect(self.error.clear)
        self.hour.changed.connect(self.error.clear)
        self.minute.changed.connect(self.error.clear)
        self.interval.changed.connect(self.update_interval_hint)
        self.repeat.toggled.connect(self.switch_mode)
        order = [self.editor, self.once, self.repeat, self.date.editor, self.date.arrow, self.hour.editor,
                 self.hour.arrow, self.minute.editor, self.minute.arrow, self.interval.editor, *self.interval.arrows,
                 *self.interval_chips.values(), self.primary, self.cancel_button, self.close_button]
        for first, second in zip(order, order[1:]):
            self.setTabOrder(first, second)
        self.update_interval_hint()
        self.result_value = None

    def switch_mode(self, repeat):
        self.pages.setCurrentIndex(int(repeat))
        self.error.clear()

    def update_interval_hint(self):
        value, _ = self.interval.validate()
        for minutes, chip in self.interval_chips.items():
            chip.setChecked(value == minutes)
        self.error.clear()
        self.repeat_hint.setText(f"保存后 {value} 分钟首次提醒，之后按此间隔循环。"
                                 if value is not None else "可输入 1 至 1440 分钟。")

    def accept(self):
        if self.snapshot is not None:
            return
        text = self.editor.text().strip()
        if not text:
            self.error.setText("请输入提醒内容。")
            self.editor.setFocus()
            return
        if self.repeat.isChecked():
            value, error = self.interval.validate()
            if error:
                self.error.setText(error)
                self.interval.editor.setFocus()
                return
            self.result_value = text, int(time()) + value * 60, value
            super().accept()
            return
        hour, minute = self.hour.number(), self.minute.number()
        if hour < 0 or minute < 0:
            self.error.setText("请选择小时和分钟。")
            (self.hour if hour < 0 else self.minute).setFocus()
            return
        date = self.date.date()
        if not date.isValid():
            self.error.setText("请选择日期，或输入 YYYY-MM-DD。")
            self.date.editor.setFocus()
            return
        when = QDateTime(date, QTime(hour, minute))
        if not when.isValid() or when.toSecsSinceEpoch() <= time():
            self.error.setText("请选择晚于当前时间的日期和时间。")
            self.hour.setFocus()
            return
        self.result_value = text, when.toSecsSinceEpoch()
        super().accept()

