from __future__ import annotations

from dataclasses import asdict
import math
from random import shuffle
import sys
from time import monotonic, time

from PySide6.QtCore import QDateTime, QPoint, QRect, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCursor, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

from activity_panel import ActivityPanel, THREAD_ID
from ambient_orb import AmbientOrb, STRIP_CLOSE, STRIP_OPEN
from activity_visual import (
    CAPSULE_WIDTH, GLINT_SECONDS, ORB_SIZE,
    CapsuleFace, PearlLight, compact_geometry, draw_compact, pearl_pixmap, smooth,
)
from codex_activity import (
    NOTICE_SECONDS, REVIEW_STATES, activity_expiry, display_name, install_global_hooks,
    read_activities, read_pin, read_records, read_scope, save_pin, set_scope,
)
from codex_links import open_codex_thread
from focus import FocusSession
from focus_visual import FocusCapsule
from glass_dialog import CityDialog, GlassNotice, GlassNumberDialog, NumberSpec
from pearl_style import DesignTokens, apply_appearance
from hover_card import BottleHoverCard, HoverContent
from hourglass import HourglassRenderer, morph_outline
from landscape import SIZE, raster
from menu import FluentMenu, line_icon
from quick_panel import QuickPanel
from renderer import BottleRenderer
from reminders import ReminderDialog, ReminderSchedule
from typography import install_typography
from scenes import GROUPS, WEATHER
from weather import Location, WeatherService
from workday import Workday, WorkdayDialog
from workday_visual import WorkdayFireworks, draw_workday_indicator
from work_memory_panel import WorkMemoryPanel


MANUAL_DURATION_MS = 5 * 60 * 1000
SHUFFLE_DEFAULT_SECONDS = 60
SHUFFLE_MAX_SECONDS = 2_147_483  # QTimer stores its millisecond interval in a signed int.
SHUFFLE_PRESETS = {5: "5 秒", 30: "30 秒", 60: "1 分钟"}
SESSION_MAX_SECONDS = 86_400
BREAK_PRESETS = (3, 5, 10, 15)
DEFAULT_BREAK_MINUTES = 5
WEATHER_REFRESH_MS = 5 * 60 * 1000
WEATHER_RETRY_MS = 30 * 1000
SCALES = (80, 100, 125, 150)
TRANSITION = 0.82
SUNSET_CELEBRATION_SECONDS = 10
IDLE_FRAME_MS = 33
MORPH_FRAME_MS = 16
PEARL_IDLE_MS = 100
PEARL_ACTIVE_MS = 55
PEARL_STATIC_MS = 125
BOTTLE_OPEN_SECONDS = .34
BOTTLE_CLOSE_SECONDS = .30
MAX_WIDGET_SIZE = 16_777_215


