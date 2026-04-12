from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from autocruise.domain.models import Bounds


class AutomationBackend(str, Enum):
    UIA = "uia"
    PLAYWRIGHT = "playwright"
    CDP = "cdp"
    VISION = "vision"


class AutomationOperation(str, Enum):
    INVOKE = "invoke"
    VALUE = "value"
    SELECTION_ITEM = "selection_item"
    EXPAND_COLLAPSE = "expand_collapse"
    TOGGLE = "toggle"
    SCROLL = "scroll"
    TEXT = "text"
    WINDOW = "window"
    LEGACY_IACCESSIBLE = "legacy_iaccessible"
    CLICK = "click"
    INPUT = "input"
    SELECT = "select"


@dataclass(slots=True)
class AutomationElementState:
    backend: AutomationBackend
    element_id: str
    name: str = ""
    automation_id: str = ""
    class_name: str = ""
    control_type: str = ""
    bounds: Bounds | None = None
    is_enabled: bool = True
    has_keyboard_focus: bool = False
    runtime_id: str = ""
    process_id: int = 0
    patterns: list[AutomationOperation] = field(default_factory=list)
    role: str = ""
    value: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AutomationActionDescriptor:
    operation: AutomationOperation
    label: str
    enabled: bool = True
    detail: str = ""


@dataclass(slots=True)
class AutomationExecutionResult:
    success: bool
    details: str
    backend: AutomationBackend
    used_operation: AutomationOperation | None = None


class AutomationAdapter(Protocol):
    backend: AutomationBackend

    def enumerate(self, *, scope: str = "active", limit: int = 50) -> list[AutomationElementState]:
        ...

    def find(self, query: str, *, limit: int = 20) -> list[AutomationElementState]:
        ...

    def element_at(self, x: int, y: int) -> AutomationElementState | None:
        ...

    def focused(self) -> AutomationElementState | None:
        ...

    def state(self, element_id: str) -> AutomationElementState | None:
        ...

    def available_actions(self, element: AutomationElementState) -> list[AutomationActionDescriptor]:
        ...

    def click(self, element: AutomationElementState) -> AutomationExecutionResult:
        ...

    def input_text(self, element: AutomationElementState, text: str) -> AutomationExecutionResult:
        ...

    def select(self, element: AutomationElementState, value: str = "") -> AutomationExecutionResult:
        ...

    def scroll(self, element: AutomationElementState, amount: int) -> AutomationExecutionResult:
        ...


def automation_element_to_prompt_dict(element: AutomationElementState) -> dict[str, Any]:
    bounds = None
    if element.bounds is not None:
        bounds = {
            "left": element.bounds.left,
            "top": element.bounds.top,
            "width": element.bounds.width,
            "height": element.bounds.height,
        }
    return {
        "backend": element.backend.value,
        "element_id": element.element_id,
        "name": element.name,
        "automation_id": element.automation_id,
        "class_name": element.class_name,
        "control_type": element.control_type,
        "bounds": bounds,
        "is_enabled": element.is_enabled,
        "has_keyboard_focus": element.has_keyboard_focus,
        "runtime_id": element.runtime_id,
        "process_id": element.process_id,
        "patterns": [item.value for item in element.patterns],
        "role": element.role,
        "source": element.source,
    }
