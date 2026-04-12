from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal


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
        self._next_id = 1

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
            hotkey_id = self._id_by_action.get(action_name)
            if hotkey_id is None:
                hotkey_id = self._next_id
                self._next_id += 1
                self._id_by_action[action_name] = hotkey_id
            if not bool(user32.RegisterHotKey(None, hotkey_id, modifiers, vk)):
                failures.append(normalized)
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
        self.activated.emit(binding[0])
        return True, 0

    def close(self) -> None:
        self.unregister_all()
