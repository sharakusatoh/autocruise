from __future__ import annotations

import re
import uuid
from typing import Any

from autocruise.domain.automation import (
    AutomationActionDescriptor,
    AutomationBackend,
    AutomationElementState,
    AutomationExecutionResult,
    AutomationOperation,
)
from autocruise.domain.models import Bounds
from autocruise.infrastructure.browser.cdp_client import CdpClientAdapter


ROLE_PRIORITY = (
    "button",
    "link",
    "textbox",
    "combobox",
    "checkbox",
    "radio",
    "tab",
    "menuitem",
    "option",
    "heading",
    "img",
)


class PlaywrightAdapter:
    backend = AutomationBackend.PLAYWRIGHT

    def __init__(self, page: Any | None = None, cdp: CdpClientAdapter | None = None) -> None:
        self._page_provider = page if callable(page) else None
        self._page = None if callable(page) else page
        self.cdp = cdp or CdpClientAdapter(page=(lambda: self.page))
        self._registry: dict[str, Any] = {}

    @property
    def page(self) -> Any | None:
        if self._page_provider is not None:
            try:
                return self._page_provider()
            except Exception:  # noqa: BLE001
                return None
        return self._page

    def enumerate(self, *, scope: str = "active", limit: int = 50) -> list[AutomationElementState]:
        page = self.page
        if page is None:
            return []
        try:
            locators = [page.get_by_role(role).first() for role in ROLE_PRIORITY[: min(limit, len(ROLE_PRIORITY))]]
        except Exception:  # noqa: BLE001
            return []
        return [state for locator in locators if (state := self._state_from_locator(locator, f"role:{scope}")) is not None][:limit]

    def find(self, query: str, *, limit: int = 20) -> list[AutomationElementState]:
        if self.page is None or not query.strip():
            return []
        locators = self._locator_candidates(query)
        results: list[AutomationElementState] = []
        for strategy, locator in locators:
            state = self._state_from_locator(locator.first(), strategy)
            if state is not None:
                results.append(state)
            if len(results) >= limit:
                break
        return results

    def element_at(self, x: int, y: int) -> AutomationElementState | None:
        return None

    def focused(self) -> AutomationElementState | None:
        page = self.page
        if page is None:
            return None
        try:
            locator = page.locator(":focus")
        except Exception:  # noqa: BLE001
            return None
        return self._state_from_locator(locator, "css:focus")

    def state(self, element_id: str) -> AutomationElementState | None:
        locator = self._registry.get(element_id)
        if locator is None:
            return None
        return self._state_from_locator(locator, "registry", element_id=element_id)

    def available_actions(self, element: AutomationElementState) -> list[AutomationActionDescriptor]:
        role = (element.role or element.control_type).lower()
        actions = [AutomationActionDescriptor(AutomationOperation.CLICK, "Click")]
        if role in {"textbox", "searchbox", "combobox"}:
            actions.append(AutomationActionDescriptor(AutomationOperation.INPUT, "Input text"))
        if role in {"combobox", "listbox", "option", "radio", "checkbox"}:
            actions.append(AutomationActionDescriptor(AutomationOperation.SELECT, "Select"))
        actions.append(AutomationActionDescriptor(AutomationOperation.SCROLL, "Scroll"))
        return actions

    def click(self, element: AutomationElementState) -> AutomationExecutionResult:
        locator = self._registry.get(element.element_id)
        if locator is None:
            return AutomationExecutionResult(False, "Playwright locator is not registered.", self.backend, AutomationOperation.CLICK)
        try:
            locator.click()
            return AutomationExecutionResult(True, "Clicked via Playwright locator.", self.backend, AutomationOperation.CLICK)
        except Exception as exc:  # noqa: BLE001
            point = _center(element.bounds)
            if point is None:
                return AutomationExecutionResult(False, str(exc), self.backend, AutomationOperation.CLICK)
            return self.cdp.click_xy(*point)

    def input_text(self, element: AutomationElementState, text: str) -> AutomationExecutionResult:
        locator = self._registry.get(element.element_id)
        if locator is None:
            return AutomationExecutionResult(False, "Playwright locator is not registered.", self.backend, AutomationOperation.INPUT)
        try:
            fill = getattr(locator, "fill", None)
            if callable(fill):
                fill(text)
            else:
                locator.click()
                locator.type(text)
            return AutomationExecutionResult(True, "Filled via Playwright locator.", self.backend, AutomationOperation.INPUT)
        except Exception:
            return self.cdp.type_text(text)

    def select(self, element: AutomationElementState, value: str = "") -> AutomationExecutionResult:
        locator = self._registry.get(element.element_id)
        if locator is None:
            return AutomationExecutionResult(False, "Playwright locator is not registered.", self.backend, AutomationOperation.SELECT)
        try:
            if value:
                locator.select_option(value)
            else:
                locator.click()
            return AutomationExecutionResult(True, "Selected via Playwright locator.", self.backend, AutomationOperation.SELECT)
        except Exception as exc:  # noqa: BLE001
            return AutomationExecutionResult(False, str(exc), self.backend, AutomationOperation.SELECT)

    def scroll(self, element: AutomationElementState, amount: int) -> AutomationExecutionResult:
        locator = self._registry.get(element.element_id)
        try:
            if locator is not None:
                locator.scroll_into_view_if_needed()
                point = _center(element.bounds)
                if point is not None:
                    return self.cdp.scroll_xy(point[0], point[1], amount)
            page = self.page
            if page is not None:
                page.mouse.wheel(0, amount)
                return AutomationExecutionResult(True, "Scrolled via Playwright mouse.", self.backend, AutomationOperation.SCROLL)
        except Exception as exc:  # noqa: BLE001
            return AutomationExecutionResult(False, str(exc), self.backend, AutomationOperation.SCROLL)
        return AutomationExecutionResult(False, "No Playwright page is available.", self.backend, AutomationOperation.SCROLL)

    def _locator_candidates(self, query: str) -> list[tuple[str, Any]]:
        page = self.page
        if page is None:
            return []
        name_pattern = re.compile(re.escape(query), re.IGNORECASE)
        candidates: list[tuple[str, Any]] = []
        for role in ROLE_PRIORITY:
            try:
                candidates.append((f"role:{role}", page.get_by_role(role, name=name_pattern)))
            except Exception:  # noqa: BLE001
                continue
        for label, method_name in (
            ("label", "get_by_label"),
            ("text", "get_by_text"),
            ("placeholder", "get_by_placeholder"),
            ("alt_text", "get_by_alt_text"),
            ("title", "get_by_title"),
        ):
            method = getattr(page, method_name, None)
            if not callable(method):
                continue
            try:
                candidates.append((label, method(name_pattern)))
            except Exception:  # noqa: BLE001
                try:
                    candidates.append((label, method(query)))
                except Exception:  # noqa: BLE001
                    continue
        return candidates

    def _state_from_locator(self, locator: Any, source: str, element_id: str = "") -> AutomationElementState | None:
        try:
            if hasattr(locator, "count") and locator.count() <= 0:
                return None
        except Exception:  # noqa: BLE001
            return None
        try:
            box = locator.bounding_box()
        except Exception:  # noqa: BLE001
            box = None
        bounds = None
        if isinstance(box, dict) and box.get("width", 0) and box.get("height", 0):
            bounds = Bounds(
                left=int(box.get("x", 0)),
                top=int(box.get("y", 0)),
                width=int(box.get("width", 0)),
                height=int(box.get("height", 0)),
            )
        generated_id = element_id or f"pw-{uuid.uuid4().hex[:12]}"
        self._registry[generated_id] = locator
        role = _attribute(locator, "role") or source.split(":", 1)[-1]
        name = _attribute(locator, "aria-label") or _text(locator)
        return AutomationElementState(
            backend=self.backend,
            element_id=generated_id,
            name=name,
            automation_id=_attribute(locator, "id"),
            class_name=_attribute(locator, "class"),
            control_type=role,
            bounds=bounds,
            is_enabled=_is_enabled(locator),
            has_keyboard_focus=False,
            patterns=self._patterns_for_role(role),
            role=role,
            source=f"Playwright {source}",
        )

    def _patterns_for_role(self, role: str) -> list[AutomationOperation]:
        normalized = (role or "").lower()
        patterns = [AutomationOperation.CLICK]
        if normalized in {"textbox", "searchbox", "combobox"}:
            patterns.append(AutomationOperation.VALUE)
        if normalized in {"combobox", "option", "radio", "checkbox"}:
            patterns.append(AutomationOperation.SELECTION_ITEM)
        patterns.append(AutomationOperation.SCROLL)
        return patterns


def _attribute(locator: Any, name: str) -> str:
    try:
        value = locator.get_attribute(name)
        return str(value or "")
    except Exception:  # noqa: BLE001
        return ""


def _text(locator: Any) -> str:
    try:
        return str(locator.inner_text(timeout=250) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _is_enabled(locator: Any) -> bool:
    try:
        return bool(locator.is_enabled())
    except Exception:  # noqa: BLE001
        return True


def _center(bounds: Bounds | None) -> tuple[int, int] | None:
    if bounds is None:
        return None
    return bounds.left + bounds.width // 2, bounds.top + bounds.height // 2
