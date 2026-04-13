from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from autocruise.domain.models import Action, ActionType, Bounds
from autocruise.infrastructure.windows.window_manager import WindowManager


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_DELETE = 0x2E
VK_LWIN = 0x5B
ULONG_PTR = getattr(wintypes, "ULONG_PTR", wintypes.WPARAM)
SM_CYSCREEN = 1
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
EDIT_CONTROL_HINTS = {"edit", "document", "text", "combo"}
SEARCH_HINTS = {"search", "searchbutton", "searchbox", "検索"}

SPECIAL_KEYS = {
    "backspace": VK_BACK,
    "tab": VK_TAB,
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "esc": VK_ESCAPE,
    "escape": VK_ESCAPE,
    "space": VK_SPACE,
    "pageup": VK_PRIOR,
    "pgup": VK_PRIOR,
    "pagedown": VK_NEXT,
    "pgdn": VK_NEXT,
    "end": VK_END,
    "home": VK_HOME,
    "left": VK_LEFT,
    "up": VK_UP,
    "right": VK_RIGHT,
    "down": VK_DOWN,
    "delete": VK_DELETE,
    "del": VK_DELETE,
    "win": VK_LWIN,
    "cmd": VK_LWIN,
    "meta": VK_LWIN,
}
for index in range(1, 13):
    SPECIAL_KEYS[f"f{index}"] = 0x6F + index


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR]
user32.mouse_event.restype = None
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR]
user32.keybd_event.restype = None
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t


