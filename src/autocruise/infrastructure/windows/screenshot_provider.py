from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from autocruise.domain.models import Bounds
from autocruise.infrastructure.windows.visual_guidance import VisualGuideState, annotate_image


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL


class ScreenshotProvider:
    def capture(self, destination: Path, guide_state: VisualGuideState | None = None) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame = self._capture_image()
        if guide_state is not None and not frame.isNull():
            frame = annotate_image(frame, guide_state)
        if frame.isNull() or not frame.save(str(destination), "PNG"):
            self._write_placeholder(destination)
        return destination

    def capture_region(self, destination: Path, bounds: Bounds, guide_state: VisualGuideState | None = None) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame = self._capture_image()
        if frame.isNull():
            self._write_placeholder(destination)
            return destination
        left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        crop = frame.copy(
            max(0, bounds.left - left),
            max(0, bounds.top - top),
            max(1, bounds.width),
            max(1, bounds.height),
        )
        if guide_state is not None and not crop.isNull():
            crop = annotate_image(crop, guide_state)
        if crop.isNull() or not crop.save(str(destination), "PNG"):
            self._write_placeholder(destination)
        return destination

    def _capture_image(self) -> QImage:
        left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or user32.GetSystemMetrics(1)

        desktop_dc = user32.GetDC(None)
        if not desktop_dc:
            return self._placeholder_image()
        mem_dc = gdi32.CreateCompatibleDC(desktop_dc)
        if not mem_dc:
            user32.ReleaseDC(None, desktop_dc)
            return self._placeholder_image()
        bitmap = gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
        if not bitmap:
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(None, desktop_dc)
            return self._placeholder_image()
        old_bitmap = gdi32.SelectObject(mem_dc, bitmap)

        try:
            success = gdi32.BitBlt(mem_dc, 0, 0, width, height, desktop_dc, left, top, SRCCOPY)
            if not success:
                return self._placeholder_image()

            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB

            buffer = ctypes.create_string_buffer(width * height * 4)
            bits = gdi32.GetDIBits(
                mem_dc,
                bitmap,
                0,
                height,
                buffer,
                ctypes.byref(info),
                DIB_RGB_COLORS,
            )
            if bits == 0:
                return self._placeholder_image()

            image = QImage(buffer.raw, width, height, width * 4, QImage.Format_ARGB32)
            return image.copy()
        finally:
            if old_bitmap:
                gdi32.SelectObject(mem_dc, old_bitmap)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if mem_dc:
                gdi32.DeleteDC(mem_dc)
            if desktop_dc:
                user32.ReleaseDC(None, desktop_dc)

    def _write_placeholder(self, destination: Path) -> None:
        image = self._placeholder_image()
        image.save(str(destination), "PNG")

    def _placeholder_image(self) -> QImage:
        image = QImage(320, 180, QImage.Format_RGB32)
        for y in range(image.height()):
            for x in range(image.width()):
                value = 70 + ((x + y) % 80)
                image.setPixelColor(x, y, QColor(value, value, value))
        return image
