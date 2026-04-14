from __future__ import annotations

import ctypes
import re
from ctypes import wintypes

from autocruise.domain.models import Bounds, WindowInfo


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetFocus.argtypes = [wintypes.HWND]
user32.SetFocus.restype = wintypes.HWND
user32.SetActiveWindow.argtypes = [wintypes.HWND]
user32.SetActiveWindow.restype = wintypes.HWND
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.EnumChildWindows.argtypes = [wintypes.HWND, EnumWindowsProc, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

EDIT_WINDOW_CLASSES = {
    "edit",
    "richedit20w",
    "richedit50w",
    "richeditd2dpt",
    "notepadtextbox",
}


class WindowManager:
    def list_windows(self) -> list[WindowInfo]:
        windows: list[WindowInfo] = []

        @EnumWindowsProc
        def callback(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title_buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, length + 1)
            title = title_buffer.value.strip()
            if not title:
                return True

            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, 256)
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            windows.append(
                WindowInfo(
                    window_id=int(hwnd),
                    title=title,
                    class_name=class_buffer.value,
                    bounds=Bounds(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                    is_visible=True,
                    process_id=int(process_id.value),
                )
            )
            return True

        user32.EnumWindows(callback, 0)
        return windows

    def get_active_window(self) -> WindowInfo | None:
        return self.get_foreground_summary()

    def get_foreground_summary(self) -> WindowInfo | None:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(length + 1, 1))
        if length > 0:
            user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        title = title_buffer.value.strip()
        return WindowInfo(
            window_id=int(hwnd),
            title=title,
            class_name=class_buffer.value,
            bounds=Bounds(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
            is_visible=bool(user32.IsWindowVisible(hwnd)),
            process_id=int(process_id.value),
        )

    def focus_window(self, window_id: int) -> bool:
        hwnd = wintypes.HWND(window_id)
        if not user32.IsWindow(hwnd):
            return False
        foreground = user32.GetForegroundWindow()
        current_thread = int(kernel32.GetCurrentThreadId())
        target_process = wintypes.DWORD()
        target_thread = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_process)))
        attached_threads: list[tuple[int, int]] = []
        if foreground:
            foreground_process = wintypes.DWORD()
            foreground_thread = int(user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_process)))
            for source_thread, target in ((current_thread, target_thread), (foreground_thread, target_thread)):
                if source_thread and target and source_thread != target and user32.AttachThreadInput(source_thread, target, True):
                    attached_threads.append((source_thread, target))
        try:
            user32.ShowWindow(hwnd, 9)
            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
            if user32.SetForegroundWindow(hwnd):
                return True
            return int(user32.GetForegroundWindow() or 0) == int(window_id)
        finally:
            for source_thread, target in reversed(attached_threads):
                user32.AttachThreadInput(source_thread, target, False)

    def find_window(self, title_hint: str) -> WindowInfo | None:
        hint = self._normalize_text(title_hint)
        if not hint:
            return None
        for window in self.list_windows():
            window_title = self._normalize_text(window.title)
            window_class = self._normalize_text(window.class_name)
            if hint in window_title or hint in window_class:
                return window
        return None

    def list_child_windows(self, window_id: int) -> list[WindowInfo]:
        hwnd = wintypes.HWND(window_id)
        if not user32.IsWindow(hwnd):
            return []
        windows: list[WindowInfo] = []

        @EnumWindowsProc
        def callback(child_hwnd, lparam):
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(child_hwnd, class_buffer, 256)
            title_length = user32.GetWindowTextLengthW(child_hwnd)
            title_buffer = ctypes.create_unicode_buffer(max(title_length + 1, 1))
            if title_length > 0:
                user32.GetWindowTextW(child_hwnd, title_buffer, title_length + 1)
            rect = RECT()
            user32.GetWindowRect(child_hwnd, ctypes.byref(rect))
            windows.append(
                WindowInfo(
                    window_id=int(child_hwnd),
                    title=title_buffer.value.strip(),
                    class_name=class_buffer.value,
                    bounds=Bounds(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                    is_visible=bool(user32.IsWindowVisible(child_hwnd)),
                )
            )
            return True

        user32.EnumChildWindows(hwnd, callback, 0)
        return windows

    def find_editable_child(self, window_id: int) -> WindowInfo | None:
        candidates = [
            item
            for item in self.list_child_windows(window_id)
            if self._normalize_text(item.class_name) in EDIT_WINDOW_CLASSES and item.bounds is not None
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item.bounds.width * item.bounds.height) if item.bounds else 0, reverse=True)
        return candidates[0]

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "")).casefold()

    def cursor_position(self) -> tuple[int, int]:
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return (int(point.x), int(point.y))
