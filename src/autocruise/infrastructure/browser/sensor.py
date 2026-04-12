from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


class BrowserSensorHub:
    def __init__(self, page_provider: Callable[[], Any | None] | None = None) -> None:
        self.page_provider = page_provider or (lambda: None)
        self._listener_bound = False
        self._event_counts = {
            "dialog_opened": 0,
            "browser_navigation": 0,
            "dom_mutation": 0,
        }
        self._last_state: dict[str, Any] | None = None

    def page(self) -> Any | None:
        try:
            return self.page_provider()
        except Exception:  # noqa: BLE001
            return None

    def snapshot(self) -> dict[str, Any]:
        page = self.page()
        if page is None:
            self._listener_bound = False
            self._last_state = None
            self._event_counts = {key: 0 for key in self._event_counts}
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

        self._bind_listeners(page)
        state = self._evaluate_state(page)
        if self._last_state is not None:
            if state.get("title") != self._last_state.get("title") or state.get("url") != self._last_state.get("url"):
                self._event_counts["browser_navigation"] += 1
            if state.get("dom_mutation_counter", 0) > self._last_state.get("dom_mutation_counter", 0):
                self._event_counts["dom_mutation"] += int(
                    state.get("dom_mutation_counter", 0) - self._last_state.get("dom_mutation_counter", 0)
                )
        self._last_state = state
        counts = {key: value for key, value in self._event_counts.items() if value > 0}
        self._event_counts = {key: 0 for key in self._event_counts}
        payload = {
            "available": True,
            "backend": "playwright",
            "title": state.get("title", ""),
            "url": state.get("url", ""),
            "focused_element": state.get("focused_element", ""),
            "focused_role": state.get("focused_role", ""),
            "event_counts": counts,
        }
        payload["fingerprint"] = hashlib.sha1(
            json.dumps(
                {
                    "title": payload["title"],
                    "url": payload["url"],
                    "focused_element": payload["focused_element"],
                    "focused_role": payload["focused_role"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return payload

    def _bind_listeners(self, page: Any) -> None:
        if self._listener_bound:
            return
        on = getattr(page, "on", None)
        if callable(on):
            try:
                on("dialog", lambda *_: self._increment("dialog_opened"))
            except Exception:  # noqa: BLE001
                pass
            try:
                on("popup", lambda *_: self._increment("dialog_opened"))
            except Exception:  # noqa: BLE001
                pass
            try:
                on("framenavigated", lambda *_: self._increment("browser_navigation"))
            except Exception:  # noqa: BLE001
                pass
        self._listener_bound = True

    def _evaluate_state(self, page: Any) -> dict[str, Any]:
        self._ensure_dom_probe(page)
        title = ""
        url = ""
        try:
            getter = getattr(page, "title", None)
            if callable(getter):
                title = str(getter() or "")
        except Exception:  # noqa: BLE001
            title = ""
        try:
            raw_url = getattr(page, "url", "")
            url = str(raw_url() if callable(raw_url) else raw_url or "")
        except Exception:  # noqa: BLE001
            url = ""
        try:
            payload = page.evaluate(_DOM_SENSOR_JS)
            if isinstance(payload, dict):
                return {
                    "title": title or str(payload.get("title", "")),
                    "url": url or str(payload.get("url", "")),
                    "focused_element": str(payload.get("focused_element", "")),
                    "focused_role": str(payload.get("focused_role", "")),
                    "dom_mutation_counter": int(payload.get("dom_mutation_counter", 0) or 0),
                }
        except Exception:  # noqa: BLE001
            pass
        return {
            "title": title,
            "url": url,
            "focused_element": "",
            "focused_role": "",
            "dom_mutation_counter": 0,
        }

    def _ensure_dom_probe(self, page: Any) -> None:
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return
        try:
            evaluate(_DOM_SENSOR_BOOTSTRAP_JS)
        except Exception:  # noqa: BLE001
            return

    def _increment(self, key: str) -> None:
        self._event_counts[key] = self._event_counts.get(key, 0) + 1


_DOM_SENSOR_BOOTSTRAP_JS = """
(() => {
  if (window.__autocruiseSensorInstalled) {
    return true;
  }
  const state = (window.__autocruiseSensorState = window.__autocruiseSensorState || {
    domMutationCounter: 0,
    focusCounter: 0,
  });
  const root = document.documentElement || document.body;
  if (root && typeof MutationObserver !== "undefined") {
    const observer = new MutationObserver(() => {
      state.domMutationCounter += 1;
    });
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
  }
  document.addEventListener(
    "focusin",
    () => {
      state.focusCounter += 1;
    },
    true,
  );
  window.addEventListener("hashchange", () => {
    state.domMutationCounter += 1;
  });
  window.addEventListener("popstate", () => {
    state.domMutationCounter += 1;
  });
  window.__autocruiseSensorInstalled = true;
  return true;
})()
"""

_DOM_SENSOR_JS = """
(() => {
  const state = window.__autocruiseSensorState || { domMutationCounter: 0, focusCounter: 0 };
  const active = document.activeElement;
  const label =
    active?.getAttribute?.("aria-label") ||
    active?.getAttribute?.("title") ||
    active?.id ||
    active?.innerText?.trim?.()?.slice?.(0, 80) ||
    active?.value ||
    "";
  return {
    title: document.title || "",
    url: location.href || "",
    focused_element: `${active?.tagName || ""}:${label}`,
    focused_role: active?.getAttribute?.("role") || active?.tagName || "",
    dom_mutation_counter: state.domMutationCounter || 0,
  };
})()
"""
