from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal


WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

user32 = ctypes.windll.user32
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C


HOTKEY_OPTIONS: list[tuple[str, str]] = [
    ("", "Disabled"),
    ("F8", "F8"),
    ("F9", "F9"),
    ("F10", "F10"),
    ("F11", "F11"),
    ("F12", "F12"),
    ("Ctrl+Alt+P", "Ctrl+Alt+P"),
    ("Ctrl+Alt+S", "Ctrl+Alt+S"),
]

_MODIFIER_FLAGS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
}

_VK_KEYS = {
    "p": 0x50,
    "s": 0x53,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}


def normalize_hotkey(value: str) -> str:
    parts = [part.strip() for part in str(value or "").split("+") if part.strip()]
    if not parts:
        return ""
    modifiers: list[str] = []
    key = ""
    for part in parts:
        lowered = part.lower()
        if lowered in _MODIFIER_FLAGS:
            canonical = "Ctrl" if lowered in {"ctrl", "control"} else lowered.title()
            if canonical not in modifiers:
                modifiers.append(canonical)
            continue
        key = lowered.upper() if len(lowered) == 1 else lowered.upper()
    if not key:
        return ""
    return "+".join([*modifiers, key])


def hotkey_to_native(shortcut: str) -> tuple[int, int] | None:
    normalized = normalize_hotkey(shortcut)
    if not normalized:
        return None
    parts = normalized.split("+")
    modifiers = 0
    for part in parts[:-1]:
        lowered = part.lower()
        modifiers |= _MODIFIER_FLAGS.get(lowered, 0)
    key = parts[-1].lower()
    vk = _VK_KEYS.get(key)
    if vk is None:
        return None
    return modifiers, vk


class GlobalHotkeyManager(QObject, QAbstractNativeEventFilter):
    activated = Signal(str)

    def __init__(self) -> None:
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self._registered: dict[int, tuple[str, str]] = {}
        self._id_by_action: dict[str, int] = {}
        self._binding_specs: dict[str, tuple[int, int, str]] = {}
        self._pressed_actions: set[str] = set()
        self._suppress_poll_until: dict[str, float] = {}
        self._next_id = 1
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll_bindings)
        self._poll_timer.start()

    def apply_bindings(self, bindings: dict[str, str]) -> list[str]:
        self.unregister_all()
        failures: list[str] = []
        for action_name, shortcut in bindings.items():
            native = hotkey_to_native(shortcut)
            normalized = normalize_hotkey(shortcut)
            if not normalized:
                continue
            if native is None:
                failures.append(normalized)
                continue
            modifiers, vk = native
            self._binding_specs[action_name] = (modifiers, vk, normalized)
            hotkey_id = self._id_by_action.get(action_name)
            if hotkey_id is None:
                hotkey_id = self._next_id
                self._next_id += 1
                self._id_by_action[action_name] = hotkey_id
            if not self._register_hotkey(hotkey_id, modifiers, vk):
                continue
            self._registered[hotkey_id] = (action_name, normalized)
        return failures

    def unregister_all(self) -> None:
        for hotkey_id in list(self._registered):
            try:
                user32.UnregisterHotKey(None, hotkey_id)
            except Exception:  # noqa: BLE001
                pass
        self._registered.clear()
        self._binding_specs.clear()
        self._pressed_actions.clear()
        self._suppress_poll_until.clear()

    def _register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> bool:
        return bool(user32.RegisterHotKey(None, hotkey_id, modifiers, vk))

    def _key_down(self, vk: int) -> bool:
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def _binding_pressed(self, modifiers: int, vk: int) -> bool:
        if not self._key_down(vk):
            return False
        if modifiers & MOD_CONTROL and not self._key_down(VK_CONTROL):
            return False
        if modifiers & MOD_SHIFT and not self._key_down(VK_SHIFT):
            return False
        if modifiers & MOD_ALT and not self._key_down(VK_MENU):
            return False
        if modifiers & MOD_WIN and not (self._key_down(VK_LWIN) or self._key_down(VK_RWIN)):
            return False
        return True

    def _poll_bindings(self) -> None:
        now = time.monotonic()
        for action_name, (modifiers, vk, _normalized) in self._binding_specs.items():
            pressed = self._binding_pressed(modifiers, vk)
            was_pressed = action_name in self._pressed_actions
            if pressed:
                if not was_pressed and now >= self._suppress_poll_until.get(action_name, 0.0):
                    self._pressed_actions.add(action_name)
                    self.activated.emit(action_name)
                continue
            if was_pressed:
                self._pressed_actions.discard(action_name)

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if event_type not in {"windows_generic_MSG", "windows_dispatcher_MSG"}:
            return False, 0
        try:
            pointer = int(message)
            msg = ctypes.cast(pointer, ctypes.POINTER(wintypes.MSG)).contents
        except Exception:  # noqa: BLE001
            return False, 0
        if msg.message != WM_HOTKEY:
            return False, 0
        binding = self._registered.get(int(msg.wParam))
        if binding is None:
            return False, 0
        action_name = binding[0]
        self._pressed_actions.add(action_name)
        self._suppress_poll_until[action_name] = time.monotonic() + 0.35
        self.activated.emit(action_name)
        return True, 0

    def close(self) -> None:
        self._poll_timer.stop()
        self.unregister_all()
