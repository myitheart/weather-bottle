"""Local weekday work schedule and its settings panel."""
from dataclasses import dataclass

from PySide6.QtCore import QDateTime, QTime
from PySide6.QtWidgets import QHBoxLayout, QLabel

from glass_dialog import GlassDialog, form_label
from pearl_style import text_role
from typography import font
from reminders import ReminderTimePart


@dataclass(frozen=True)
class Workday:
    start: int = 9 * 60
    end: int = 18 * 60

    @classmethod
    def load(cls, settings):
        start = settings.value("workday_start", 540, type=int)
        end = settings.value("workday_end", 1080, type=int)
        return cls(start, end) if 0 <= start < end < 1440 else cls()

    def save(self, settings):
        settings.setValue("workday_start", self.start)
        settings.setValue("workday_end", self.end)

    def window(self, now):
        if now.date().dayOfWeek() > 5:
            return None
        start, end = (
            QDateTime(now.date(), QTime(*divmod(value, 60)), now.timeZone())
            for value in (self.start, self.end)
        )
        return start.toSecsSinceEpoch(), end.toSecsSinceEpoch()

    def end_label(self):
        hour, minute = divmod(self.end, 60)
        return f"{hour:02d}:{minute:02d}"


class WorkdayDialog(GlassDialog):
    def __init__(self, bottle, schedule):
        super().__init__(bottle, "下班日落", "工作日时间 · 周一至周五", "保存并启用")
        self.parts = []
        for name, value in (("上班", schedule.start), ("下班", schedule.end)):
            self.content.addWidget(form_label(name))
            row = QHBoxLayout()
            for unit, limit, number in zip(("时", "分"), (23, 59), divmod(value, 60)):
                part = ReminderTimePart(f"{name}{unit}", limit, number)
                self.parts.append(part)
                row.addWidget(part, 1)
                caption = QLabel(unit)
                caption.setFont(font("unit"))
                text_role(caption, "muted")
                row.addWidget(caption)
            self.content.addLayout(row)
        self.error = QLabel()
        self.error.setFixedHeight(18)
        self.error.setFont(font("hint"))
        text_role(self.error, "error")
        self.content.addWidget(self.error)
        order = []
        for part in self.parts:
            part.changed.connect(self.error.clear)
            order.extend((part.editor, part.arrow))
        order.extend((self.primary, self.cancel_button, self.close_button))
        for a, b in zip(order, order[1:]):
            self.setTabOrder(a, b)
        self.result_value = None

    def accept(self):
        if self.snapshot is not None:
            return
        hours, minutes, end_hour, end_minute = (part.number() for part in self.parts)
        if min(hours, minutes, end_hour, end_minute) < 0:
            self.error.setText("请选择有效的小时和分钟。")
            return
        start, end = hours * 60 + minutes, end_hour * 60 + end_minute
        if start >= end:
            self.error.setText("下班时间须晚于同一天的上班时间。")
            return
        self.result_value = Workday(start, end)
        super().accept()

