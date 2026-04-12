from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from autocruise.domain.models import Bounds, WindowInfo


user32 = ctypes.windll.user32

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

GRID_MINOR_COLOR = QColor(255, 255, 255, 34)
GRID_MAJOR_COLOR = QColor(255, 255, 255, 76)
WINDOW_BORDER_COLOR = QColor(71, 170, 255, 176)
CURSOR_COLOR = QColor(255, 208, 84, 224)
LABEL_BG = QColor(7, 10, 14, 196)
LABEL_TEXT = QColor(241, 245, 249)

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int


@dataclass(slots=True)
class VisualGuideState:
    screen_bounds: Bounds
    cursor_position: tuple[int, int]
    active_window_title: str = ""
    active_window_bounds: Bounds | None = None
    show_grid: bool = False
    show_text_labels: bool = False
    show_legend: bool = False
    minor_grid_step: int = 40
    major_grid_step: int = 200

    def prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "screen_origin": {"x": self.screen_bounds.left, "y": self.screen_bounds.top},
            "screen_size": {"width": self.screen_bounds.width, "height": self.screen_bounds.height},
            "cursor_position": {"x": self.cursor_position[0], "y": self.cursor_position[1]},
            "show_grid": self.show_grid,
            "show_text_labels": self.show_text_labels,
            "show_legend": self.show_legend,
            "minor_grid_step": self.minor_grid_step,
            "major_grid_step": self.major_grid_step,
            "coordinate_space": "global_windows_screen_coordinates",
        }
        if self.active_window_title:
            payload["active_window_title"] = self.active_window_title
        if self.active_window_bounds is not None:
            payload["active_window_bounds"] = asdict(self.active_window_bounds)
        return payload


def get_virtual_screen_bounds() -> Bounds:
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or user32.GetSystemMetrics(1)
    return Bounds(left=left, top=top, width=max(1, width), height=max(1, height))


def build_visual_guide_state(
    screen_bounds: Bounds,
    cursor_position: tuple[int, int],
    active_window: WindowInfo | None,
    *,
    show_grid: bool = False,
    show_text_labels: bool = False,
    show_legend: bool = False,
    minor_grid_step: int = 40,
    major_grid_step: int = 200,
) -> VisualGuideState:
    minor = max(20, int(minor_grid_step or 40))
    major = max(minor * 2, int(major_grid_step or 200))
    if major % minor != 0:
        major += minor - (major % minor)
    return VisualGuideState(
        screen_bounds=screen_bounds,
        cursor_position=(int(cursor_position[0]), int(cursor_position[1])),
        active_window_title=active_window.title if active_window is not None else "",
        active_window_bounds=active_window.bounds if active_window is not None else None,
        show_grid=bool(show_grid),
        show_text_labels=bool(show_text_labels),
        show_legend=bool(show_legend),
        minor_grid_step=minor,
        major_grid_step=major,
    )


def annotate_image(image: QImage, state: VisualGuideState) -> QImage:
    annotated = image.copy()
    painter = QPainter(annotated)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    paint_visual_guides(painter, annotated.width(), annotated.height(), state)
    painter.end()
    return annotated


def paint_visual_guides(painter: QPainter, canvas_width: int, canvas_height: int, state: VisualGuideState) -> None:
    if canvas_width <= 0 or canvas_height <= 0:
        return
    allow_text = QGuiApplication.instance() is not None and state.show_text_labels
    painter.save()
    painter.setClipRect(0, 0, canvas_width, canvas_height)
    if state.show_grid:
        _draw_grid(painter, canvas_width, canvas_height, state, allow_text=allow_text)
    _draw_active_window(painter, canvas_width, canvas_height, state, allow_text=allow_text)
    _draw_cursor(painter, canvas_width, canvas_height, state, allow_text=allow_text)
    if state.show_legend and QGuiApplication.instance() is not None:
        _draw_legend(painter, canvas_width, canvas_height, state)
    painter.restore()


