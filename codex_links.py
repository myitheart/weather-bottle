"""Open a verified local chat identifier without changing Pearl activity state."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from work_memory.codex_rpc import identifier


def open_codex_thread(thread_id):
    return identifier(thread_id) and QDesktopServices.openUrl(QUrl(f"codex://threads/{thread_id}"))