class InputExecutor:
    def __init__(self, window_manager: WindowManager) -> None:
        self.window_manager = window_manager

    def execute(self, action: Action) -> tuple[bool, str]:
        try:
            if action.type == ActionType.FOCUS_WINDOW:
                window = self.window_manager.find_window(action.target.window_title or action.target.name)
                if not window:
                    return False, "Target window not found"
                return self.window_manager.focus_window(window.window_id), "Focused window"

            if action.type == ActionType.WAIT:
                time.sleep(0.8)
                return True, "Waited"

            if action.type == ActionType.HOTKEY:
                ok, detail = self._send_hotkey(action.hotkey)
                return ok, detail

            if action.type == ActionType.SCROLL:
                user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(action.scroll_amount or -240), 0)
                return True, "Scrolled"

            if action.type in {ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK}:
                self._focus_target_window(action)
                point = self._target_center(action.target.bounds)
                if point is None:
                    return False, "Action has no bounds for pointer execution"
                user32.SetCursorPos(*point)
                if action.type == ActionType.RIGHT_CLICK:
                    self._mouse_click(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
                else:
                    clicks = 2 if action.type == ActionType.DOUBLE_CLICK else 1
                    for _ in range(clicks):
                        self._mouse_click(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
                        time.sleep(0.05)
                return True, f"Pointer action at {point}"

            if action.type == ActionType.DRAG:
                self._focus_target_window(action)
                scripted_strokes = self._pointer_script_strokes(action)
                if scripted_strokes:
                    stroke_count = 0
                    point_count = 0
                    for points, duration_ms, pause_after_ms in scripted_strokes:
                        if len(points) < 2:
                            continue
                        self._drag_pointer(points, duration_ms)
                        stroke_count += 1
                        point_count += len(points)
                        if pause_after_ms > 0:
                            time.sleep(pause_after_ms / 1000.0)
                    if stroke_count <= 0:
                        return False, "Pointer script did not include a drawable stroke"
                    return True, f"Executed pointer script with {stroke_count} strokes across {point_count} points"
                points = self._drag_points(action)
                if len(points) < 2:
                    return False, "Drag action requires a visible start area and at least one drag point"
                self._drag_pointer(points, max(120, int(action.drag_duration_ms or 600)))
                return True, f"Dragged pointer across {len(points)} points"

            if action.type == ActionType.TYPE_TEXT:
                self._focus_target_window(action)
                if self._should_click_before_typing(action):
                    point = self._target_center(action.target.bounds)
                    if point is not None:
                        user32.SetCursorPos(*point)
                        self._mouse_click(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
                        time.sleep(0.06)
                ok, detail = self._send_text(action.text)
                return ok, detail

            return False, f"Unsupported action type: {action.type.value}"
        except Exception as exc:  # noqa: BLE001
            message = str(exc).strip() or f"{action.type.value} failed"
            return False, message

    def _target_center(self, bounds: Bounds | None) -> tuple[int, int] | None:
        if bounds is None:
            return None
        return (bounds.left + bounds.width // 2, bounds.top + bounds.height // 2)

    def _mouse_click(self, down_flag: int, up_flag: int) -> None:
        user32.mouse_event(down_flag, 0, 0, 0, 0)
        user32.mouse_event(up_flag, 0, 0, 0, 0)

    def _focus_target_window(self, action: Action) -> None:
        candidates: list[str] = []
        for value in (action.target.window_title, action.target.name):
            text = str(value or "").strip()
            if text and text not in candidates:
                candidates.append(text)
        marker = str(action.target.fallback_visual_hint or "").strip().lower()
        if marker.startswith("launch:"):
            app_key = marker.split(":", 1)[1].strip()
            if app_key and app_key not in candidates:
                candidates.append(app_key)
        for title in candidates:
            window = self.window_manager.find_window(title)
            if window is not None:
                self.window_manager.focus_window(window.window_id)
                time.sleep(0.05)
                return

    def _send_text(self, text: str) -> tuple[bool, str]:
        if not text:
            return True, "Typed text"
        if self._should_paste_text(text):
            return self._paste_text(text)
        for char in text:
            if not self._send_virtual_key_char(char):
                self._send_unicode_char(char)
            time.sleep(0.01)
        return True, f"Typed text: {len(text)} chars"

    def _should_paste_text(self, text: str) -> bool:
        normalized = str(text or "")
        return any(ord(char) > 127 for char in normalized) or "\n" in normalized or "\r" in normalized or "\t" in normalized

    def _paste_text(self, text: str) -> tuple[bool, str]:
        previous_text = self._read_clipboard_text()
        clipboard_written = False
        try:
            self._write_clipboard_text(text)
            clipboard_written = True
            ok, details = self._send_hotkey("CTRL+V")
            if not ok:
                return ok, details
            time.sleep(0.05)
            return True, f"Pasted text: {len(text)} chars"
        finally:
            if clipboard_written and previous_text is not None:
                try:
                    self._write_clipboard_text(previous_text)
                except OSError:
                    pass

    def _read_clipboard_text(self) -> str | None:
        if not self._open_clipboard():
            return None
        try:
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                size = int(kernel32.GlobalSize(handle) or 0)
                if size <= 0:
                    return ""
                raw = ctypes.string_at(pointer, size)
            finally:
                kernel32.GlobalUnlock(handle)
            return raw.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]
        finally:
            user32.CloseClipboard()

    def _write_clipboard_text(self, text: str) -> None:
        encoded = ((text or "").replace("\r\n", "\n").replace("\r", "\n") + "\x00").encode("utf-16-le")
        if not self._open_clipboard():
            raise OSError("Could not open the clipboard")
        try:
            if not user32.EmptyClipboard():
                raise OSError("Could not clear the clipboard")
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            if not handle:
                raise OSError("Could not allocate clipboard memory")
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise OSError("Could not lock clipboard memory")
            try:
                ctypes.memmove(pointer, encoded, len(encoded))
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                raise OSError("Could not set clipboard text")
        finally:
            user32.CloseClipboard()

    def _open_clipboard(self) -> bool:
        for _ in range(8):
            if user32.OpenClipboard(None):
                return True
            time.sleep(0.02)
        return False

    def _send_unicode_char(self, char: str) -> None:
        code = ord(char)
        down = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0)))
        up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)),
        )
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))

    def _send_hotkey(self, combo: str) -> tuple[bool, str]:
        parts = [part.strip().lower() for part in combo.split("+") if part.strip()]
        if not parts:
            return False, "Hotkey is empty"
        modifier_map = {
            "ctrl": VK_CONTROL,
            "control": VK_CONTROL,
            "shift": VK_SHIFT,
            "alt": VK_MENU,
            "win": VK_LWIN,
            "cmd": VK_LWIN,
            "meta": VK_LWIN,
        }
        pressed: list[int] = []
        for part in parts[:-1]:
            key = modifier_map.get(part)
            if key is not None:
                user32.keybd_event(key, 0, 0, 0)
                pressed.append(key)

        final = parts[-1] if parts else ""
        vk = self._vk_for_key(final)
        if vk == 0:
            for key in reversed(pressed):
                user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
            return False, f"Unsupported hotkey: {combo}"
        if vk:
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

        for key in reversed(pressed):
            user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
        return True, f"Sent hotkey {combo}"

    def _vk_for_key(self, key: str) -> int:
        normalized = key.strip().lower()
        if normalized in SPECIAL_KEYS:
            return SPECIAL_KEYS[normalized]
        if len(normalized) == 1:
            return ord(normalized.upper())
        return 0

    def _send_virtual_key_char(self, char: str) -> bool:
        vk_scan = int(user32.VkKeyScanW(char))
        if vk_scan < 0:
            return False
        vk = vk_scan & 0xFF
        if vk == 0xFF:
            return False
        shift_state = (vk_scan >> 8) & 0xFF
        modifiers: list[int] = []
        if shift_state & 1:
            modifiers.append(VK_SHIFT)
        if shift_state & 2:
            modifiers.append(VK_CONTROL)
        if shift_state & 4:
            modifiers.append(VK_MENU)
        for key in modifiers:
            user32.keybd_event(key, 0, 0, 0)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        for key in reversed(modifiers):
            user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
        return True

    def _should_click_before_typing(self, action: Action) -> bool:
        bounds = action.target.bounds
        if bounds is None:
            return False
        if self._looks_like_taskbar_search_target(action):
            return False
        control_type = (action.target.control_type or "").strip().lower()
        if any(hint in control_type for hint in EDIT_CONTROL_HINTS):
            return True
        return True

    def _looks_like_taskbar_search_target(self, action: Action) -> bool:
        bounds = action.target.bounds
        if bounds is None:
            return False
        screen_height = max(int(user32.GetSystemMetrics(SM_CYSCREEN)), 0)
        combined = " ".join(
            filter(
                None,
                [
                    action.target.name.lower(),
                    action.target.automation_id.lower(),
                    action.target.control_type.lower(),
                    action.target.fallback_visual_hint.lower(),
                ],
            )
        )
        if any(hint in combined for hint in SEARCH_HINTS):
            return True
        return bool(screen_height and bounds.top >= max(screen_height - 120, 0) and not action.target.window_title.strip())

    def _drag_points(self, action: Action) -> list[tuple[int, int]]:
        if action.drag_coordinate_mode == "relative":
            bounds = action.target.bounds
            if bounds is None:
                return []
            return [self._relative_point_to_screen(bounds, item.x, item.y) for item in action.drag_path]

        points = [(item.x, item.y) for item in action.drag_path]
        if action.target.bounds is not None and points:
            return [self._target_center(action.target.bounds), *points]
        return points

    def _pointer_script_strokes(self, action: Action) -> list[tuple[list[tuple[int, int]], int, int]]:
        bounds = action.target.bounds
        strokes: list[tuple[list[tuple[int, int]], int, int]] = []
        for stroke in action.pointer_script:
            if stroke.button != "left":
                continue
            if stroke.coordinate_mode == "relative":
                if bounds is None:
                    continue
                points = [self._relative_point_to_screen(bounds, item.x, item.y) for item in stroke.path]
            else:
                points = [(item.x, item.y) for item in stroke.path]
            if len(points) < 2:
                continue
            strokes.append((points, max(120, int(stroke.duration_ms or 600)), max(0, int(stroke.pause_after_ms or 0))))
        return strokes

    def _relative_point_to_screen(self, bounds: Bounds, rel_x: int, rel_y: int) -> tuple[int, int]:
        clamped_x = max(0, min(int(rel_x), 1000))
        clamped_y = max(0, min(int(rel_y), 1000))
        return (
            bounds.left + int(round(bounds.width * clamped_x / 1000.0)),
            bounds.top + int(round(bounds.height * clamped_y / 1000.0)),
        )

    def _drag_pointer(self, points: list[tuple[int, int]], duration_ms: int) -> None:
        total_segments = max(len(points) - 1, 1)
        per_segment_ms = max(duration_ms // total_segments, 30)
        start_x, start_y = points[0]
        user32.SetCursorPos(start_x, start_y)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        try:
            for start, end in zip(points, points[1:]):
                self._move_pointer_segment(start, end, per_segment_ms)
        finally:
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def _move_pointer_segment(self, start: tuple[int, int], end: tuple[int, int], duration_ms: int) -> None:
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        distance = max(abs(delta_x), abs(delta_y))
        steps = max(6, min(40, distance // 12 if distance else 6))
        sleep_seconds = max(duration_ms / max(steps, 1) / 1000.0, 0.005)
        for index in range(1, steps + 1):
            ratio = index / steps
            user32.SetCursorPos(
                int(round(start[0] + delta_x * ratio)),
                int(round(start[1] + delta_y * ratio)),
            )
            time.sleep(sleep_seconds)