def _draw_grid(painter: QPainter, width: int, height: int, state: VisualGuideState, *, allow_text: bool) -> None:
    screen = state.screen_bounds
    start_x = _aligned_start(screen.left, state.minor_grid_step)
    end_x = screen.left + screen.width
    start_y = _aligned_start(screen.top, state.minor_grid_step)
    end_y = screen.top + screen.height

    minor_pen = QPen(GRID_MINOR_COLOR, 1)
    major_pen = QPen(GRID_MAJOR_COLOR, 1)

    for global_x in range(start_x, end_x + 1, state.minor_grid_step):
        local_x = global_x - screen.left
        if local_x < 0 or local_x > width:
            continue
        is_major = global_x % state.major_grid_step == 0
        painter.setPen(major_pen if is_major else minor_pen)
        painter.drawLine(local_x, 0, local_x, height)
        if is_major and allow_text:
            _draw_tag(
                painter,
                f"x {global_x}",
                _clamp(local_x + 4, 4, max(4, width - 64)),
                6,
            )

    for global_y in range(start_y, end_y + 1, state.minor_grid_step):
        local_y = global_y - screen.top
        if local_y < 0 or local_y > height:
            continue
        is_major = global_y % state.major_grid_step == 0
        painter.setPen(major_pen if is_major else minor_pen)
        painter.drawLine(0, local_y, width, local_y)
        if is_major and allow_text:
            _draw_tag(
                painter,
                f"y {global_y}",
                6,
                _clamp(local_y + 4, 6, max(6, height - 24)),
            )


def _draw_active_window(painter: QPainter, width: int, height: int, state: VisualGuideState, *, allow_text: bool) -> None:
    bounds = state.active_window_bounds
    if bounds is None:
        return
    screen = state.screen_bounds
    rect = QRect(
        bounds.left - screen.left,
        bounds.top - screen.top,
        bounds.width,
        bounds.height,
    )
    if not rect.intersects(QRect(0, 0, width, height)):
        return
    painter.save()
    pen = QPen(WINDOW_BORDER_COLOR, 2)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(rect)
    if allow_text:
        label = f"Active: {state.active_window_title[:42]} [{bounds.left}, {bounds.top}, {bounds.width}x{bounds.height}]"
        _draw_tag(
            painter,
            label,
            _clamp(rect.left() + 8, 6, max(6, width - 280)),
            _clamp(rect.top() + 8, 6, max(6, height - 24)),
        )
    painter.restore()


def _draw_cursor(painter: QPainter, width: int, height: int, state: VisualGuideState, *, allow_text: bool) -> None:
    screen = state.screen_bounds
    x = state.cursor_position[0] - screen.left
    y = state.cursor_position[1] - screen.top
    if x < -40 or y < -40 or x > width + 40 or y > height + 40:
        return

    painter.save()
    pen = QPen(CURSOR_COLOR, 2)
    painter.setPen(pen)
    painter.drawLine(x - 18, y, x + 18, y)
    painter.drawLine(x, y - 18, x, y + 18)
    painter.drawEllipse(QPoint(x, y), 8, 8)
    painter.drawEllipse(QPoint(x, y), 2, 2)
    if allow_text:
        _draw_tag(
            painter,
            f"Cursor {state.cursor_position[0]}, {state.cursor_position[1]}",
            _clamp(x + 14, 6, max(6, width - 180)),
            _clamp(y + 14, 6, max(6, height - 24)),
        )
    painter.restore()


def _draw_legend(painter: QPainter, width: int, height: int, state: VisualGuideState) -> None:
    lines = [
        f"Origin {state.screen_bounds.left}, {state.screen_bounds.top}",
        f"Screen {state.screen_bounds.width}x{state.screen_bounds.height}",
        f"Cursor {state.cursor_position[0]}, {state.cursor_position[1]}",
    ]
    if state.show_grid:
        lines.append(f"Grid {state.minor_grid_step}px / {state.major_grid_step}px")
    if state.active_window_title:
        lines.append(f"Active {state.active_window_title[:36]}")

    painter.save()
    font = QFont()
    font.setPointSize(9)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    max_width = max(metrics.horizontalAdvance(line) for line in lines) + 18
    box_height = (metrics.height() * len(lines)) + 16
    box = QRect(12, max(12, height - box_height - 12), min(max_width, width - 24), box_height)
    painter.setPen(Qt.NoPen)
    painter.setBrush(LABEL_BG)
    painter.drawRoundedRect(box, 10, 10)
    painter.setPen(LABEL_TEXT)
    text_y = box.top() + 12 + metrics.ascent()
    for line in lines:
        painter.drawText(box.left() + 9, text_y, line)
        text_y += metrics.height()
    painter.restore()


def _draw_tag(painter: QPainter, text: str, x: int, y: int) -> None:
    painter.save()
    font = QFont()
    font.setPointSize(8)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    rect = QRect(x, y, metrics.horizontalAdvance(text) + 12, metrics.height() + 8)
    painter.setPen(Qt.NoPen)
    painter.setBrush(LABEL_BG)
    painter.drawRoundedRect(rect, 8, 8)
    painter.setPen(LABEL_TEXT)
    painter.drawText(rect.adjusted(6, 4, -6, -4), Qt.AlignLeft | Qt.AlignVCenter, text)
    painter.restore()


def _aligned_start(origin: int, step: int) -> int:
    return (origin // step) * step


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))
