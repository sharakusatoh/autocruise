from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from autocruise.domain.automation import automation_element_to_prompt_dict
from autocruise.domain.models import Observation, ObservationKind
from autocruise.infrastructure.automation import AutomationRouter
from autocruise.infrastructure.windows.primary_sensor import PrimarySensorHub, sensor_snapshot_to_dict
from autocruise.infrastructure.windows.screenshot_provider import ScreenshotProvider
from autocruise.infrastructure.windows.uia_adapter import UIAAdapter
from autocruise.infrastructure.windows.visual_guidance import build_visual_guide_state, get_virtual_screen_bounds
from autocruise.infrastructure.windows.window_manager import WindowManager


class WindowsObservationBuilder:
    def __init__(
        self,
        screenshot_provider: ScreenshotProvider,
        window_manager: WindowManager,
        uia_adapter: UIAAdapter,
        *,
        browser_sensor=None,
        automation_router: AutomationRouter | None = None,
        primary_sensor: PrimarySensorHub | None = None,
    ) -> None:
        self.screenshot_provider = screenshot_provider
        self.window_manager = window_manager
        self.uia_adapter = uia_adapter
        self.browser_sensor = browser_sensor
        self.automation_router = automation_router or AutomationRouter([uia_adapter])
        self.primary_sensor = primary_sensor or PrimarySensorHub(window_manager, uia_adapter, browser_sensor)

    def capture(self, screenshot_path: Path, recent_actions: list[str]) -> Observation:
        return self.capture_full(screenshot_path, recent_actions)

    def capture_full(
        self,
        screenshot_path: Path,
        recent_actions: list[str],
        *,
        previous_observation: Observation | None = None,
        sensor_snapshot=None,
        vision_bounds=None,
        observation_kind: ObservationKind = ObservationKind.FULL,
    ) -> Observation:
        sensor_snapshot = sensor_snapshot or self.primary_sensor.snapshot()
        active_window = sensor_snapshot.active_window or self.window_manager.get_active_window()
        visible_windows = self.window_manager.list_windows()
        cursor_position = self.window_manager.cursor_position()
        screen_bounds = get_virtual_screen_bounds()
        guide_state = build_visual_guide_state(
            screen_bounds,
            cursor_position,
            active_window,
            show_grid=True,
        )
        if vision_bounds is not None:
            self.screenshot_provider.capture_region(screenshot_path, vision_bounds, guide_state=guide_state)
        else:
            self.screenshot_provider.capture(screenshot_path, guide_state=guide_state)
        return self._build_observation(
            recent_actions=recent_actions,
            active_window=active_window,
            visible_windows=visible_windows,
            cursor_position=cursor_position,
            screen_bounds=screen_bounds,
            sensor_snapshot=sensor_snapshot,
            screenshot_path=str(screenshot_path),
            guide_state=guide_state.prompt_payload(),
            previous_observation=previous_observation,
            observation_kind=observation_kind,
            vision_fallback_required=observation_kind == ObservationKind.VISION_FALLBACK,
        )

    def refresh_structured(
        self,
        recent_actions: list[str],
        *,
        previous_observation: Observation | None = None,
        sensor_snapshot=None,
    ) -> Observation:
        sensor_snapshot = sensor_snapshot or self.primary_sensor.snapshot()
        active_window = sensor_snapshot.active_window or self.window_manager.get_active_window()
        visible_windows = (
            list(previous_observation.visible_windows)
            if previous_observation is not None and previous_observation.visible_windows
            else ([active_window] if active_window is not None else [])
        )
        cursor_position = self.window_manager.cursor_position()
        screen_bounds = get_virtual_screen_bounds()
        return self._build_observation(
            recent_actions=recent_actions,
            active_window=active_window,
            visible_windows=visible_windows,
            cursor_position=cursor_position,
            screen_bounds=screen_bounds,
            sensor_snapshot=sensor_snapshot,
            screenshot_path=None,
            guide_state={},
            previous_observation=previous_observation,
            observation_kind=ObservationKind.STRUCTURED,
            vision_fallback_required=False,
        )

    def reuse(
        self,
        previous_observation: Observation,
        *,
        sensor_snapshot=None,
        reason: str = "sensor_unchanged",
    ) -> Observation:
        sensor_snapshot = sensor_snapshot or self.primary_sensor.snapshot()
        raw_ref = dict(previous_observation.raw_ref or {})
        raw_ref["sensor_snapshot"] = sensor_snapshot_to_dict(sensor_snapshot)
        raw_ref["observation_kind"] = ObservationKind.REUSED.value
        raw_ref["planner_skip_reason"] = reason
        raw_ref["vision_fallback_required"] = False
        return replace(previous_observation, raw_ref=raw_ref)

    def capture_vision_fallback(
        self,
        screenshot_path: Path,
        recent_actions: list[str],
        *,
        previous_observation: Observation | None = None,
        sensor_snapshot=None,
        target_bounds=None,
    ) -> Observation:
        return self.capture_full(
            screenshot_path,
            recent_actions,
            previous_observation=previous_observation,
            sensor_snapshot=sensor_snapshot,
            vision_bounds=target_bounds,
            observation_kind=ObservationKind.VISION_FALLBACK,
        )

    def _build_observation(
        self,
        *,
        recent_actions: list[str],
        active_window,
        visible_windows,
        cursor_position: tuple[int, int],
        screen_bounds,
        sensor_snapshot,
        screenshot_path: str | None,
        guide_state: dict,
        previous_observation: Observation | None,
        observation_kind: ObservationKind,
        vision_fallback_required: bool,
    ) -> Observation:
        active_hint = active_window.title if active_window else ""
        automation_elements = self._automation_elements(active_hint)
        numbered_automation_elements = self._numbered_automation_elements(automation_elements)
        elements = self._detected_elements(active_hint)
        focused = self.uia_adapter.get_focused_element()
        browser_snapshot = sensor_snapshot.metadata.get("browser", {}) if sensor_snapshot is not None else {}
        uia_available = bool(automation_elements or elements or focused)
        playwright_available = bool(browser_snapshot.get("available"))
        summary = self._summarize(active_window, elements, visible_windows, cursor_position, sensor_snapshot, browser_snapshot)
        change_summary = self._change_summary(previous_observation, active_window, focused, elements, browser_snapshot)
        return Observation(
            screenshot_path=screenshot_path,
            active_window=active_window,
            visible_windows=visible_windows[:20],
            detected_elements=elements[:20],
            ui_tree_summary=summary,
            cursor_position=cursor_position,
            focused_element=self._focused_identity(focused, browser_snapshot),
            textual_hints=self._textual_hints(active_hint, focused, elements, visible_windows, browser_snapshot),
            recent_actions=recent_actions[-5:],
            raw_ref={
                "mode": "windows",
                "visible_window_count": len(visible_windows),
                "screen_bounds": {
                    "left": screen_bounds.left,
                    "top": screen_bounds.top,
                    "width": screen_bounds.width,
                    "height": screen_bounds.height,
                },
                "visual_guides": guide_state,
                "sensor_snapshot": sensor_snapshot_to_dict(sensor_snapshot),
                "observation_kind": observation_kind.value,
                "change_summary": change_summary,
                "planner_skip_reason": "",
                "automation": {
                    "priority": ["uia", "playwright", "cdp", "vision"],
                    "source": "playwright" if playwright_available else ("uia" if uia_available else "vision_fallback"),
                    "availability": {
                        "uia": uia_available,
                        "playwright": playwright_available,
                        "cdp": playwright_available,
                        "vision_fallback": not (uia_available or playwright_available),
                    },
                    "vision_fallback_allowed": not (uia_available or playwright_available),
                    "elements": numbered_automation_elements[:20],
                },
                "screen_understanding": {
                    "ui_candidates": numbered_automation_elements[:20],
                    "ocr_text_blocks": [],
                    "ocr_available": False,
                },
                "vision_fallback_required": vision_fallback_required,
            },
        )

    def _numbered_automation_elements(self, elements) -> list[dict]:
        numbered: list[dict] = []
        for index, item in enumerate(elements[:40], start=1):
            prompt_item = automation_element_to_prompt_dict(item)
            prompt_item["candidate_index"] = index
            numbered.append(prompt_item)
        return numbered

    def _automation_elements(self, active_hint: str):
        try:
            elements = self.automation_router.enumerate(scope="active", limit=40)
        except Exception:  # noqa: BLE001
            elements = []
        if not elements and active_hint:
            try:
                elements = self.automation_router.find(active_hint, limit=20)
            except Exception:  # noqa: BLE001
                elements = []
        return elements

    def _detected_elements(self, active_hint: str):
        elements = self.uia_adapter.find_elements("", limit=40)
        if not elements and active_hint:
            elements = self.uia_adapter.find_elements(active_hint, limit=20)
        return elements

    def _summarize(self, active_window, elements, windows, cursor_position: tuple[int, int], sensor_snapshot, browser_snapshot: dict) -> str:
        active_title = active_window.title if active_window else "No active window"
        element_names = [element.name for element in elements[:5] if element.name]
        window_names = [window.title for window in windows[:3] if window.title]
        active_bounds = (
            f"{active_window.bounds.left},{active_window.bounds.top},{active_window.bounds.width}x{active_window.bounds.height}"
            if active_window is not None and active_window.bounds is not None
            else "unknown"
        )
        browser_title = str(browser_snapshot.get("title", "")).strip()
        browser_url = str(browser_snapshot.get("url", "")).strip()
        sensor_bits = f"fingerprint={sensor_snapshot.fingerprint}; events={sensor_snapshot.event_counts}" if sensor_snapshot is not None else ""
        return (
            f"Active={active_title}; active_bounds={active_bounds}; cursor={cursor_position}; "
            f"windows={window_names}; elements={element_names}; browser_title={browser_title}; "
            f"browser_url={browser_url}; {sensor_bits}"
        )

    def _focused_identity(self, focused, browser_snapshot: dict) -> str:
        browser_identity = str(browser_snapshot.get("focused_element", "")).strip()
        if browser_identity:
            return browser_identity
        if focused is None:
            return ""
        parts = [focused.control_type, focused.name or focused.automation_id]
        return ":".join(part for part in parts if part)

    def _textual_hints(self, active_hint: str, focused, elements, windows, browser_snapshot: dict) -> list[str]:
        hints: list[str] = []
        for item in [
            active_hint,
            browser_snapshot.get("title", ""),
            browser_snapshot.get("url", ""),
            browser_snapshot.get("focused_element", ""),
            focused.name if focused is not None else "",
            focused.automation_id if focused is not None else "",
            *[element.name for element in elements[:8] if element.name],
            *[window.title for window in windows[:5] if window.title],
        ]:
            text = str(item or "").strip()
            if text and text not in hints:
                hints.append(text)
        return hints[:12]

    def _change_summary(self, previous_observation: Observation | None, active_window, focused, elements, browser_snapshot: dict) -> str:
        if previous_observation is None:
            return "Initial observation."
        changes: list[str] = []
        previous_window = previous_observation.active_window.title if previous_observation.active_window else ""
        current_window = active_window.title if active_window else ""
        if previous_window != current_window:
            changes.append(f"window:{previous_window}->{current_window}")
        previous_focus = previous_observation.focused_element
        current_focus = self._focused_identity(focused, browser_snapshot)
        if previous_focus != current_focus:
            changes.append(f"focus:{previous_focus}->{current_focus}")
        previous_names = [element.name for element in previous_observation.detected_elements[:5] if element.name]
        current_names = [element.name for element in elements[:5] if element.name]
        if previous_names != current_names:
            changes.append(f"elements:{previous_names}->{current_names}")
        if previous_observation.ui_tree_summary == "":
            return "; ".join(changes) or "No structured changes."
        return "; ".join(changes) or "No structured changes."
