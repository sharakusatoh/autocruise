from __future__ import annotations

from autocruise.domain.automation import AutomationActionDescriptor, AutomationElementState, AutomationExecutionResult
from autocruise.domain.models import DetectedElement, TargetRef
from autocruise.infrastructure.windows.uia_client import UiaClientLayer


class UIAAdapter:
    def __init__(self, client: UiaClientLayer | None = None) -> None:
        self.client = client or UiaClientLayer()
        self.backend = self.client.backend

    def close(self) -> None:
        closer = getattr(self.client, "close", None)
        if callable(closer):
            closer()

    def root_element(self) -> AutomationElementState | None:
        return self.client.root()

    def element_at(self, x: int, y: int) -> AutomationElementState | None:
        return self.client.element_at(x, y)

    def enumerate(self, *, scope: str = "active", limit: int = 50) -> list[AutomationElementState]:
        return self.client.enumerate(scope=scope, limit=limit)

    def find(self, query: str, *, limit: int = 20) -> list[AutomationElementState]:
        return self.client.find(query, limit=limit)

    def state(self, element_id: str) -> AutomationElementState | None:
        return self.client.state(element_id)

    def focused(self) -> AutomationElementState | None:
        return self.client.focused()

    def primary_snapshot(self) -> dict:
        getter = getattr(self.client, "primary_snapshot", None)
        if callable(getter):
            return getter()
        focused = self.focused()
        focused_identity = ""
        if focused is not None:
            focused_identity = ":".join(part for part in [focused.control_type, focused.name or focused.automation_id] if part)
        return {
            "backend": "uia",
            "focused_element": focused_identity,
            "event_counts": {},
            "available": focused is not None,
        }

    def available_actions(self, element: AutomationElementState) -> list[AutomationActionDescriptor]:
        return self.client.available_actions(element)

    def click(self, element: AutomationElementState) -> AutomationExecutionResult:
        return self.client.click(element)

    def input_text(self, element: AutomationElementState, text: str) -> AutomationExecutionResult:
        return self.client.input_text(element, text)

    def select(self, element: AutomationElementState, value: str = "") -> AutomationExecutionResult:
        return self.client.select(element, value)

    def scroll(self, element: AutomationElementState, amount: int) -> AutomationExecutionResult:
        return self.client.scroll(element, amount)

    def resolve_target(self, target: TargetRef) -> AutomationElementState | None:
        probes = [target.automation_id, target.name, target.window_title, target.control_type.split(".")[-1]]
        for probe in [item for item in probes if item]:
            for element in self.find(probe, limit=20):
                if self._target_matches(target, element):
                    return element
        return None

    def find_elements(self, query: str, limit: int = 40) -> list[DetectedElement]:
        return [self._to_detected(element) for element in self.find(query, limit=limit)]

    def get_focused_element(self) -> DetectedElement | None:
        focused = self.focused()
        return self._to_detected(focused) if focused is not None else None

    def get_automation_elements(self, query: str = "", limit: int = 40) -> list[AutomationElementState]:
        return self.find(query, limit=limit) if query else self.enumerate(scope="active", limit=limit)

    def _target_matches(self, target: TargetRef, element: AutomationElementState) -> bool:
        if target.automation_id and target.automation_id == element.automation_id:
            return True
        if target.name and target.name == element.name:
            return True
        if target.window_title and target.window_title in element.name:
            return True
        if target.control_type and target.control_type == element.control_type:
            return True
        if target.bounds is not None and element.bounds is not None:
            return (
                abs(target.bounds.left - element.bounds.left) <= 8
                and abs(target.bounds.top - element.bounds.top) <= 8
                and abs(target.bounds.width - element.bounds.width) <= 12
                and abs(target.bounds.height - element.bounds.height) <= 12
            )
        return False

    def _to_detected(self, element: AutomationElementState) -> DetectedElement:
        confidence = 0.84 if element.patterns else 0.72
        return DetectedElement(
            window_id=None,
            name=element.name,
            automation_id=element.automation_id,
            control_type=element.control_type,
            bounds=element.bounds,
            confidence=confidence,
        )
