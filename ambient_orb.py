"""Visual timing for the desktop pearl. No task or timer state is stored here."""
from dataclasses import dataclass, field
from random import uniform


HOVER_LIGHT = .25
HOVER_OPEN = .60
HOVER_LEAVE = .27
CHARGE = .10
STRIP_OPEN = .24
STRIP_CLOSE = .20
MERGE = 2.1
MAX_DEFER = 12.
START_DEFER = 2.
FEEDBACK_PRIORITY = {"start": 1, "ended": 2, "unknown": 3, "failed": 4, "interrupted": 4, "session": 5, "session_done": 6}
HOLD = {"start": 1.45, "ended": 1.8, "unknown": 1.75, "failed": 1.95, "interrupted": 1.95, "session": 1.55, "session_done": 1.95}


@dataclass
class Feedback:
    queued: float
    events: dict = field(default_factory=dict)
    shown: float | None = None
    expires: float = 0.

    @property
    def kind(self):
        return max(self.events.values(), key=FEEDBACK_PRIORITY.__getitem__)

    def add(self, now, events):
        self.events.update(events)
        if self.shown is not None:
            # Update an open capsule in place, with a hard cap for bursty streams.
            self.expires = min(self.shown + CHARGE + MERGE + HOLD[self.kind], now + HOLD[self.kind])

    def stale(self, now):
        if self.shown is not None:
            return now >= self.expires
        defer = START_DEFER if self.kind == "start" else MAX_DEFER
        return now - self.queued > defer

    def start(self, now, reduced):
        self.shown = now
        self.expires = now + HOLD[self.kind] + (0. if reduced else CHARGE + STRIP_OPEN)


class AmbientOrb:
    def __init__(self, now):
        self.codex = None
        self.session = None
        self.entered = None
        self.last_inside = None
        self.hover_open = False
        self.reflection_at = now + uniform(12., 20.)

    def queue_codex(self, now, events):
        if not events:
            return
        if self.codex is None or self.codex.stale(now):
            self.codex = Feedback(now)
        self.codex.add(now, events)

    def queue_session(self, now, done=False):
        self.session = Feedback(now, {"session": "session_done" if done else "session"})

    def update_hover(self, now, inside, enabled):
        if not enabled:
            self.entered = self.last_inside = None
            self.hover_open = False
        elif inside:
            if self.entered is None:
                self.entered = now
            self.last_inside = now
            self.hover_open = self.hover_open or now - self.entered >= HOVER_OPEN
        elif self.last_inside is None or not self.hover_open or now - self.last_inside > HOVER_LEAVE:
            self.entered = self.last_inside = None
            self.hover_open = False
        return self.entered is not None and now - self.entered >= HOVER_LIGHT

    def feedback(self, now, eligible, reduced):
        for slot in ("session", "codex"):
            item = getattr(self, slot)
            if item is not None and item.stale(now):
                setattr(self, slot, None)
        if not eligible:
            return None, 0.
        item = self.session or self.codex
        if item is None:
            return None, 0.
        if item.shown is None:
            item.start(now, reduced)
        age = now - item.shown
        if not reduced and age < CHARGE:
            return None, max(.001, age / CHARGE)
        return item, 0.

    def interrupt_visible(self):
        if self.codex and self.codex.shown is not None:
            self.codex = None
        if self.session and self.session.shown is not None:
            self.session = None
        self.update_hover(0., False, False)

    def clear(self):
        self.codex = self.session = None
        self.update_hover(0., False, False)

    def reflection(self, now):
        duration = 1.35
        if now > self.reflection_at + duration:
            self.reflection_at = now + uniform(12., 20.)
        return max(0., (now - self.reflection_at) / duration)
