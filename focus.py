"""Deadline-based local focus and break sessions."""
from math import ceil
from time import time


class FocusSession:
    def __init__(self):
        self.phase = "idle"
        self.duration = 0
        self.deadline = None
        self.paused_remaining = 0

    def start(self, phase, seconds):
        self.phase = phase
        self.duration = seconds
        self.deadline = time() + seconds

    @property
    def running(self):
        return self.phase in {"focus", "break"}

    @property
    def remaining(self):
        if not self.running:
            return 0
        if self.deadline is None:
            return self.paused_remaining
        return max(0, min(self.duration, self.deadline - time()))

    @property
    def progress(self):
        return self.remaining / self.duration if self.duration else 0

    @property
    def clock_text(self):
        minutes, seconds = divmod(ceil(self.remaining), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def toggle_pause(self):
        if self.deadline is None:
            self.deadline = time() + self.paused_remaining
        else:
            self.paused_remaining = self.remaining
            self.deadline = None

    def check_deadline(self):
        if not self.running or self.deadline is None or self.remaining > 0:
            return False
        self.phase = "focus_done" if self.phase == "focus" else "break_done"
        self.deadline = None
        return True

    def clear(self):
        self.phase = "idle"
        self.deadline = None

