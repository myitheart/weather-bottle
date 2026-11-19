"""Date windows based on local calendar days, with UTC millisecond bounds."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone


PERIODS = {"today": "今天", "yesterday": "昨天", "last-7-days": "近 7 天"}


@dataclass(frozen=True)
class Window:
    period: str
    start: int
    end: int
    as_of: int
    zone: str

    @property
    def cutoff(self):
        return min(self.end, self.as_of)

    def contains(self, millisecond):
        return millisecond is not None and self.start <= millisecond < self.cutoff


def make_window(period, as_of, *, zone=None, selected_day=None):
    instant = datetime.fromtimestamp(as_of / 1000, timezone.utc)
    local = instant.astimezone(zone)
    day = local.date()
    if selected_day is not None:
        if selected_day > day:
            raise ValueError("未来日期不能生成成果草稿。")
        first, last = selected_day, selected_day + timedelta(days=1)
    else:
        first = day - timedelta(days={"today": 0, "yesterday": 1, "last-7-days": 6}[period])
        last = day if period == "yesterday" else day + timedelta(days=1)

    def midnight(date):
        return int(datetime.combine(date, time.min, zone).timestamp()) * 1000

    return Window(period, midnight(first), midnight(last), as_of, local.tzname() or "local")


def local_time(milliseconds):
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).astimezone().isoformat(timespec="milliseconds")
