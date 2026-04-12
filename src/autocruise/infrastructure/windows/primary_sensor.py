from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from typing import Iterable

from autocruise.domain.models import ExpectedSignal, ExpectedSignalKind, Observation, PrimarySensorSnapshot, WindowInfo


class PrimarySensorHub:
    def __init__(self, window_manager, uia_adapter, browser_sensor=None) -> None:
        self.window_manager = window_manager
        self.uia_adapter = uia_adapter
        self.browser_sensor = browser_sensor

    def snapshot(self) -> PrimarySensorSnapshot:
        active_window = self._active_window()
        uia_snapshot = self._uia_snapshot()
        browser_snapshot = self._browser_snapshot()
        focused_element = str(
            browser_snapshot.get("focused_element")
            or uia_snapshot.get("focused_element")
            or ""
        )
        active_backend = "playwright" if browser_snapshot.get("available") else str(uia_snapshot.get("backend") or "uia")
        event_counts = self._merge_event_counts(uia_snapshot.get("event_counts", {}), browser_snapshot.get("event_counts", {}))
        fingerprint_payload = {
            "window": asdict(active_window) if active_window is not None else None,
            "focused_element": focused_element,
            "backend": active_backend,
            "browser": {
                "available": browser_snapshot.get("available", False),
                "title": browser_snapshot.get("title", ""),
                "url": browser_snapshot.get("url", ""),
                "focused_role": browser_snapshot.get("focused_role", ""),
            },
        }
        fingerprint = hashlib.sha1(
            json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return PrimarySensorSnapshot(
            active_window=active_window,
            focused_element=focused_element,
            event_counts=event_counts,
            active_automation_backend=active_backend,
            fingerprint=fingerprint,
            has_events=any(event_counts.values()),
            metadata={
                "uia": uia_snapshot,
                "browser": browser_snapshot,
            },
        )

    def wait_for_expected_signals(
        self,
        previous_snapshot: PrimarySensorSnapshot,
        expected_signals: list[ExpectedSignal],
        *,
        timeout_ms: int,
        poll_interval_ms: int = 80,
    ) -> dict:
        deadline = time.monotonic() + max(timeout_ms, 1) / 1000.0
        while time.monotonic() < deadline:
            current = self.snapshot()
            matched = match_expected_signals(previous_snapshot, current, expected_signals)
            if matched:
                return {
                    "matched": True,
                    "snapshot": current,
                    "matched_signal": matched.kind.value,
                    "wait_satisfied_by": _wait_source_for_signal(matched, current),
                }
            time.sleep(max(poll_interval_ms, 20) / 1000.0)
        return {
            "matched": False,
            "snapshot": self.snapshot(),
            "matched_signal": "",
            "wait_satisfied_by": "",
        }

    def _active_window(self) -> WindowInfo | None:
        getter = getattr(self.window_manager, "get_foreground_summary", None)
        if callable(getter):
            return getter()
        getter = getattr(self.window_manager, "get_active_window", None)
        if callable(getter):
            return getter()
        return None

    def _uia_snapshot(self) -> dict:
        getter = getattr(self.uia_adapter, "primary_snapshot", None)
        if callable(getter):
            try:
                return getter()
            except Exception:  # noqa: BLE001
                pass
        focused = ""
        focused_getter = getattr(self.uia_adapter, "get_focused_element", None)
        if callable(focused_getter):
            try:
                element = focused_getter()
                if element is not None:
                    focused = ":".join(
                        item for item in [getattr(element, "control_type", ""), getattr(element, "name", "") or getattr(element, "automation_id", "")] if item
                    )
            except Exception:  # noqa: BLE001
                focused = ""
        return {
            "backend": "uia",
            "focused_element": focused,
            "event_counts": {},
            "available": bool(focused),
        }

    def _browser_snapshot(self) -> dict:
        if self.browser_sensor is None:
            return {
                "available": False,
                "backend": "",
                "title": "",
                "url": "",
                "focused_element": "",
                "focused_role": "",
                "event_counts": {},
                "fingerprint": "",
            }
        try:
            return self.browser_sensor.snapshot()
        except Exception:  # noqa: BLE001
            return {
                "available": False,
                "backend": "",
                "title": "",
                "url": "",
                "focused_element": "",
                "focused_role": "",
                "event_counts": {},
                "fingerprint": "",
            }

    def _merge_event_counts(self, *groups: dict[str, int]) -> dict[str, int]:
        merged: dict[str, int] = {}
        for group in groups:
            for key, value in group.items():
                if int(value or 0) <= 0:
                    continue
                merged[key] = merged.get(key, 0) + int(value or 0)
        return merged


def match_expected_signals(
    previous: PrimarySensorSnapshot,
    current: PrimarySensorSnapshot,
    signals: Iterable[ExpectedSignal],
) -> ExpectedSignal | None:
    normalized = list(signals)
    if not normalized:
        if previous.fingerprint != current.fingerprint or current.has_events:
            return ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED)
        return None
    for signal in normalized:
        if _signal_matched(previous, current, signal):
            return signal
    return None


