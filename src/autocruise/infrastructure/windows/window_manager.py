from __future__ import annotations

import ctypes
from ctypes import wintypes

from autocruise.domain.models import Bounds, WindowInfo


user32 = ctypes.windll.user32


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
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL


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
        user32.ShowWindow(hwnd, 5)
        return bool(user32.SetForegroundWindow(hwnd))

    def find_window(self, title_hint: str) -> WindowInfo | None:
        hint = title_hint.lower()
        for window in self.list_windows():
            if hint in window.title.lower():
                return window
        return None

    def cursor_position(self) -> tuple[int, int]:
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return (int(point.x), int(point.y))