class WeatherBottle(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("WeatherBottle", "WeatherBottle")
        self.appearance = self.settings.value("pearl_appearance", "system", type=str)
        if self.appearance not in {"system", "light", "dark"}:
            self.appearance = "system"
        apply_appearance(self.appearance)
        self.weather = "rain"
        self.location = None
        self.current_weather = None
        self.location_generation = 0
        self.fetching = False
        self.weather_status = "正在获取本地天气"
        self.service = WeatherService(self)
        try:
            saved_location = self.settings.value("weather_city")
            if saved_location:
                self.location = Location.from_data(saved_location)
        except (TypeError, ValueError, KeyError, AttributeError):
            pass

        self.manual_timer = QTimer(self)
        self.manual_timer.setSingleShot(True)
        self.manual_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.manual_timer.timeout.connect(self.follow_weather)
        self.shuffle_timer = QTimer(self)
        saved_interval = self.settings.value("shuffle_interval_seconds", SHUFFLE_DEFAULT_SECONDS, type=int)
        self.shuffle_seconds = saved_interval if 1 <= saved_interval <= SHUFFLE_MAX_SECONDS else SHUFFLE_DEFAULT_SECONDS
        self.shuffle_timer.setInterval(self.shuffle_seconds * 1000)
        self.shuffle_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.shuffle_timer.timeout.connect(self.next_random_scene)
        self.shuffle_scenes = []
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh_weather)
        self.pinned = self.settings.value("pinned", True, type=bool)
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | (Qt.WindowType.WindowStaysOnTopHint if self.pinned else Qt.WindowType(0))
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("灵动珠 Dynamic Pearl")
        saved_scale = self.settings.value("scale", 100, type=int)
        self.bottle_scale = saved_scale if saved_scale in SCALES else 100
        self.resize_bottle()
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.renderer = BottleRenderer()
        self.previous_scene = None
        self.transition_start = 0.0
        self.hover = 0.0
        self.press_position = None
        self.start_position = QPoint()
        self.last_pointer = QPoint()
        self.dragging = False
        self.tilt = 0.0
        self.time = 0.0
        self.last_frame = monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(IDLE_FRAME_MS)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.animate)
        self.focus = FocusSession()
        self.hourglass = HourglassRenderer()
        self.focus_morph = 0.0
        self.focus_exit_progress = 0.0
        self.focus_timer = QTimer(self)
        self.focus_timer.setInterval(250)
        self.focus_timer.timeout.connect(self.check_focus)
        self.focus_capsule = FocusCapsule(self)
        self.workday = Workday.load(self.settings)
        self.work_progress = None
        self.work_remaining = 0
        self.work_celebration = None
        self.work_animation_sample = 0.
        self.work_fireworks = WorkdayFireworks(self)
        self.work_last_checked = None
        self.work_timer = QTimer(self)
        self.work_timer.setInterval(1000)
        self.work_timer.timeout.connect(self.update_workday)
        self.work_action = QAction("启用下班日落", self, checkable=True)
        self.work_action.setChecked(self.settings.value("workday_enabled", False, type=bool))
        self.work_action.toggled.connect(self.set_workday_enabled)
        self.reminders = ReminderSchedule(self.settings)
        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(1000)
        self.reminder_timer.timeout.connect(self.show_due_notice)
        self.sync_reminder_timer()
        self.input_dialog = None
        self.work_memory_panel = None
        self.quick_panel = QuickPanel(self)
        self.hover_card = BottleHoverCard(self)
        self.quick_panel.closed.connect(self.show_due_notice)
        self.shape = "bottle"
        self.activity = None
        self.activity_count = 0
        self.activity_observed = None
        self.pinned_activity = read_pin()
        self.visible_pin = None
        self.unread_activities = {}
        self.seen_reviews = None
        self.reviewed_activities = set()
        self.activity_panel = ActivityPanel(self)
        self.keep_bottle_until = 0.
        self.fold = 1.
        self.fold_snapshot = None
        self.strip_progress = 0.
        self.compact_on_right = False
        self.position_right = None
        self.compact_face = None
        self.compact_paint_key = None
        self.ambient = AmbientOrb(self.last_frame)
        self.pearl_light = PearlLight()
        self.ambient_lit = False
        self.ambient_after_drag = 0.
        self.strip_glint = 1.
        self.reduced_motion = self.settings.value("pearl_reduced_motion", False, type=bool)
        self.motion_action = QAction("减少动态效果", self, checkable=True, checked=self.reduced_motion)
        self.motion_action.toggled.connect(self.set_reduced_motion)
        self.shape_offset = QPoint()
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(400)
        self.activity_timer.timeout.connect(self.poll_activity)
        self.orb_action = QAction("空闲时收成光珠", self, checkable=True)
        self.orb_action.setChecked(self.settings.value("compact_orb", True, type=bool))
        self.orb_action.toggled.connect(self.settings_orb)
        self.activity_scope = QActionGroup(self)
        for scope, label in (("global", "所有本机 Codex 聊天"), ("project", "仅灵动瓶项目"), ("off", "关闭状态联动")):
            action = QAction(label, self, checkable=True, checked=scope == read_scope())
            action.setData(scope)
            self.activity_scope.addAction(action)
        self.activity_scope.triggered.connect(lambda action: self.change_activity_scope(action.data()))

        self.follow_action = QAction(line_icon("follow"), "立即恢复自动跟随", self)
        self.follow_action.triggered.connect(self.follow_weather)
        self.shuffle_action = QAction(line_icon("shuffle"), "自动随机轮播", self, checkable=True)
        self.shuffle_action.setChecked(self.settings.value("shuffle_enabled", False, type=bool))
        self.shuffle_action.triggered.connect(self.set_shuffle)
        self.city_action = QAction(line_icon("city"), "设置城市…", self)
        self.city_action.triggered.connect(self.choose_city)
        self.locate_action = QAction(line_icon("locate"), "重新自动定位", self)
        self.locate_action.triggered.connect(lambda: self.change_city(None))
        self.shuffle_interval_actions = {}
        for seconds, label in SHUFFLE_PRESETS.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, value=seconds: self.set_shuffle_interval(value))
            self.shuffle_interval_actions[seconds] = action
        self.shuffle_custom_action = QAction("自定义秒数…", self)
        self.shuffle_custom_action.triggered.connect(self.choose_shuffle_interval)

        self.weather_actions = QActionGroup(self)
        self.weather_actions.setExclusive(True)
        self.scene_actions = {}
        for season, scenes in GROUPS.items():
            actions = []
            for key, scene in scenes.items():
                action = QAction(scene.name, self, checkable=True)
                action.setData(key)
                self.weather_actions.addAction(action)
                actions.append(action)
            self.scene_actions[season] = actions
        self.weather_actions.triggered.connect(lambda action: self.preview_weather(action.data()))

        self.size_actions = QActionGroup(self)
        self.size_actions.setExclusive(True)
        for scale in SCALES:
            action = QAction(f"{scale}%", self, checkable=True, checked=scale == self.bottle_scale)
            action.setData(scale)
            self.size_actions.addAction(action)
        self.size_actions.triggered.connect(lambda action: self.set_bottle_scale(action.data()))
        self.pin_action = QAction(line_icon("pin", self.pinned), "始终置顶", self, checkable=True, checked=self.pinned)
        self.pin_action.toggled.connect(self.set_pinned)
        self.quit_action = QAction(line_icon("quit"), "退出", self)
        self.quit_action.triggered.connect(self.close)

        self.appearance_actions = QActionGroup(self)
        for mode, text in (("system", "跟随系统"), ("light", "浅色毛玻璃"), ("dark", "深色毛玻璃")):
            option = QAction(text, self, checkable=True, checked=self.appearance == mode)
            option.setData(mode)
            self.appearance_actions.addAction(option)
        self.appearance_actions.triggered.connect(lambda action: self.change_appearance(action.data()))
        QApplication.styleHints().colorSchemeChanged.connect(self.refresh_appearance)
        for action, kind in ((self.follow_action, "follow"), (self.shuffle_action, "shuffle"),
                             (self.city_action, "city"), (self.locate_action, "locate"),
                             (self.pin_action, "pin"), (self.quit_action, "quit")):
            action.setProperty("pearlIcon", kind)
        self.menu = FluentMenu(self)
        self.tray_menu = FluentMenu(self)
        self.menu_labels = []
        self.shuffle_menus = []
        self.build_menu(self.menu)
        self.build_menu(self.tray_menu, tray=True)
        self.update_shuffle_interval_menu()
        self.tray = QSystemTrayIcon(self.make_icon(), self)
        self.tray.setToolTip("灵动珠 Dynamic Pearl")
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.on_tray)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            self.hide_action.setEnabled(False)
        self.setWindowIcon(self.tray.icon())
        if self.shuffle_action.isChecked():
            self.next_random_scene()
        else:
            self.set_weather(self.weather)
        self.restore_position()
        QTimer.singleShot(0, self, self.refresh_weather)

    def build_menu(self, root, tray=False):
        summary = root.status(width=220, wrap=False)
        weather = root.submenu("天气与场景", "weather")
        details = weather.status()
        weather.item("经典天气瓶", "weather", self.show_classic_weather)
        weather.addActions([self.follow_action, self.shuffle_action])
        self.shuffle_menus.append(self.make_shuffle_interval_menu(weather))
        scenes = weather.submenu("场景预览", "scenes")
        for season, actions in self.scene_actions.items():
            scenes.submenu(season, season).addActions(actions)
        weather.addSeparator()
        weather.addActions([self.city_action, self.locate_action])

        time_tools = root.submenu("时间工具", "clock")
        self.make_focus_menu(time_tools)
        self.make_reminder_menu(time_tools)
        work_status = self.make_workday_menu(time_tools)
        self.menu_labels.append((summary, details, work_status))
        root.item("工作回顾", "stack", self.toggle_work_memory)

        desktop = root.submenu("桌面设置", "size")
        desktop.submenu("挂件大小", "size").addActions(self.size_actions.actions())
        desktop.addAction(self.pin_action)
        desktop.addAction(self.orb_action)
        desktop.addAction(self.motion_action)
        desktop.submenu("外观", "scenes").addActions(self.appearance_actions.actions())
        desktop.submenu("Codex 活动范围", "clock").addActions(self.activity_scope.actions())
        desktop.addSeparator()
        desktop.addAction(self.quit_action)

        root.addSeparator()
        if tray:
            root.item("显示灵动珠", "show", self.restore)
        else:
            self.hide_action = root.item("收进托盘", "tray", self.hide)

    @staticmethod
    def make_icon():
        pearl = pearl_pixmap()
        if not pearl.isNull():
            return QIcon(pearl.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        renderer = BottleRenderer()
        renderer.prepare(1.5)
        return QIcon(raster(1.5, lambda p: renderer.paint(p, "sun", 0)))

    def resize_bottle(self):
        self.setFixedSize(*self.bottle_size())

    def bottle_size(self):
        return tuple(round(size * self.bottle_scale / 100) for size in SIZE)

    def set_bottle_scale(self, scale):
        position = self.pos() - self.shape_offset
        old_w, old_h = self.bottle_size()
        self.bottle_scale = scale
        self.settings.setValue("scale", scale)
        width, height = self.bottle_size()
        position += QPoint(old_w - width if self.compact_on_right else 0, old_h - height)
        self.shape_offset = self.pos() - position
        self.update_shape(monotonic(), 0., False)
        self.save_position()
        if self.focus_capsule.isVisible():
            self.focus_capsule.reposition(self)
        if self.quick_panel.isVisible():
            self.quick_panel.reposition()

    def scene_opacity(self):
        progress = min(1.0, (self.time - self.transition_start) / TRANSITION)
        return 1.0 - progress * progress * (3 - 2 * progress)

    def restore_position(self):
        saved = self.settings.value("position", type=QPoint) if self.settings.contains("position") else None
        self.position_right = None
        self.shape_offset = QPoint()
        if saved is not None:
            if self.settings.contains("position_right"):
                self.position_right = self.settings.value("position_right", type=bool)
                full_w, full_h = self.bottle_size()
                anchor = saved + QPoint(full_w - 1 if self.position_right else 0, full_h - 1)
            else:
                anchor = saved + QPoint(self.width() // 2, self.height() // 2)
            screen = QApplication.screenAt(anchor)
            if screen is not None:
                point = self.clamp_position(saved, screen)
                self.shape_offset = point - saved
                self.move(point)
                return
        self.position_right = None
        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 19, area.bottom() - self.height() - 12)

    def save_position(self):
        self.settings.setValue("position", self.pos() - self.shape_offset)
        on_right = self.position_right if self.position_right is not None else self.compact_on_right
        self.settings.setValue("position_right", on_right)

    def clamp_position(self, position, screen):
        area = screen.availableGeometry()
        return QPoint(
            max(area.left(), min(position.x(), area.right() + 1 - self.width())),
            max(area.top(), min(position.y(), area.bottom() + 1 - self.height())),
        )

    def change_appearance(self, mode):
        self.appearance = mode
        self.settings.setValue("pearl_appearance", mode)
        self.refresh_appearance()

    def refresh_appearance(self, *_):
        apply_appearance(self.appearance)
        self.compact_paint_key = None
        self.update()

    def settings_orb(self, enabled):
        self.settings.setValue("compact_orb", enabled)
        if not enabled:
            self.activity_panel.hide()

    def set_reduced_motion(self, enabled):
        self.reduced_motion = enabled
        self.settings.setValue("pearl_reduced_motion", enabled)
        self.compact_paint_key = None

    def change_activity_scope(self, scope):
        try:
            if scope == "global":
                install_global_hooks()
            set_scope(scope)
        except (OSError, ValueError) as error:
            for action in self.activity_scope.actions():
                action.setChecked(action.data() == read_scope())
            self.show_glass_notice("Codex 活动范围", f"无法保存活动范围：{error}")
            return
        self.activity_observed = None
        self.ambient.codex = None
        self.poll_activity()

    def poll_activity(self):
        scope = read_scope()
        records = read_records()
        wall = time()
        reviews = {item["id"]: item for item in records.values()
                   if item["state"] in REVIEW_STATES and wall - item["updated"] < NOTICE_SECONDS
                   and self.can_open_activity(item)}
        if self.seen_reviews is not None:
            self.unread_activities.update((key, value) for key, value in reviews.items()
                                          if key not in self.seen_reviews and key not in self.reviewed_activities
                                          and self.in_activity_scope(value, scope))
            self.unread_activities = dict(list(self.unread_activities.items())[-40:])
            self.seen_reviews.intersection_update(records)
        else:
            self.seen_reviews = set()
        self.seen_reviews.update(reviews)
        if records:
            self.reviewed_activities.intersection_update(records)
        self.visible_pin = self.refresh_activity_pin(records, scope, wall)
        self.review_continued_threads(records, reviews, scope)
        activities = [item for item in read_activities(wall, records=records, scope=scope)
                      if item["id"] not in self.reviewed_activities]
        self.activity = activities[0] if activities else None
        self.activity_count = sum(item["state"] == "running" for item in activities)
        self.observe_activity_events(records, activities, wall, scope)
        if scope == "off" and self.activity_panel.records and self.activity_panel.isVisible():
            self.activity_panel.hide()
        unread = {key: item for key, item in self.unread_activities.items()
                  if self.in_activity_scope(item, scope)}
        rows = {item["id"]: item for item in activities}
        rows.update((key, item) for key, item in unread.items() if key not in rows)
        if self.visible_pin:
            key = self.visible_pin["id"]
            rows = {key: self.visible_pin, **{other: item for other, item in rows.items() if other != key}}
        self.activity_panel.set_records([
            {**item, "pinned": item is self.visible_pin,
             "unread": key in unread or (item is self.visible_pin and item["state"] in REVIEW_STATES)}
            for key, item in rows.items()
        ])

    def observe_activity_events(self, records, activities, wall, scope):
        if not records and self.activity_observed is not None:
            # An empty bridge snapshot can also be a transient read failure.
            return
        observed = {key: item["state"] for key, item in records.items() if self.in_activity_scope(item, scope)}
        observed.update((item["id"], "unknown") for item in activities if item["state"] == "unknown")
        if self.activity_observed is not None and self.isVisible():
            changes = {}
            for key, state in observed.items():
                if self.activity_observed.get(key) == state or key in self.reviewed_activities:
                    continue
                if state == "unknown":
                    changes[key] = state
                    continue
                if wall - records[key]["updated"] >= NOTICE_SECONDS:
                    continue
                if state == "running" and wall - records[key]["started"] < NOTICE_SECONDS:
                    changes[key] = "start"
                elif state in REVIEW_STATES:
                    changes[key] = state
            self.ambient.queue_codex(monotonic(), changes)
        self.activity_observed = observed

    def review_continued_threads(self, records, reviews, scope):
        pending = {**reviews, **self.unread_activities}
        if self.visible_pin and self.visible_pin["state"] in REVIEW_STATES:
            pending[self.visible_pin["id"]] = self.visible_pin
        if not pending or scope == "off":
            return
        # A prompt submitted after the result is evidence scoped to that exact chat.
        latest_prompt = {}
        for item in records.values():
            if item["source"] == "desktop" and self.can_open_activity(item) and self.in_activity_scope(item, scope):
                thread = item["thread"]
                latest_prompt[thread] = max(latest_prompt.get(thread, 0), item["started"])
        for item in pending.values():
            next_started = latest_prompt.get(item["thread"], 0)
            if (self.in_activity_scope(item, scope)
                    and next_started > item["started"] and next_started >= item["updated"]):
                self.record_activity_review(item)

    @staticmethod
    def in_activity_scope(record, scope):
        return scope == "global" or (scope == "project" and record.get("in_project", True))

    @staticmethod
    def can_open_activity(record):
        thread = record and record.get("thread")
        return isinstance(thread, str) and bool(THREAD_ID.fullmatch(thread))

    def refresh_activity_pin(self, records, scope, wall):
        record = self.pinned_activity
        if not record or not self.in_activity_scope(record, scope):
            return None
        current = records.get(record["id"], record)
        if current["state"] in REVIEW_STATES and current["state"] != record["state"]:
            self.store_activity_pin(current)
        if current["state"] == "running" and wall - current["updated"] > activity_expiry(current):
            return {**current, "state": "unknown"}
        return current

    def store_activity_pin(self, record):
        try:
            save_pin(record)
        except OSError:
            return False
        self.pinned_activity = record
        return True

    def toggle_activity_pin(self, record):
        if not self.can_open_activity(record):
            return
        selected = None if self.pinned_activity and self.pinned_activity["id"] == record["id"] else record
        if self.store_activity_pin(selected):
            self.poll_activity()
        else:
            self.activity_panel.hide()
            self.show_glass_notice("Codex 活动", "无法保存桌角活动。")

    def record_activity_review(self, record):
        if record["state"] not in REVIEW_STATES:
            return False
        key = record["id"]
        if self.pinned_activity and self.pinned_activity["id"] == key:
            if not self.store_activity_pin(None):
                return False
            self.visible_pin = None
        self.reviewed_activities.add(key)
        self.unread_activities.pop(key, None)
        return True

    def mark_activity_reviewed(self, record):
        if self.record_activity_review(record):
            self.poll_activity()

    def open_activity(self, record):
        if not self.can_open_activity(record):
            return
        if not open_codex_thread(record["thread"]):
            return
        self.record_activity_review(record)
        self.activity_panel.hide()
        self.poll_activity()

    def toggle_activity_panel(self):
        if self.close_work_memory():
            return
        if self.activity_panel.isVisible() and not self.activity_panel.closing:
            self.activity_panel.dismiss()
            return
        self.hover_card.reset()
        unread = self.has_unread_activity()
        mode = ("focus" if self.focus.phase != "idle" else
                "activities" if self.activity or self.visible_pin or unread or self.shape == "activity" else "quick")
        self.activity_panel.reveal(mode, unread_first=unread and not self.activity_count)

    def work_memory_visible(self):
        return self.work_memory_panel is not None and self.work_memory_panel.isVisible()

    def close_work_memory(self):
        if self.work_memory_visible():
            self.work_memory_panel.hide()
            return True
        return False

    def toggle_work_memory(self):
        if self.close_work_memory() or self.input_dialog is not None or self.focus_capsule.isVisible():
            return
        if QApplication.activeModalWidget() is not None:
            return
        if not self.isVisible():
            self.restore()
        self.activity_panel.hide()
        self.quick_panel.hide()
        self.hover_card.reset()
        self.work_fireworks.hide()
        if self.work_memory_panel is None:
            self.work_memory_panel = WorkMemoryPanel(self)
        self.work_memory_panel.reveal()

    def activity_panel_face(self):
        if self.activity_panel.mode == "focus":
            return self.focus_face() if self.focus.phase != "idle" else None
        if self.visible_pin:
            return self.pin_face()
        return self.activity_summary()

    def activity_summary(self):
        pending = [item for item in self.activity_panel.records if item["unread"]]
        if not self.activity_count and not pending:
            return (CapsuleFace("状态未确认", "", symbol="notice", tone="muted")
                    if self.activity and self.activity["state"] == "unknown" else None)
        if self.activity_count:
            detail = f"{len(pending)} 项待查看" if pending else ""
            if not detail and self.activity_count == 1:
                minutes, seconds = divmod(max(0, int(time() - self.activity["started"])), 60)
                detail = f"{minutes:02d}:{seconds:02d}"
            return CapsuleFace(f"{self.activity_count} 项处理中", detail,
                               symbol="stack" if self.activity_count > 1 else "running")
        error = any(item["state"] != "ended" for item in pending)
        return CapsuleFace(f"{len(pending)} 项待查看", "", symbol="notice" if error else "check",
                           tone="error" if error else "success")

    def feedback_face(self, feedback):
        if feedback.kind.startswith("session"):
            return self.focus_face() if self.focus.phase != "idle" else None
        if feedback.kind in {"failed", "interrupted"}:
            count = sum(kind in {"failed", "interrupted"} for kind in feedback.events.values())
            abnormal = {kind for kind in feedback.events.values() if kind in {"failed", "interrupted"}}
            reason = "已中断" if abnormal == {"interrupted"} else "运行失败" if abnormal == {"failed"} else "中断或失败"
            label = reason if count == 1 else f"{count} 项{reason}"
            return CapsuleFace(label, "", symbol="notice", tone="error")
        if feedback.kind == "unknown":
            return CapsuleFace("状态未确认", "", symbol="notice", tone="muted")
        if feedback.kind == "ended":
            count = sum(kind == "ended" for kind in feedback.events.values())
            label = f"{count} 项已结束" if self.activity_count else "本轮已结束"
            detail = (f"{self.activity_count} 项处理中" if self.activity_count else
                      f"{count} 项已结束" if count > 1 else "")
            return CapsuleFace(label, detail, symbol="check", tone="success")
        return self.activity_summary()

    def show_classic_weather(self):
        if not self.isVisible():
            self.restore()
        self.peek_bottle()

    def compact_pearl_contains(self, point):
        if self.fold > 0. or self.strip_progress < .65:
            return False
        x = self.mapFromGlobal(point).x()
        pearl_width = round(ORB_SIZE * self.bottle_scale / 100)
        return x >= self.width() - pearl_width if self.compact_on_right else x < pearl_width

    def focus_face(self):
        phase = self.focus.phase
        if phase == "focus_done":
            return CapsuleFace("专注完成", f"休息 {DEFAULT_BREAK_MINUTES} 分钟", symbol="check", tone="success")
        if phase == "break_done":
            return CapsuleFace("休息完成", "结束", symbol="check", tone="success")
        label = "专注" if phase == "focus" else "休息"
        if self.focus.deadline is None:
            label += "暂停"
        return CapsuleFace(label, self.focus.clock_text, self.focus.progress,
                           "pause" if self.focus.deadline is None else "play",
                           "ice" if phase == "break" else "warm")

    def pin_face(self):
        record = self.visible_pin
        label = display_name(record.get("project")) or "Codex"
        detail = {"running": "处理中", "ended": "待查看", "failed": "失败待查看",
                  "interrupted": "中断待查看", "unknown": "状态未确认"}[record["state"]]
        return CapsuleFace(label, detail, symbol="pin",
                           tone="error" if record["state"] in {"failed", "interrupted"}
                           else "success" if record["state"] == "ended" else "warm")

    def peek_bottle(self):
        self.activity_panel.hide()
        now = monotonic()
        self.keep_bottle_until = now + 5
        if self.fold < 1. and self.timer.isActive() and self.timer.interval() != MORPH_FRAME_MS:
            self.last_frame = now
            self.timer.setInterval(MORPH_FRAME_MS)

    def expand_now(self):
        position = self.pos() - self.shape_offset
        self.shape, self.fold = "bottle", 1.
        self.fold_snapshot = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        screen = self.screen()
        self.resize_bottle()
        point = self.clamp_position(position, screen)
        self.shape_offset = point - position
        self.move(point)

    def update_shape(self, now, elapsed, hovering):
        if hovering and self.shape == "bottle" and self.keep_bottle_until > now:
            self.keep_bottle_until = max(self.keep_bottle_until, now + .55)
        classic = not self.orb_action.isChecked()
        focus_short = not classic and self.focus.phase != "idle"
        wants_bottle = (classic or self.focus_morph > 0
                        or self.quick_panel.isVisible()
                        or (self.focus_capsule.isVisible() and self.focus_capsule.reminder_id is None)
                        or self.input_dialog is not None
                        or now < self.keep_bottle_until)
        if self.interaction_busy():
            return
        if wants_bottle:
            self.activity_panel.hide()
        session = self.focus.phase
        panel_open = self.activity_panel.isVisible() or self.work_memory_visible()
        blocked = (wants_bottle or panel_open or self.focus_capsule.isVisible() or self.work_fireworks.isVisible()
                   or now < self.ambient_after_drag)
        self.ambient_lit = self.ambient.update_hover(now, hovering, not blocked and self.fold == 0.)
        feedback, charge = self.ambient.feedback(now, not blocked and self.visible_pin is None, self.reduced_motion)
        if wants_bottle:
            face = None
        elif self.visible_pin:
            face = self.pin_face()
        elif feedback:
            face = self.feedback_face(feedback)
        elif self.ambient.hover_open and self.visible_pin is None:
            face = self.focus_face() if session != "idle" else self.activity_summary()
        else:
            face = None
        shape = ("bottle" if wants_bottle else "orb" if face is None else
                 "focus" if self.visible_pin is None and session != "idle"
                 and (feedback is None or feedback.kind.startswith("session")) else "activity")
        if self.shape != shape:
            self.shape = shape
            self.update_shape_cursor()
        mode = ("rest" if session.startswith("break") else "focus" if session.startswith("focus")
                else "active" if self.activity_count else "idle")
        paused = self.focus.running and self.focus.deadline is None
        self.pearl_light = PearlLight(
            mode=mode, motion=None if self.reduced_motion or paused or session.endswith("_done") else now,
            reflection=self.ambient.reflection(now) if mode == "idle" and not self.reduced_motion else 0.,
            charge=charge, direction=-1 if self.compact_on_right else 1,
            dense=mode == "active" and self.activity_count > 1,
            paused=paused, completed=session.endswith("_done"),
        )
        self.strip_glint = (
            min(1., max(0., (now - feedback.shown - .21) / GLINT_SECONDS))
            if feedback and feedback.kind in {"ended", "session_done"} and not self.reduced_motion else 1.
        )
        goal = 1. if wants_bottle else 0.
        step = elapsed / (BOTTLE_OPEN_SECONDS if wants_bottle else BOTTLE_CLOSE_SECONDS)
        self.fold = min(goal, self.fold + step) if self.fold < goal else max(goal, self.fold - step)
        if self.reduced_motion and elapsed:
            self.fold = goal
        if face:
            self.strip_progress = (1. if self.reduced_motion and elapsed else
                                   min(1., self.strip_progress + min(.040, elapsed) / STRIP_OPEN))
            self.compact_face = face
        else:
            self.strip_progress = (0. if self.reduced_motion and elapsed else
                                   max(0., self.strip_progress - min(.040, elapsed) / STRIP_CLOSE))
            if self.strip_progress == 0.:
                self.compact_face = None
        position = self.pos() - self.shape_offset
        area = self.screen().availableGeometry()
        full_w, full_h = self.bottle_size()
        width, height = self.morph_size()
        if 0. < self.fold < 1.:
            # Resize the native window only at the ends of the bottle transition.
            width, height = max(full_w, round(CAPSULE_WIDTH * self.bottle_scale / 100)), full_h
        else:
            self.fold_snapshot = None
            if self.fold == 0. and 0. < self.strip_progress < 1.:
                width = round(CAPSULE_WIDTH * self.bottle_scale / 100)
        self.compact_on_right = (self.position_right if self.position_right is not None
                                 else position.x() + full_w / 2 > area.center().x())
        x = position.x() + (full_w - width if self.compact_on_right else 0)
        x = max(area.left(), min(x, area.right() - width + 1))
        y = max(area.top(), min(position.y() + full_h - height, area.bottom() - height + 1))
        point = QPoint(x, y)
        if (self.width(), self.height()) != (width, height):
            self.setMinimumSize(1, 1)
            self.setMaximumSize(MAX_WIDGET_SIZE, MAX_WIDGET_SIZE)
            self.setGeometry(point.x(), point.y(), width, height)
        elif self.pos() != point:
            self.move(point)
        self.shape_offset = point - position
        if self.activity_panel.isVisible():
            self.activity_panel.place()
        if self.work_memory_visible():
            self.work_memory_panel.place()

    def morph_size(self):
        compact_w, compact_h = compact_geometry(self.strip_progress, self.bottle_scale / 100)
        full_w, full_h = self.bottle_size()
        amount = smooth(self.fold)
        return (round(compact_w + (full_w - compact_w) * amount),
                round(compact_h + (full_h - compact_h) * amount))

    def visual_geometry(self):
        width, height = self.morph_size()
        x = self.x() + (self.width() - width if self.compact_on_right else 0)
        return QRect(x, self.y() + self.height() - height, width, height)

    def set_weather(self, weather):
        if weather != self.weather:
            self.capture_scene_transition()
            self.weather = weather
        for action in self.weather_actions.actions():
            action.setChecked(action.data() == weather)
        self.update_weather_status()
        self.update()

    def capture_scene_transition(self):
        if self.isVisible() and self.focus_morph < 1:
            self.renderer.prepare(self.devicePixelRatioF() * self.bottle_scale / 100)
            self.previous_scene = self.renderer.snapshot(
                self.weather, self.time, self.tilt, self.previous_scene, self.scene_opacity(),
            )
            self.transition_start = self.time
        else:
            self.previous_scene = None

    def update_weather_status(self):
        location = self.location.name if self.location else "自动定位"
        status = f"{location} · {self.weather_status}"
        if self.manual_timer.isActive():
            status = f"手动预览 · {WEATHER[self.weather].name}\n{status}"
        elif self.shuffle_action.isChecked():
            status = f"随机轮播 · {WEATHER[self.weather].name}\n本地天气 · {status}"
        weather_details = status
        if self.work_progress is not None:
            status = f"{self.workday_status()}\n{status}"
        if self.current_weather:
            data = self.current_weather
            summary = f"{location} · {data.condition} {data.temperature:.1f} °C"
        else:
            summary = f"{location} · {self.weather_status}"
        if self.manual_timer.isActive():
            mode = f"手动预览 · {WEATHER[self.weather].name}"
        elif self.shuffle_action.isChecked():
            mode = f"随机轮播 · {WEATHER[self.weather].name}"
        else:
            mode = "自动跟随"
        if self.focus.running:
            phase = "专注" if self.focus.phase == "focus" else "休息"
            mode = f"{phase} · {self.focus.clock_text}" + (" · 已暂停" if self.focus.deadline is None else "")
        elif self.focus.phase in {"focus_done", "break_done"}:
            mode = "专注完成" if self.focus.phase == "focus_done" else "休息结束"
        for top, details, work in self.menu_labels:
            top.setText(top.fontMetrics().elidedText(summary, Qt.TextElideMode.ElideRight, top.width() - 18)
                        + "\n" + mode)
            details.setText(weather_details)
            work.setText(self.workday_status())
        self.tray.setToolTip(f"灵动珠 Dynamic Pearl\n{status}")
        if self.hover_card.isVisible():
            self.hover_card.set_content(self.hover_content())
        if self.quick_panel.isVisible():
            self.quick_panel.refresh()

    def hover_content(self):
        if self.shape == "activity" and self.visible_pin:
            face = self.pin_face()
            return HoverContent("已挂到桌角", face.label, face.detail, "点击珠光查看全部活动", wrap_primary=True)
        if self.focus.running:
            phase = "专注" if self.focus.phase == "focus" else "休息"
            paused = self.focus.deadline is None
            return HoverContent(f"{phase} · {'已暂停' if paused else '进行中'}", self.focus.clock_text,
                                hint="轻点继续" if paused else "轻点暂停")
        if self.manual_timer.isActive():
            heading = f"手动预览 · {WEATHER[self.weather].name}"
        elif self.shuffle_action.isChecked():
            heading = f"随机轮播 · {WEATHER[self.weather].name}"
        else:
            heading = "本地天气"
        location = self.location.name if self.location else "自动定位"
        weather = self.current_weather
        if weather:
            primary = f"{weather.condition} {weather.temperature:.1f} °C · {location}"
            detail = f"更新于 {weather.time.rsplit('T', 1)[-1]}"
        else:
            primary, detail = location, self.weather_status
        if self.work_progress is not None:
            detail = self.workday_status()
        return HoverContent(heading, primary, detail, "瓶盖打开快捷舱 · 瓶身换景")

    def workday_status(self):
        if not self.work_action.isChecked():
            return "下班进度未启用"
        if self.work_celebration is not None:
            return "下班啦"
        if self.work_progress is None:
            return f"{self.workday.end_label()} 下班 · 当前不在工作时段"
        hours, minutes = divmod(math.ceil(self.work_remaining / 60), 60)
        remaining = f"{hours} 小时 {minutes} 分钟" if hours else f"{minutes} 分钟"
        return f"{self.workday.end_label()} 下班 · 还有 {remaining}"

    def make_workday_menu(self, parent):
        menu = parent.submenu("下班日落", "clock")
        status = menu.status()
        menu.addAction(self.work_action)
        menu.item("设置上下班时间…", "clock", self.choose_workday)
        return status

    def choose_workday(self):
        if self.input_dialog is None:
            dialog = WorkdayDialog(self, self.workday)
            self.open_input_dialog(dialog, dialog.parts[0].editor, self.save_workday)

    def save_workday(self, schedule):
        self.workday = schedule
        self.workday.save(self.settings)
        self.work_last_checked = None
        self.work_action.setChecked(True)
        self.update_workday()
        self.settings.sync()

    def set_workday_enabled(self, enabled):
        self.settings.setValue("workday_enabled", enabled)
        self.work_last_checked = None
        if enabled and self.isVisible():
            self.work_timer.start()
        else:
            self.work_timer.stop()
        self.update_workday()

    def update_workday(self, now=None):
        now = now if now is not None else QDateTime.currentDateTime()
        stamp = now.toMSecsSinceEpoch() / 1000
        window = self.workday.window(now) if self.work_action.isChecked() and self.isVisible() else None
        progress = celebration = None
        remaining = 0
        if window:
            start, end = window
            if start <= stamp < end:
                progress = (stamp - start) / (end - start)
                remaining = end - stamp
            elif end <= stamp < end + SUNSET_CELEBRATION_SECONDS:
                uninterrupted = self.can_play_work_fireworks() and self.reminders.next_due() is None
                crossing = (self.work_last_checked is not None and end - 3 <= self.work_last_checked < end
                            and stamp < end + 3)
                if uninterrupted and (crossing or self.work_celebration is not None):
                    progress, celebration = 1., stamp - end
        self.work_last_checked = stamp if window else None
        self.work_progress = progress
        self.work_remaining = remaining
        self.work_celebration = celebration
        self.work_animation_sample = monotonic()
        if celebration is None:
            self.work_fireworks.hide()
        self.update_weather_status()
        self.update()

    def can_shuffle(self):
        return (self.isVisible() and self.shuffle_action.isChecked()
                and self.focus.phase == "idle")

    def make_focus_menu(self, parent):
        menu = parent.submenu("专注沙漏", "clock")
        menu.addAction("专注 25 分钟", lambda: self.start_focus(25 * 60))
        menu.addAction("专注 45 分钟", lambda: self.start_focus(45 * 60))
        menu.addAction("自定义时长…", self.choose_focus_duration)
        rest = menu.submenu("立即休息", "clock")
        for minutes in BREAK_PRESETS:
            rest.addAction(f"休息 {minutes} 分钟", lambda checked=False, value=minutes: self.start_break(value * 60))
        rest.addAction("自定义休息…", self.choose_break_duration)
        menu.addSeparator()
        pause = menu.addAction("暂停", self.toggle_focus_pause)
        end = menu.addAction("结束计时", self.end_focus)
        menu.aboutToShow.connect(lambda: self.update_focus_menu(pause, end))

    def update_focus_menu(self, pause, end):
        pause.setEnabled(self.focus.running)
        pause.setText("继续" if self.focus.running and self.focus.deadline is None else "暂停")
        end.setEnabled(self.focus.phase != "idle")

    def choose_focus_duration(self):
        self.choose_session_duration(self.start_focus, "专注", 25, (15, 25, 45, 60))

    def choose_break_duration(self):
        self.choose_session_duration(self.start_break, "休息", DEFAULT_BREAK_MINUTES, BREAK_PRESETS)

    def choose_session_duration(self, start, label, default_minutes, presets):
        self.open_number_dialog(
            start, f"自定义{label}", f"设置本次{label}时长", f"开始{label}",
            NumberSpec(1, SESSION_MAX_SECONDS // 60, "分钟", multiplier=60), default_minutes,
            lambda value, unit, factor: f"{label}时长为 {value} {unit}（{value * factor} 秒）"
            if factor != 1 else f"{label}时长为 {value} {unit}",
            alternate=NumberSpec(1, SESSION_MAX_SECONDS, "秒"), presets=presets,
        )

    def open_number_dialog(self, apply, *args, **options):
        if self.input_dialog is not None:
            return
        dialog = GlassNumberDialog(self, *args, **options)
        self.open_input_dialog(dialog, dialog.number.editor, apply, expand_bottle=not self.orb_action.isChecked())

    def open_input_dialog(self, dialog, editor, apply, *, expand_bottle=True):
        self.close_work_memory()
        if expand_bottle:
            self.expand_now()
            self.keep_bottle_until = monotonic() + .55
        self.hover_card.reset()
        self.quick_panel.hide()
        self.focus_capsule.hide()
        self.work_fireworks.hide()
        self.input_dialog = dialog

        def finished(result):
            self.input_dialog = None
            if result:
                apply(dialog.result_value)
            dialog.deleteLater()
            QTimer.singleShot(0, self, self.show_due_notice)

        dialog.finished.connect(finished)
        dialog.open_near_bottle(editor)

    def make_reminder_menu(self, parent):
        menu = parent.submenu("本地提醒", "clock")
        menu.item("添加提醒…", "clock", self.choose_reminder)
        pending = menu.submenu("待处理提醒", "clock")
        pending.aboutToShow.connect(lambda: self.populate_reminders(pending))

    def populate_reminders(self, menu):
        for action in menu.actions():
            if action.menu() is not None:
                action.menu().deleteLater()
        menu.clear()
        if not self.reminders.items:
            menu.addAction("暂无提醒").setEnabled(False)
        for item in self.reminders.ordered():
            cycle = f" · {item.interval_label()}" if item.interval_minutes else ""
            label = f"{item.time_label()}{cycle} · {item.text}".replace("&", "&&")
            submenu = menu.submenu(label, "clock")
            remove_label = "停止循环并删除" if item.interval_minutes else "删除这条提醒"
            submenu.item(remove_label, "quit", lambda checked=False, key=item.id: self.remove_reminder(key))

    def choose_reminder(self):
        if self.input_dialog is not None:
            return
        dialog = ReminderDialog(self)
        self.open_input_dialog(dialog, dialog.editor, self.add_reminder, expand_bottle=False)

    def add_reminder(self, result):
        self.reminders.add(*result)
        self.sync_reminder_timer()

    def sync_reminder_timer(self):
        if self.reminders.items:
            if not self.reminder_timer.isActive():
                self.reminder_timer.start()
        else:
            self.reminder_timer.stop()

    def remove_reminder(self, reminder_id):
        self.reminders.remove(reminder_id)
        self.finish_reminder_notice(reminder_id)

    def finish_reminder_notice(self, reminder_id):
        if self.focus_capsule.reminder_id == reminder_id:
            self.focus_capsule.retract()
        self.sync_reminder_timer()

    def resolve_reminder(self, snooze=False):
        reminder_id = self.focus_capsule.reminder_id
        if reminder_id is not None:
            self.reminders.resolve(reminder_id, snooze)
            self.finish_reminder_notice(reminder_id)

    def interaction_busy(self):
        return (self.press_position is not None or self.input_dialog is not None
                or QApplication.activePopupWidget() is not None or QApplication.activeModalWidget() is not None)

    def can_play_work_fireworks(self):
        return (self.focus.phase == "idle" and not self.interaction_busy()
                and not self.quick_panel.isVisible() and not self.focus_capsule.isVisible()
                and not self.activity_panel.isVisible() and not self.work_memory_visible())

    def show_due_notice(self):
        if self.focus.check_deadline():
            self.focus_timer.stop()
            self.close_work_memory()
            if self.orb_action.isChecked() and self.isVisible():
                self.ambient.queue_session(monotonic(), done=True)
                if self.activity_panel.isVisible():
                    self.activity_panel.refresh()
        if (
            not self.isVisible() or self.interaction_busy()
            or self.quick_panel.pending_action is not None
            or self.focus_capsule.isVisible()
        ):
            return
        compact_focus = self.orb_action.isChecked() and self.focus.phase != "idle"
        completed = not compact_focus and self.focus.phase in {"focus_done", "break_done"}
        reminder = None if completed else self.reminders.next_due()
        if completed or reminder is not None:
            self.close_work_memory()
            self.activity_panel.hide()
            self.hover_card.reset()
            self.work_fireworks.hide()
            if self.quick_panel.isVisible():
                self.quick_panel.dismiss()
                return
        if completed:
            self.expand_now()
            self.focus_capsule.open_for(self, self.focus.phase)
        elif reminder is not None:
            if not self.orb_action.isChecked():
                self.expand_now()
            self.focus_capsule.open_reminder(self, reminder)

    def start_focus(self, seconds):
        self.start_session("focus", seconds)
        if not self.isVisible():
            self.restore()

    def start_break(self, seconds=DEFAULT_BREAK_MINUTES * 60):
        self.start_session("break", seconds)
        if not self.isVisible():
            self.restore()

    def start_session(self, phase, seconds):
        self.keep_bottle_until = 0.
        if not self.orb_action.isChecked():
            self.expand_now()
        self.hover_card.reset()
        self.quick_panel.hide()
        if self.focus_capsule.reminder_id is None:
            self.focus_capsule.retract()
        self.shuffle_timer.stop()
        self.focus.start(phase, seconds)
        if self.orb_action.isChecked():
            self.ambient.queue_session(monotonic())
        self.focus_timer.start()
        self.update_weather_status()

    def toggle_focus_pause(self):
        self.check_focus()
        if self.focus.running:
            self.focus.toggle_pause()
            if self.focus.deadline is None:
                self.focus_timer.stop()
            else:
                self.focus_timer.start()
            self.update_weather_status()

    def check_focus(self):
        self.show_due_notice()
        if self.isVisible():
            self.update_weather_status()

    def end_focus(self):
        self.focus_exit_progress = self.focus.progress
        self.focus.clear()
        self.ambient.session = None
        self.focus_timer.stop()
        if self.focus_capsule.reminder_id is None:
            self.focus_capsule.retract()
        if self.can_shuffle():
            self.shuffle_timer.start()
        self.update_weather_status()

    def preview_weather(self, weather):
        if self.orb_action.isChecked() and (self.fold < 1. or not self.isVisible()):
            self.show_classic_weather()
        self.stop_shuffle()
        self.manual_timer.start(MANUAL_DURATION_MS)
        self.update_workday()
        self.set_weather(weather)

    def make_shuffle_interval_menu(self, parent):
        menu = parent.submenu("轮播间隔", "clock")
        menu.addActions(list(self.shuffle_interval_actions.values()))
        menu.addSeparator()
        menu.addAction(self.shuffle_custom_action)
        return menu

    def update_shuffle_interval_menu(self):
        for seconds, action in self.shuffle_interval_actions.items():
            action.setChecked(seconds == self.shuffle_seconds)
        label = SHUFFLE_PRESETS.get(self.shuffle_seconds, f"{self.shuffle_seconds} 秒")
        title = f"轮播间隔 · {label}"
        for menu in self.shuffle_menus:
            menu.setTitle(title)

    def set_shuffle_interval(self, seconds):
        self.shuffle_seconds = seconds
        # Qt restarts an active timer when its interval changes and leaves a stopped timer idle.
        if self.shuffle_timer.interval() != seconds * 1000:
            self.shuffle_timer.setInterval(seconds * 1000)
        self.settings.setValue("shuffle_interval_seconds", seconds)
        self.update_shuffle_interval_menu()

    def choose_shuffle_interval(self):
        self.open_number_dialog(
            self.set_shuffle_interval, "设置轮播间隔", "每隔多少秒切换场景", "确定",
            NumberSpec(1, SHUFFLE_MAX_SECONDS, "秒"), self.shuffle_seconds,
            lambda value, unit, factor: f"每 {value} 秒自动切换一次天气场景",
        )

    def set_shuffle(self, enabled):
        if not enabled:
            self.follow_weather()
            return
        self.settings.setValue("shuffle_enabled", True)
        self.manual_timer.stop()
        self.next_random_scene()

    def stop_shuffle(self):
        self.shuffle_action.setChecked(False)
        self.settings.setValue("shuffle_enabled", False)
        self.shuffle_timer.stop()
        self.shuffle_scenes.clear()

    def next_random_scene(self):
        if not self.shuffle_scenes:
            self.shuffle_scenes = list(WEATHER)
            shuffle(self.shuffle_scenes)
            if self.shuffle_scenes[-1] == self.weather:
                self.shuffle_scenes[0], self.shuffle_scenes[-1] = self.shuffle_scenes[-1], self.shuffle_scenes[0]
        self.set_weather(self.shuffle_scenes.pop())
        if self.can_shuffle():
            self.shuffle_timer.start()

    def follow_weather(self):
        self.stop_shuffle()
        self.manual_timer.stop()
        self.update_workday()
        if self.current_weather:
            self.set_weather(self.current_weather.scene)
        else:
            self.update_weather_status()
        self.refresh_weather()

    def refresh_weather(self):
        if self.fetching:
            return
        self.refresh_timer.stop()
        self.fetching = True
        generation = self.location_generation

        def received(weather):
            if generation != self.location_generation:
                return
            self.fetching = False
            if weather is None:
                self.weather_status = "更新失败，显示上次天气，30 秒后重试" if self.current_weather else "天气暂不可用，30 秒后重试"
                self.update_weather_status()
                self.refresh_timer.start(WEATHER_RETRY_MS)
                return
            self.current_weather = weather
            self.refresh_timer.start(WEATHER_REFRESH_MS)
            self.weather_status = f"{weather.condition} {weather.temperature:.1f} °C · {weather.time.replace('T', ' ')}"
            if self.manual_timer.isActive() or self.shuffle_action.isChecked():
                self.update_weather_status()
            else:
                self.set_weather(weather.scene)

        def located(location):
            if generation != self.location_generation:
                return
            if location is None:
                self.fetching = False
                self.weather_status = "定位失败，30 秒后重试，可右键设置城市"
                self.update_weather_status()
                self.refresh_timer.start(WEATHER_RETRY_MS)
                return
            self.location = location
            self.update_weather_status()
            self.service.current(location, received)

        if self.location:
            self.service.current(self.location, received)
        else:
            self.service.locate(located)

    def change_city(self, location):
        self.location_generation += 1
        self.fetching = False
        self.location = location
        self.current_weather = None
        self.weather_status = "正在获取本地天气"
        if location:
            self.settings.setValue("weather_city", asdict(location))
        else:
            self.settings.remove("weather_city")
        self.update_weather_status()
        self.refresh_weather()

    def choose_city(self):
        if self.input_dialog is not None:
            return
        if not self.isVisible():
            self.restore()
        dialog = CityDialog(self, self.service.search)
        self.open_input_dialog(dialog, dialog.editor, self.change_city)

    def show_glass_notice(self, title, message):
        if self.input_dialog is None:
            dialog = GlassNotice(self, title, message)
            self.open_input_dialog(dialog, dialog.primary, lambda _: None)

    def set_pinned(self, pinned):
        self.pinned = pinned
        self.pin_action.setIcon(line_icon("pin", pinned))
        self.settings.setValue("pinned", pinned)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        self.show()

    def restore(self):
        if not self.orb_action.isChecked():
            self.expand_now()
        self.show()
        self.raise_()

    def on_tray(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.restore()

    def showEvent(self, event):
        super().showEvent(event)
        self.last_frame = monotonic()
        self.timer.start(IDLE_FRAME_MS)
        self.poll_activity()
        self.activity_timer.start(400)
        if self.work_action.isChecked():
            self.work_timer.start()
        self.update_workday()
        if self.can_shuffle():
            self.shuffle_timer.start()
        self.check_focus()

    def hideEvent(self, event):
        self.close_work_memory()
        self.activity_panel.hide()
        self.hover_card.reset()
        self.timer.stop()
        self.fold_snapshot = None
        if self.activity_timer.isActive():
            self.activity_timer.setInterval(1500)
        self.ambient.clear()
        self.keep_bottle_until = 0.
        self.shuffle_timer.stop()
        self.work_timer.stop()
        self.work_fireworks.hide()
        self.work_progress = self.work_celebration = self.work_last_checked = None
        self.focus_capsule.hide()
        self.quick_panel.hide()
        self.focus_morph = float(self.focus.phase != "idle" and not self.orb_action.isChecked())
        self.previous_scene = None
        self.hover = 0.0
        super().hideEvent(event)

    def closeEvent(self, event):
        self.close_work_memory()
        self.save_position()
        self.settings.sync()
        self.tray.hide()
        super().closeEvent(event)
        QApplication.quit()

    def contextMenuEvent(self, event):
        self.close_work_memory()
        self.activity_panel.hide()
        self.hover_card.reset()
        self.quick_panel.hide()
        self.focus_capsule.hide()
        self.work_fireworks.hide()
        self.menu.popup_at(event.globalPos())

    def cap_center(self):
        scale = self.bottle_scale / 100
        return QPoint(round(80 * scale), round(20 * scale))

    def global_cap_contains(self, position):
        if self.focus.phase != "idle" or self.focus_morph > 0 or self.fold < 1.:
            return False
        scale = self.bottle_scale / 100
        local = self.mapFromGlobal(position)
        return QRectF(47, 1, 66, 33).contains(local.x() / scale, local.y() / scale)

    def toggle_quick_panel(self):
        if self.close_work_memory():
            return
        if self.quick_panel.isVisible():
            self.quick_panel.dismiss()
        elif not self.focus_capsule.isVisible() and self.input_dialog is None and QApplication.activeModalWidget() is None:
            self.work_fireworks.hide()
            self.quick_panel.reveal()

    def mousePressEvent(self, event):
        self.hover_card.reset()
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.press_position = self.last_pointer = event.globalPosition().toPoint()
        self.start_position = self.pos()
        self.dragging = False

    def mouseMoveEvent(self, event):
        if self.press_position is None:
            return super().mouseMoveEvent(event)
        pointer = event.globalPosition().toPoint()
        delta = pointer - self.press_position
        if not self.dragging and delta.manhattanLength() >= QApplication.startDragDistance():
            self.dragging = True
            self.close_work_memory()
            self.activity_panel.hide()
            self.quick_panel.hide()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self.dragging:
            self.move(self.start_position + delta)
            if self.focus_capsule.isVisible():
                self.focus_capsule.reposition(self)
            impulse = (pointer.x() - self.last_pointer.x()) * 1.6
            self.tilt = max(-30.0, min(30.0, self.tilt + impulse))
        self.last_pointer = pointer

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.press_position is None:
            return super().mouseReleaseEvent(event)
        pointer = event.globalPosition().toPoint()
        delta = pointer - self.press_position
        if self.dragging or delta.manhattanLength() >= QApplication.startDragDistance():
            self.finish_drag(self.start_position + delta, pointer)
        elif self.fold == 0.:
            if (self.visible_pin and self.visible_pin["state"] in REVIEW_STATES
                    and self.strip_progress >= .65 and not self.compact_pearl_contains(pointer)):
                self.open_activity(self.visible_pin)
            else:
                self.toggle_activity_panel()
        elif self.focus.running:
            self.toggle_focus_pause()
        elif self.fold < 1.:
            self.peek_bottle()
        elif self.global_cap_contains(self.press_position) and self.global_cap_contains(event.globalPosition().toPoint()):
            self.toggle_quick_panel()
        elif self.can_shuffle():
            self.next_random_scene()
        elif self.focus.phase == "idle":
            choices = list(WEATHER)
            self.preview_weather(choices[(choices.index(self.weather) + 1) % len(choices)])
        self.press_position = None
        self.dragging = False
        self.update_shape_cursor()
        if self.focus_capsule.isVisible():
            self.focus_capsule.reposition(self)

    def finish_drag(self, position, pointer):
        self.close_work_memory()
        self.activity_panel.hide()
        self.quick_panel.hide()
        center = position + self.rect().center()
        screen = QApplication.screenAt(pointer) or QApplication.screenAt(center) or self.screen()
        self.move(self.clamp_position(position, screen))
        full_w, full_h = self.bottle_size()
        if self.fold == 0.:
            orb_w = round(ORB_SIZE * self.bottle_scale / 100)
            pearl_x = self.x() + (self.width() - orb_w if self.compact_on_right else 0)
            self.position_right = pearl_x + orb_w / 2 > screen.availableGeometry().center().x()
            anchor_x = pearl_x - (full_w - orb_w if self.position_right else 0)
            self.shape_offset = QPoint(self.x() - anchor_x, full_h - self.height())
            if not self.visible_pin:
                self.strip_progress, self.compact_face = 0., None
            now = monotonic()
            self.ambient_after_drag = now + .34
            self.ambient.interrupt_visible()
        else:
            self.position_right = self.geometry().center().x() > screen.availableGeometry().center().x()
            self.shape_offset = QPoint(full_w - self.width() if self.position_right else 0, full_h - self.height())
        self.compact_on_right = self.position_right
        self.save_position()
        if self.fold == 1. and self.shape == "bottle":
            self.keep_bottle_until = max(self.keep_bottle_until, monotonic() + .55)

    def update_shape_cursor(self):
        cursor = Qt.CursorShape.OpenHandCursor if self.shape == "bottle" else Qt.CursorShape.PointingHandCursor
        self.setCursor(cursor)

    def animate(self):
        now = monotonic()
        elapsed = min(now - self.last_frame, .15)
        self.last_frame = now
        target = float(self.focus.phase != "idle" and not self.orb_action.isChecked())
        step = elapsed / .57
        if self.focus_morph < target:
            self.focus_morph = min(target, self.focus_morph + step)
        else:
            self.focus_morph = max(target, self.focus_morph - step)
        if (not self.orb_action.isChecked() and self.focus.phase in {"focus_done", "break_done"}
                and not self.focus_capsule.isVisible()):
            self.check_focus()
        if self.work_celebration is not None and self.can_play_work_fireworks():
            elapsed_celebration = self.work_celebration + now - self.work_animation_sample
            if elapsed_celebration < SUNSET_CELEBRATION_SECONDS:
                self.work_fireworks.paint_frame(self, elapsed_celebration)
            else:
                self.work_fireworks.hide()
        elif self.work_fireworks.isVisible():
            self.work_fireworks.hide()
        self.tilt *= math.exp(-4.5 * elapsed)
        cursor = QCursor.pos()
        hovering = (self.visual_geometry().contains(cursor) and not self.dragging and not self.menu.isVisible()
                    and (self.underMouse() or QApplication.topLevelAt(cursor) == self))
        self.update_shape(now, elapsed, hovering)
        morphing = 0. < self.fold < 1. or (self.fold == 0. and 0. < self.strip_progress < 1.)
        if morphing or self.pearl_light.charge or 0. < self.strip_glint < 1.:
            interval = MORPH_FRAME_MS
        elif self.fold > 0. or self.work_fireworks.isVisible():
            interval = IDLE_FRAME_MS
        elif self.reduced_motion:
            interval = PEARL_STATIC_MS
        else:
            interval = PEARL_IDLE_MS if self.pearl_light.mode == "idle" else PEARL_ACTIVE_MS
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        if self.fold in (0., 1.):
            self.time += elapsed
        lit = hovering if self.fold else hovering and self.ambient_lit
        response = (22 if lit else 14) if self.shape == "orb" else 5
        self.hover += (float(lit) - self.hover) * (1 - math.exp(-response * elapsed))
        pin_hover = self.shape == "activity" and self.visible_pin is not None and self.strip_progress >= 1.
        blocked = (self.interaction_busy() or self.quick_panel.isVisible() or self.focus_capsule.isVisible()
                   or self.activity_panel.isVisible() or self.work_memory_visible()
                   or self.work_fireworks.isVisible() or self.focus.phase in {"focus_done", "break_done"}
                   or (not pin_hover and (self.focus_morph != float(self.focus.running) or self.fold < 1.)))
        self.hover_card.tick(elapsed, hovering, blocked)
        if self.previous_scene is not None and self.scene_opacity() == 0:
            self.previous_scene = None
        if self.fold > 0.:
            self.compact_paint_key = None
            self.update()
        else:
            light = self.pearl_light if self.strip_progress < .96 else None
            frame = (self.strip_progress, self.compact_on_right, self.compact_face, light,
                     self.activity_badge(), round(self.hover * 40), round(self.strip_glint, 3),
                     self.press_position is not None and not self.dragging)
            if frame != self.compact_paint_key:
                self.compact_paint_key = frame
                self.update()

    def activity_badge(self):
        return max((1 if item["state"] == "ended" else 2
                    for item in self.activity_panel.records if item["unread"]), default=0)

    def has_unread_activity(self):
        return bool(self.activity_badge())

    def paintEvent(self, event):
        scale = self.bottle_scale / 100
        dpr = self.devicePixelRatioF() * scale
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if self.fold < 1.:
                width, height = self.morph_size()
                x = self.width() - width if self.compact_on_right else 0
                painter.translate(x, self.height() - height)
                handoff = smooth((self.fold - .09) / .80)
                if handoff < 1.:
                    painter.save()
                    painter.setOpacity(1. - handoff)
                    compact_w, compact_h = compact_geometry(self.strip_progress, self.bottle_scale / 100)
                    compact_w = min(width, round(compact_w))
                    inset = (width - compact_w) * smooth(self.fold / .72) * .5
                    x = width - compact_w - inset if self.compact_on_right else inset
                    lift = math.sin(math.pi * self.fold)
                    painter.translate(x, height - compact_h - 1.5 * lift)
                    painter.scale(scale, scale)
                    badge = self.activity_badge()
                    face = self.compact_face
                    state = ("interrupted" if face and face.tone == "error" else "running") if face else None
                    draw_compact(
                        painter, compact_w / scale, compact_h / scale, on_right=self.compact_on_right, state=state,
                        progress=self.strip_progress, hover=max(self.hover, lift * .48), glint=self.strip_glint,
                        active=0, recent=None, finished=0, elapsed=0, change=(0, 1.),
                        face=face, unread=bool(badge), alert=badge == 2, light=self.pearl_light,
                        pressed=self.press_position is not None and not self.dragging,
                    )
                    painter.restore()
                if handoff > 0.:
                    fitted = min(width / SIZE[0], height / SIZE[1], scale)
                    painter.translate((width - SIZE[0] * fitted) / 2, height - SIZE[1] * fitted)
                    painter.scale(fitted, fitted)
                    painter.setOpacity(handoff)
                    painter.drawPixmap(0, 0, self.bottle_snapshot(dpr))
                return
            painter.scale(scale, scale)
            self.paint_bottle(painter, dpr)

    def bottle_snapshot(self, dpr):
        # The weather clock is paused during the transition so every frame can reuse this raster.
        key = (dpr, self.weather, self.focus_morph, id(self.previous_scene))
        if self.fold_snapshot is None or self.fold_snapshot[0] != key:
            self.fold_snapshot = key, raster(dpr, lambda p: self.paint_bottle(p, dpr))
        return self.fold_snapshot[1]

    def paint_bottle(self, painter, dpr):
        amount = self.focus_morph ** 2 * (3 - 2 * self.focus_morph)
        if amount < 1:
            self.renderer.prepare(dpr)
            if amount > 0:
                # Clip the outgoing world to the animated silhouette while the sand appears.
                painter.save()
                clip = morph_outline(amount)
                clip.addRect(0, 0, SIZE[0], 31)
                clip.addRect(0, 172, SIZE[0], 26)
                clip.setFillRule(Qt.FillRule.WindingFill)
                painter.setClipPath(clip)
            cap_open = self.quick_panel.cap_opening()
            self.renderer.paint(painter, self.weather, self.time, self.tilt, self.hover,
                                self.previous_scene, self.scene_opacity(), cap_open=cap_open,
                                cap_side=self.quick_panel.cap_side() if cap_open else 1)
            if amount == 0 and self.work_progress is not None:
                draw_workday_indicator(painter, self.work_progress, self.work_fireworks.isVisible())
            if amount > 0:
                painter.restore()
        if amount > 0:
            self.hourglass.prepare(dpr)
            active = self.focus.phase != "idle"
            progress = self.focus.progress if active else self.focus_exit_progress
            self.hourglass.paint(
                painter, amount, progress, self.time, self.focus.running and self.focus.deadline is not None,
                active and not self.focus.running, self.focus.clock_text if self.focus.running else "", self.hover,
                self.focus.phase in {"break", "break_done"},
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    install_typography(app)
    app.setApplicationDisplayName("灵动珠 Dynamic Pearl")
    # The bottle is a tool window, so closing a city dialog can otherwise quit Qt.
    app.setQuitOnLastWindowClosed(False)
    bottle = WeatherBottle()
    bottle.show()
    sys.exit(app.exec())
