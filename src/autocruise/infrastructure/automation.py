from __future__ import annotations

from autocruise.domain.automation import (
    AutomationActionDescriptor,
    AutomationAdapter,
    AutomationBackend,
    AutomationElementState,
    AutomationExecutionResult,
    AutomationOperation,
)
from autocruise.domain.models import TargetRef


class AutomationRouter:
    def __init__(self, adapters: list[AutomationAdapter] | None = None) -> None:
        self.adapters = adapters or []

    def enumerate(self, *, scope: str = "active", limit: int = 50) -> list[AutomationElementState]:
        return self._first_elements(lambda adapter: adapter.enumerate(scope=scope, limit=limit))

    def find(self, query: str, *, limit: int = 20) -> list[AutomationElementState]:
        return self._first_elements(lambda adapter: adapter.find(query, limit=limit))

    def element_at(self, x: int, y: int) -> AutomationElementState | None:
        return self._first_state(lambda adapter: adapter.element_at(x, y))

    def focused(self) -> AutomationElementState | None:
        return self._first_state(lambda adapter: adapter.focused())

    def state(self, element_id: str) -> AutomationElementState | None:
        return self._first_state(lambda adapter: adapter.state(element_id))

    def available_actions(self, element: AutomationElementState) -> list[AutomationActionDescriptor]:
        for adapter in self.adapters:
            if adapter.backend == element.backend:
                try:
                    return adapter.available_actions(element)
                except Exception:  # noqa: BLE001
                    return []
        return []

    def click(self, element: AutomationElementState) -> AutomationExecutionResult:
        return self._execute(element, lambda adapter: adapter.click(element))

    def input_text(self, element: AutomationElementState, text: str) -> AutomationExecutionResult:
        return self._execute(element, lambda adapter: adapter.input_text(element, text))

    def select(self, element: AutomationElementState, value: str = "") -> AutomationExecutionResult:
        return self._execute(element, lambda adapter: adapter.select(element, value))

    def scroll(self, element: AutomationElementState, amount: int) -> AutomationExecutionResult:
        return self._execute(element, lambda adapter: adapter.scroll(element, amount))

    def should_use_vision_fallback(self, elements: list[AutomationElementState]) -> bool:
        return not elements

    def resolve_target(self, target: TargetRef) -> AutomationElementState | None:
        probes = [
            *[item for item in target.search_terms if item],
            target.automation_id,
            target.name,
            target.window_title,
            target.control_type.split(".")[-1],
        ]
        adapters = self._ordered_adapters(target.backend_hint)
        for adapter in adapters:
            resolver = getattr(adapter, "resolve_target", None)
            if callable(resolver):
                try:
                    element = resolver(target)
                except Exception:  # noqa: BLE001
                    element = None
                if element is not None:
                    return element
            for probe in [item for item in probes if item]:
                try:
                    candidates = adapter.find(probe, limit=20)
                except Exception:  # noqa: BLE001
                    continue
                for element in candidates:
                    if self._target_matches(target, element):
                        return element
        return None

    def _ordered_adapters(self, backend_hint: str) -> list[AutomationAdapter]:
        normalized = str(backend_hint or "").strip().lower()
        if not normalized:
            return list(self.adapters)
        preferred = [adapter for adapter in self.adapters if adapter.backend.value == normalized]
        remainder = [adapter for adapter in self.adapters if adapter.backend.value != normalized]
        return [*preferred, *remainder]

    def _first_elements(self, callback) -> list[AutomationElementState]:
        for adapter in self.adapters:
            try:
                elements = callback(adapter)
            except Exception:  # noqa: BLE001
                continue
            if elements:
                return elements
        return []

    def _first_state(self, callback) -> AutomationElementState | None:
        for adapter in self.adapters:
            try:
                state = callback(adapter)
            except Exception:  # noqa: BLE001
                continue
            if state is not None:
                return state
        return None

    def _execute(self, element: AutomationElementState, callback) -> AutomationExecutionResult:
        for adapter in self.adapters:
            if adapter.backend != element.backend:
                continue
            try:
                return callback(adapter)
            except Exception as exc:  # noqa: BLE001
                return AutomationExecutionResult(False, str(exc), adapter.backend)
        return AutomationExecutionResult(
            False,
            f"No automation adapter is registered for {element.backend.value}",
            element.backend if element.backend != AutomationBackend.VISION else AutomationBackend.VISION,
            AutomationOperation.CLICK,
        )

    def _target_matches(self, target: TargetRef, element: AutomationElementState) -> bool:
        if target.automation_id and target.automation_id == element.automation_id:
            return True
        if target.name and target.name == element.name:
            return True
        if target.search_terms:
            haystack = " ".join(
                [element.name, element.automation_id, element.class_name, element.control_type, element.role]
            ).casefold()
            if any(str(term or "").strip().casefold() in haystack for term in target.search_terms):
                return True
        if target.window_title and target.window_title and target.window_title in element.name:
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
