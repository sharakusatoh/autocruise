from __future__ import annotations

import atexit
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from autocruise.domain.automation import (
    AutomationActionDescriptor,
    AutomationBackend,
    AutomationElementState,
    AutomationExecutionResult,
    AutomationOperation,
)
from autocruise.domain.models import Bounds


UIA_OPERATION_MAP = {
    "Invoke": AutomationOperation.INVOKE,
    "Value": AutomationOperation.VALUE,
    "SelectionItem": AutomationOperation.SELECTION_ITEM,
    "ExpandCollapse": AutomationOperation.EXPAND_COLLAPSE,
    "Toggle": AutomationOperation.TOGGLE,
    "Scroll": AutomationOperation.SCROLL,
    "Text": AutomationOperation.TEXT,
    "Window": AutomationOperation.WINDOW,
    "LegacyIAccessible": AutomationOperation.LEGACY_IACCESSIBLE,
}

SERVER_OPERATIONS = {
    "primary_snapshot",
    "root",
    "focused",
    "from_point",
    "active_descendants",
    "root_descendants",
    "find",
    "state",
    "actions",
    "click",
    "set_value",
    "select",
    "scroll",
}


class UiaClientLayer:
    backend = AutomationBackend.UIA

    def __init__(self, script_path: Path | None = None) -> None:
        self.script_path = script_path or self._resolve_script_path()
        self.last_error = ""
        self._server_process: subprocess.Popen[str] | None = None
        self._server_stdout_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._server_stderr_buffer: queue.Queue[str] = queue.Queue()
        self._server_stdout_thread: threading.Thread | None = None
        self._server_stderr_thread: threading.Thread | None = None
        self._server_lock = threading.RLock()
        self._next_request_id = 1
        self._server_registered = False

    def close(self) -> None:
        with self._server_lock:
            process = self._server_process
            self._server_process = None
            if process is None:
                return
            try:
                if process.stdin is not None:
                    process.stdin.write(json.dumps({"id": 0, "operation": "shutdown"}) + "\n")
                    process.stdin.flush()
            except Exception:  # noqa: BLE001
                pass
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:  # noqa: BLE001
                try:
                    process.kill()
                except Exception:  # noqa: BLE001
                    pass

    def root(self) -> AutomationElementState | None:
        return self._single("root")

    def focused(self) -> AutomationElementState | None:
        return self._single("focused")

    def element_at(self, x: int, y: int) -> AutomationElementState | None:
        return self._single("from_point", x=x, y=y)

    def enumerate(self, *, scope: str = "active", limit: int = 50) -> list[AutomationElementState]:
        operation = "active_descendants" if scope == "active" else "root_descendants"
        return self._elements(operation, limit=limit)

    def active_window_descendants(self, *, limit: int = 50) -> list[AutomationElementState]:
        return self.enumerate(scope="active", limit=limit)

    def find(self, query: str, *, limit: int = 20) -> list[AutomationElementState]:
        return self._elements("find", query=query, limit=limit)

    def state(self, element_id: str) -> AutomationElementState | None:
        return self._single("state", element_id=element_id)

    def available_actions(self, element: AutomationElementState) -> list[AutomationActionDescriptor]:
        actions = self._action_names(element)
        return [
            AutomationActionDescriptor(operation=operation, label=operation.value, enabled=True)
            for operation in actions
        ]

    def click(self, element: AutomationElementState) -> AutomationExecutionResult:
        return self._execute("click", element, preferred=self._first_click_operation(element))

    def input_text(self, element: AutomationElementState, text: str) -> AutomationExecutionResult:
        return self._execute("set_value", element, text=text, preferred=AutomationOperation.VALUE)

    def select(self, element: AutomationElementState, value: str = "") -> AutomationExecutionResult:
        return self._execute("select", element, text=value, preferred=AutomationOperation.SELECTION_ITEM)

    def scroll(self, element: AutomationElementState, amount: int) -> AutomationExecutionResult:
        return self._execute("scroll", element, amount=amount, preferred=AutomationOperation.SCROLL)

    def primary_snapshot(self) -> dict[str, Any]:
        payload = self._run("primary_snapshot")
        if not isinstance(payload, dict):
            focused = self.focused()
            focused_element = ""
            if focused is not None:
                focused_element = ":".join(part for part in [focused.control_type, focused.name or focused.automation_id] if part)
            return {
                "backend": "uia",
                "focused_element": focused_element,
                "event_counts": {},
                "available": bool(focused),
            }
        return {
            "backend": "uia",
            "focused_element": str(payload.get("focused_element", "")),
            "event_counts": {str(key): int(value or 0) for key, value in dict(payload.get("event_counts", {})).items()},
            "available": bool(payload.get("available", True)),
            "active_window": payload.get("active_window") if isinstance(payload.get("active_window"), dict) else {},
        }

    def _single(self, operation: str, **kwargs) -> AutomationElementState | None:
        elements = self._elements(operation, limit=1, **kwargs)
        return elements[0] if elements else None

    def _elements(self, operation: str, **kwargs) -> list[AutomationElementState]:
        payload = self._run(operation, **kwargs)
        if payload is None:
            return []
        if isinstance(payload, dict) and "elements" in payload:
            payload = payload.get("elements")
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return []
        return [element for item in payload if (element := self._parse_element(item)) is not None]

    def _execute(
        self,
        operation: str,
        element: AutomationElementState,
        *,
        text: str = "",
        amount: int = 0,
        preferred: AutomationOperation | None = None,
    ) -> AutomationExecutionResult:
        payload = self._run(operation, element_id=element.element_id, text=text, amount=amount)
        if not isinstance(payload, dict):
            return AutomationExecutionResult(False, "UIA operation returned no result.", self.backend, preferred)
        used = UIA_OPERATION_MAP.get(str(payload.get("operation", "")), preferred)
        return AutomationExecutionResult(
            bool(payload.get("ok")),
            str(payload.get("message") or ""),
            self.backend,
            used,
        )

    def _run(
        self,
        operation: str,
        *,
        query: str = "",
        limit: int = 40,
        x: int = 0,
        y: int = 0,
        element_id: str = "",
        text: str = "",
        amount: int = 0,
    ) -> Any:
        if operation in SERVER_OPERATIONS:
            payload = self._run_server(
                operation,
                query=query,
                limit=limit,
                x=x,
                y=y,
                element_id=element_id,
                text=text,
                amount=amount,
            )
            if payload is not None:
                return payload
        return self._run_oneshot(
            operation,
            query=query,
            limit=limit,
            x=x,
            y=y,
            element_id=element_id,
            text=text,
            amount=amount,
        )

    def _run_server(self, operation: str, **kwargs) -> Any:
        if not self.script_path.exists():
            self.last_error = f"UIA client script was not found: {self.script_path}"
            return None
        with self._server_lock:
            if not self._ensure_server_started_locked():
                return None
            request_id = self._next_request_id
            self._next_request_id += 1
            payload = {
                "id": request_id,
                "operation": operation,
                "params": kwargs,
            }
            try:
                assert self._server_process is not None
                assert self._server_process.stdin is not None
                self._server_process.stdin.write(json.dumps(payload) + "\n")
                self._server_process.stdin.flush()
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"UIA server write failed: {exc}"
                self.close()
                return None
            return self._wait_for_server_response_locked(request_id, timeout_seconds=4.0)

    def _run_oneshot(
        self,
        operation: str,
        *,
        query: str = "",
        limit: int = 40,
        x: int = 0,
        y: int = 0,
        element_id: str = "",
        text: str = "",
        amount: int = 0,
    ) -> Any:
        if not self.script_path.exists():
            self.last_error = f"UIA client script was not found: {self.script_path}"
            return None
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.script_path),
            "-Operation",
            operation,
            "-Limit",
            str(limit),
        ]
        if query:
            command.extend(["-Query", query])
        if x or y:
            command.extend(["-X", str(x), "-Y", str(y)])
        if element_id:
            command.extend(["-ElementId", element_id])
        if text:
            command.extend(["-Text", text])
        if amount:
            command.extend(["-ScrollAmount", str(amount)])
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                check=False,
                **_hidden_subprocess_kwargs(),
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"UIA client failed to start: {exc}"
            return None
        if result.returncode != 0 or not result.stdout.strip():
            self.last_error = (result.stderr or result.stdout or f"UIA client exited with {result.returncode}").strip()
            return None
        try:
            self.last_error = ""
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.last_error = f"UIA client returned unreadable JSON: {exc}"
            return None

    def _ensure_server_started_locked(self) -> bool:
        if self._server_process is not None and self._server_process.poll() is None:
            return True
        try:
            self._server_process = subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(self.script_path),
                    "-Operation",
                    "server",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_hidden_subprocess_kwargs(),
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"UIA server failed to start: {exc}"
            self._server_process = None
            return False
        self._server_stdout_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._server_stdout_thread.start()
        self._server_stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._server_stderr_thread.start()
        if not self._server_registered:
            atexit.register(self.close)
            self._server_registered = True
        ready = self._wait_for_server_response_locked(0, timeout_seconds=4.0)
        if ready is None:
            self.close()
            return False
        self.last_error = ""
        return True

    def _wait_for_server_response_locked(self, request_id: int, *, timeout_seconds: float) -> Any:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._server_process is None:
                return None
            if self._server_process.poll() is not None:
                self.last_error = self._drain_stderr() or "UIA server exited unexpectedly."
                return None
            remaining = max(deadline - time.monotonic(), 0.05)
            try:
                message = self._server_stdout_queue.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                continue
            if int(message.get("id", -1)) != request_id:
                continue
            if not bool(message.get("ok", True)):
                self.last_error = str(message.get("error") or message.get("message") or "UIA server request failed.")
                return None
            return message.get("result")
        self.last_error = self._drain_stderr() or "Timed out while waiting for UIA server."
        return None

    def _pump_stdout(self) -> None:
        process = self._server_process
        if process is None or process.stdout is None:
            return
        while True:
            line = process.stdout.readline()
            if not line:
                break
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            self._server_stdout_queue.put(payload)

    def _pump_stderr(self) -> None:
        process = self._server_process
        if process is None or process.stderr is None:
            return
        while True:
            line = process.stderr.readline()
            if not line:
                break
            self._server_stderr_buffer.put(line.strip())

    def _drain_stderr(self) -> str:
        messages: list[str] = []
        while True:
            try:
                messages.append(self._server_stderr_buffer.get_nowait())
            except queue.Empty:
                break
        return "\n".join(item for item in messages if item)

    def _resolve_script_path(self) -> Path:
        candidates = [
            Path(__file__).with_name("uia_client.ps1"),
        ]
        frozen_root = getattr(sys, "_MEIPASS", "")
        if frozen_root:
            candidates.append(Path(frozen_root) / "autocruise" / "infrastructure" / "windows" / "uia_client.ps1")
        executable_dir = Path(sys.executable).resolve().parent if getattr(sys, "executable", "") else Path.cwd()
        candidates.extend(
            [
                executable_dir / "autocruise" / "infrastructure" / "windows" / "uia_client.ps1",
                executable_dir / "_internal" / "autocruise" / "infrastructure" / "windows" / "uia_client.ps1",
                Path.cwd() / "src" / "autocruise" / "infrastructure" / "windows" / "uia_client.ps1",
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _parse_element(self, item: Any) -> AutomationElementState | None:
        if not isinstance(item, dict):
            return None
        bounds = self._parse_bounds(item.get("bounding_rectangle") or item)
        patterns = [
            UIA_OPERATION_MAP[name]
            for name in item.get("patterns", [])
            if name in UIA_OPERATION_MAP
        ]
        runtime_id = _runtime_id_to_string(item.get("runtime_id"))
        element_id = str(item.get("element_id") or runtime_id or item.get("automation_id") or item.get("name") or "")
        if not element_id:
            return None
        return AutomationElementState(
            backend=self.backend,
            element_id=element_id,
            name=str(item.get("name") or ""),
            automation_id=str(item.get("automation_id") or ""),
            class_name=str(item.get("class_name") or ""),
            control_type=str(item.get("control_type") or ""),
            bounds=bounds,
            is_enabled=bool(item.get("is_enabled", True)),
            has_keyboard_focus=bool(item.get("has_keyboard_focus", False)),
            runtime_id=runtime_id,
            process_id=int(item.get("process_id") or 0),
            patterns=patterns,
            source="Microsoft UI Automation",
            metadata={"raw": item},
        )

    def _parse_bounds(self, payload: Any) -> Bounds | None:
        if not isinstance(payload, dict):
            return None
        width = int(float(payload.get("width", 0) or 0))
        height = int(float(payload.get("height", 0) or 0))
        if width <= 0 or height <= 0:
            return None
        return Bounds(
            left=int(float(payload.get("left", 0) or 0)),
            top=int(float(payload.get("top", 0) or 0)),
            width=width,
            height=height,
        )

    def _action_names(self, element: AutomationElementState) -> list[AutomationOperation]:
        actions = list(element.patterns)
        if AutomationOperation.INVOKE in actions or AutomationOperation.LEGACY_IACCESSIBLE in actions:
            actions.append(AutomationOperation.CLICK)
        if AutomationOperation.VALUE in actions:
            actions.append(AutomationOperation.INPUT)
        if AutomationOperation.SELECTION_ITEM in actions or AutomationOperation.EXPAND_COLLAPSE in actions:
            actions.append(AutomationOperation.SELECT)
        return actions

    def _first_click_operation(self, element: AutomationElementState) -> AutomationOperation | None:
        for operation in (
            AutomationOperation.INVOKE,
            AutomationOperation.SELECTION_ITEM,
            AutomationOperation.TOGGLE,
            AutomationOperation.EXPAND_COLLAPSE,
            AutomationOperation.LEGACY_IACCESSIBLE,
        ):
            if operation in element.patterns:
                return operation
        return None


def _runtime_id_to_string(value: Any) -> str:
    if isinstance(value, list):
        return ".".join(str(int(item)) for item in value if str(item).strip())
    return str(value or "")


def _hidden_subprocess_kwargs() -> dict:
    kwargs: dict = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    if startupinfo_cls is not None and startf_use_showwindow:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= startf_use_showwindow
        kwargs["startupinfo"] = startupinfo
    return kwargs