def observation_sensor_snapshot(observation: Observation | None) -> PrimarySensorSnapshot | None:
    if observation is None:
        return None
    payload = observation.raw_ref.get("sensor_snapshot") if isinstance(observation.raw_ref, dict) else None
    if not isinstance(payload, dict):
        return None
    active_payload = payload.get("active_window")
    active_window = None
    if isinstance(active_payload, dict):
        bounds_payload = active_payload.get("bounds")
        bounds = None
        if isinstance(bounds_payload, dict) and {"left", "top", "width", "height"} <= set(bounds_payload):
            from autocruise.domain.models import Bounds

            bounds = Bounds(
                left=int(bounds_payload["left"]),
                top=int(bounds_payload["top"]),
                width=int(bounds_payload["width"]),
                height=int(bounds_payload["height"]),
            )
        active_window = WindowInfo(
            window_id=int(active_payload.get("window_id", 0) or 0),
            title=str(active_payload.get("title", "")),
            class_name=str(active_payload.get("class_name", "")),
            bounds=bounds,
            is_visible=bool(active_payload.get("is_visible", True)),
            process_id=int(active_payload.get("process_id", 0) or 0),
        )
    return PrimarySensorSnapshot(
        active_window=active_window,
        focused_element=str(payload.get("focused_element", "")),
        event_counts={
            str(key): int(value or 0)
            for key, value in (payload.get("event_counts", {}) or {}).items()
        },
        active_automation_backend=str(payload.get("active_automation_backend", "")),
        fingerprint=str(payload.get("fingerprint", "")),
        has_events=bool(payload.get("has_events", False)),
        metadata=dict(payload.get("metadata", {})),
        timestamp=str(payload.get("timestamp", "")),
    )


def sensor_snapshot_to_dict(snapshot: PrimarySensorSnapshot | None) -> dict:
    return asdict(snapshot) if snapshot is not None else {}


def _signal_matched(previous: PrimarySensorSnapshot, current: PrimarySensorSnapshot, signal: ExpectedSignal) -> bool:
    kind = signal.kind
    previous_window = previous.active_window.title if previous.active_window is not None else ""
    current_window = current.active_window.title if current.active_window is not None else ""
    previous_events = previous.event_counts
    current_events = current.event_counts
    fingerprint_changed = previous.fingerprint != current.fingerprint
    browser_changed = _browser_snapshot_changed(previous, current)
    if kind == ExpectedSignalKind.WINDOW_CHANGED:
        return previous_window != current_window or fingerprint_changed
    if kind == ExpectedSignalKind.FOCUS_CHANGED:
        return previous.focused_element != current.focused_element or current_events.get("focus_changed", 0) > 0
    if kind == ExpectedSignalKind.ELEMENT_APPEARED:
        return (
            current_events.get("structure_changed", 0) > 0
            or current_events.get("element_appeared", 0) > 0
            or fingerprint_changed
            or browser_changed
        )
    if kind == ExpectedSignalKind.ELEMENT_DISAPPEARED:
        return (
            current_events.get("structure_changed", 0) > 0
            or current_events.get("element_disappeared", 0) > 0
            or fingerprint_changed
            or browser_changed
        )
    if kind == ExpectedSignalKind.ELEMENT_ENABLED_CHANGED:
        return (
            current_events.get("property_changed", 0) > previous_events.get("property_changed", 0)
            or fingerprint_changed
            or browser_changed
        )
    if kind in {ExpectedSignalKind.TEXT_CHANGED, ExpectedSignalKind.VALUE_CHANGED}:
        return (
            current_events.get("property_changed", 0) > previous_events.get("property_changed", 0)
            or previous.focused_element != current.focused_element
            or fingerprint_changed
            or browser_changed
        )
    if kind == ExpectedSignalKind.DIALOG_OPENED:
        return previous_window != current_window or current_events.get("dialog_opened", 0) > 0 or fingerprint_changed
    if kind == ExpectedSignalKind.BROWSER_NAVIGATION:
        return current_events.get("browser_navigation", 0) > 0 or browser_changed
    if kind == ExpectedSignalKind.DOM_MUTATION:
        return current_events.get("dom_mutation", 0) > 0 or browser_changed
    if kind == ExpectedSignalKind.VISION_CHANGE:
        return False
    return fingerprint_changed


def _wait_source_for_signal(signal: ExpectedSignal, current: PrimarySensorSnapshot) -> str:
    if signal.kind in {
        ExpectedSignalKind.BROWSER_NAVIGATION,
        ExpectedSignalKind.DOM_MUTATION,
    } or current.event_counts.get("browser_navigation", 0) > 0 or current.event_counts.get("dom_mutation", 0) > 0:
        return "browser"
    if signal.kind == ExpectedSignalKind.VISION_CHANGE:
        return "vision"
    if current.event_counts:
        return "uia_event"
    return "sensor_diff"


def _browser_snapshot_changed(previous: PrimarySensorSnapshot, current: PrimarySensorSnapshot) -> bool:
    previous_browser = previous.metadata.get("browser", {}) if isinstance(previous.metadata, dict) else {}
    current_browser = current.metadata.get("browser", {}) if isinstance(current.metadata, dict) else {}
    if not previous_browser and not current_browser:
        return False
    previous_fingerprint = str(previous_browser.get("fingerprint", ""))
    current_fingerprint = str(current_browser.get("fingerprint", ""))
    if previous_fingerprint and current_fingerprint:
        return previous_fingerprint != current_fingerprint
    keys = ("title", "url", "focused_element", "focused_role")
    return any(str(previous_browser.get(key, "")) != str(current_browser.get(key, "")) for key in keys)
