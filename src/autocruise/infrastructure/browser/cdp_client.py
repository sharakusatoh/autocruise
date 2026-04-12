from __future__ import annotations

from typing import Any

from autocruise.domain.automation import AutomationBackend, AutomationExecutionResult, AutomationOperation


class CdpClientAdapter:
    backend = AutomationBackend.CDP

    def __init__(self, page: Any | None = None, session: Any | None = None) -> None:
        self._page_provider = page if callable(page) else None
        self._page = None if callable(page) else page
        self._session = session

    @property
    def page(self) -> Any | None:
        if self._page_provider is not None:
            try:
                return self._page_provider()
            except Exception:  # noqa: BLE001
                return None
        return self._page

    def available(self) -> bool:
        return self.page is not None or self._session is not None

    def session(self):
        if self._session is not None:
            return self._session
        if self.page is None:
            return None
        context = getattr(self.page, "context", None)
        factory = getattr(context, "new_cdp_session", None)
        if not callable(factory):
            return None
        self._session = factory(self.page)
        return self._session

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.session()
        if session is None:
            return {}
        return session.send(method, params or {})

    def accessibility_snapshot(self) -> dict[str, Any]:
        return self.send("Accessibility.getFullAXTree", {})

    def dom_snapshot(self) -> dict[str, Any]:
        document = self.send("DOM.getDocument", {"depth": 2, "pierce": True})
        return document if isinstance(document, dict) else {}

    def click_xy(self, x: int, y: int) -> AutomationExecutionResult:
        if self.session() is None:
            return AutomationExecutionResult(False, "CDP session is unavailable.", self.backend, AutomationOperation.CLICK)
        self.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        self.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
        return AutomationExecutionResult(True, f"Clicked at {x},{y} via CDP.", self.backend, AutomationOperation.CLICK)

    def type_text(self, text: str) -> AutomationExecutionResult:
        if self.session() is None:
            return AutomationExecutionResult(False, "CDP session is unavailable.", self.backend, AutomationOperation.INPUT)
        self.send("Input.insertText", {"text": text})
        return AutomationExecutionResult(True, "Inserted text via CDP.", self.backend, AutomationOperation.INPUT)

    def scroll_xy(self, x: int, y: int, delta_y: int) -> AutomationExecutionResult:
        if self.session() is None:
            return AutomationExecutionResult(False, "CDP session is unavailable.", self.backend, AutomationOperation.SCROLL)
        self.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": 0,
                "deltaY": delta_y,
            },
        )
        return AutomationExecutionResult(True, "Scrolled via CDP.", self.backend, AutomationOperation.SCROLL)
