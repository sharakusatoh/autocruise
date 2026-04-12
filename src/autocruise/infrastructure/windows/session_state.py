from __future__ import annotations

import ctypes


DESKTOP_SWITCHDESKTOP = 0x0100


def is_workstation_locked() -> bool:
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return False

    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.OpenInputDesktop.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_uint]
    user32.SwitchDesktop.argtypes = [ctypes.c_void_p]
    user32.SwitchDesktop.restype = ctypes.c_bool
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    user32.CloseDesktop.restype = ctypes.c_bool

    desktop = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return False
    try:
        return not bool(user32.SwitchDesktop(desktop))
    finally:
        user32.CloseDesktop(desktop)
