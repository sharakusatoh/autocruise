from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autocruise.version import APP_TITLE, APP_VERSION


APP_SERVER_HELP_MARKERS = (
    "Usage: codex app-server",
    "Run the app server",
)
DEFAULT_CLIENT_NAME = "autocruise_ce"
DEFAULT_CLIENT_TITLE = APP_TITLE
DEFAULT_CLIENT_VERSION = APP_VERSION
DEFAULT_STARTUP_TIMEOUT_SECONDS = 45
DEFAULT_REQUEST_TIMEOUT_SECONDS = 45
DEFAULT_TURN_TIMEOUT_SECONDS = 180


class CodexAppServerError(RuntimeError):
    pass


class CodexAppServerUnavailable(CodexAppServerError):
    pass


@dataclass(slots=True)
class CodexAppServerCommand:
    command: str
    label: str


@dataclass(slots=True)
class CodexAccountState:
    auth_mode: str | None
    requires_openai_auth: bool
    email: str = ""
    plan_type: str = ""
    command_label: str = ""

    @property
    def is_chatgpt_ready(self) -> bool:
        return self.auth_mode == "chatgpt"


@dataclass(slots=True)
class CodexModelProfile:
    model_id: str
    display_name: str = ""
    default_reasoning_effort: str = "medium"
    supported_reasoning_efforts: list[str] = field(default_factory=list)
    supported_service_tiers: list[str] = field(default_factory=list)
    input_modalities: list[str] = field(default_factory=list)
    is_default: bool = False


def read_cached_auth_mode() -> str | None:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    auth_path = codex_home / "auth.json"
    if not auth_path.exists():
        return None
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("auth_mode")
    return str(value) if isinstance(value, str) and value else None


class CodexAppServerConnection:
    _cached_command: CodexAppServerCommand | None = None
    _command_lock = threading.Lock()

    def __init__(
        self,
        workspace_root: Path,
        *,
        client_name: str = DEFAULT_CLIENT_NAME,
        client_title: str = DEFAULT_CLIENT_TITLE,
        client_version: str = DEFAULT_CLIENT_VERSION,
    ) -> None:
        self.workspace_root = workspace_root
        self.client_name = client_name
        self.client_title = client_title
        self.client_version = client_version
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_buffer: deque[str] = deque(maxlen=120)
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._io_lock = threading.RLock()
        self._next_request_id = 1
        self._initialized = False
        self._last_auth_mode: str | None = None
        self._last_login_result: dict[str, Any] | None = None
        self._cancel_event = threading.Event()

    def close(self) -> None:
        self._cancel_event.set()
        with self._io_lock:
            process = self._process
            self._process = None
            self._initialized = False
            while not self._stdout_queue.empty():
                try:
                    self._stdout_queue.get_nowait()
                except queue.Empty:
                    break
            if process is None:
                return
            _terminate_process_tree(process)

    def cancel_active_turn(self) -> None:
        self._cancel_event.set()
        process = self._process
        if process is not None:
            _terminate_process_tree(process)

    def is_cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def ensure_available(self) -> CodexAppServerCommand:
        return self._resolve_command()

    def read_account(self, refresh_token: bool = False) -> CodexAccountState:
        result = self.request(
            "account/read",
            {"refreshToken": bool(refresh_token)},
            timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        account = result.get("account") or {}
        auth_mode = None
        email = ""
        plan_type = ""
        if isinstance(account, dict):
            account_type = account.get("type")
            auth_mode = str(account_type) if isinstance(account_type, str) else None
            email = str(account.get("email", "")) if isinstance(account.get("email"), str) else ""
            plan_type = str(account.get("planType", "")) if isinstance(account.get("planType"), str) else ""
        if auth_mode:
            self._last_auth_mode = auth_mode
        return CodexAccountState(
            auth_mode=auth_mode,
            requires_openai_auth=bool(result.get("requiresOpenaiAuth", True)),
            email=email,
            plan_type=plan_type,
            command_label=self._resolve_command().label,
        )

    def start_chatgpt_login(self) -> dict[str, str]:
        result = self.request(
            "account/login/start",
            {"type": "chatgpt"},
            timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        auth_url = str(result.get("authUrl", "")).strip()
        login_id = str(result.get("loginId", "")).strip()
        if not auth_url or not login_id:
            raise CodexAppServerError("Codex did not return a ChatGPT login URL.")
        return {"auth_url": auth_url, "login_id": login_id}

    def cancel_login(self, login_id: str) -> None:
        if not login_id:
            return
        self.request(
            "account/login/cancel",
            {"loginId": login_id},
            timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )

    def logout(self) -> None:
        self.request("account/logout", {}, timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS)
        self._last_auth_mode = None

    def list_models(self) -> list[CodexModelProfile]:
        result = self.request(
            "model/list",
            {},
            timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        payload = result.get("data") or result.get("models")
        if not isinstance(payload, list):
            return []

        models: list[CodexModelProfile] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id", "")).strip()
            if not model_id:
                continue
            efforts: list[str] = []
            for value in item.get("supportedReasoningEfforts", []):
                if isinstance(value, dict):
                    effort_value = str(value.get("reasoningEffort", "")).strip().lower()
                else:
                    effort_value = str(value).strip().lower()
                if effort_value in {"none", "minimal", "low", "medium", "high", "xhigh"} and effort_value not in efforts:
                    efforts.append(effort_value)
            default_effort = str(item.get("defaultReasoningEffort", "")).strip().lower() or "medium"
            if default_effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
                default_effort = "medium"
            if default_effort not in efforts:
                efforts = [*efforts, default_effort] if efforts else [default_effort]
            modalities = [str(value).strip().lower() for value in item.get("inputModalities", []) if str(value).strip()]
            service_tiers = ["auto"]
            for value in item.get("additionalSpeedTiers", []):
                tier = str(value).strip().lower()
                if tier and tier not in service_tiers:
                    service_tiers.append(tier)
            models.append(
                CodexModelProfile(
                    model_id=model_id,
                    display_name=str(item.get("displayName", "")).strip() or str(item.get("name", "")).strip() or model_id,
                    default_reasoning_effort=default_effort,
                    supported_reasoning_efforts=efforts,
                    supported_service_tiers=service_tiers,
                    input_modalities=modalities,
                    is_default=bool(item.get("isDefault", False)),
                )
            )
        return models

    def start_thread(self, model: str, cwd: Path) -> str:
        self._cancel_event.clear()
        result = self.request(
            "thread/start",
            {
                "model": model,
                "cwd": str(cwd),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "serviceName": DEFAULT_CLIENT_NAME,
            },
            timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        thread = result.get("thread") or {}
        thread_id = str(thread.get("id", "")).strip()
        if not thread_id:
            raise CodexAppServerError("Codex did not return a thread id.")
        return thread_id

    def unsubscribe_thread(self, thread_id: str) -> None:
        if not thread_id or self._cancel_event.is_set():
            return
        try:
            self.request(
                "thread/unsubscribe",
                {"threadId": thread_id},
                timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            )
        except CodexAppServerError:
            return

    def run_turn(
        self,
        thread_id: str,
        *,
        input_items: list[dict[str, Any]],
        model: str,
        cwd: Path,
        effort: str = "high",
        service_tier: str = "auto",
        timeout_seconds: int = DEFAULT_TURN_TIMEOUT_SECONDS,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        self._cancel_event.clear()
        with self._io_lock:
            self._ensure_started_locked()
            request_id = self._next_request_id
            self._next_request_id += 1
            params: dict[str, Any] = {
                "threadId": thread_id,
                "input": input_items,
                "model": model,
                "cwd": str(cwd),
                "effort": effort,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly", "access": {"type": "fullAccess"}},
            }
            normalized_service_tier = (service_tier or "").strip().lower()
            if normalized_service_tier and normalized_service_tier != "auto":
                params["serviceTier"] = normalized_service_tier
            if output_schema:
                params["outputSchema"] = output_schema
            self._send_locked({"method": "turn/start", "id": request_id, "params": params})
            response = self._wait_for_response_locked(request_id, timeout_seconds=timeout_seconds)
            turn = response.get("turn") or {}
            turn_id = str(turn.get("id", "")).strip()
            if not turn_id:
                raise CodexAppServerError("Codex did not return a turn id.")
            return self._wait_for_turn_completion_locked(turn_id, timeout_seconds=timeout_seconds)

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        if method != "thread/unsubscribe":
            self._cancel_event.clear()
        with self._io_lock:
            self._ensure_started_locked()
            request_id = self._next_request_id
            self._next_request_id += 1
            self._send_locked({"method": method, "id": request_id, "params": params or {}})
            return self._wait_for_response_locked(request_id, timeout_seconds=timeout_seconds)

    def _wait_for_turn_completion_locked(self, turn_id: str, *, timeout_seconds: int) -> str:
        deadline = time.monotonic() + timeout_seconds
        final_text = ""
        while True:
            remaining = max(deadline - time.monotonic(), 0.1)
            message = self._read_message_locked(timeout_seconds=remaining)
            method = message.get("method")
            if method == "item/agentMessage/delta":
                params = message.get("params", {})
                if str(params.get("turnId", "")) == turn_id:
                    final_text += str(params.get("delta", ""))
            elif method == "item/completed":
                params = message.get("params", {})
                item = params.get("item", {})
                if str(params.get("turnId", "")) == turn_id and item.get("type") == "agentMessage":
                    candidate = str(item.get("text", "")).strip()
                    if candidate:
                        final_text = candidate
            elif method == "turn/completed":
                turn = message.get("params", {}).get("turn", {})
                if str(turn.get("id", "")) != turn_id:
                    continue
                status = str(turn.get("status", ""))
                if status != "completed":
                    error = turn.get("error") or {}
                    detail = str(error.get("message", "")).strip() or f"Codex turn ended with status: {status}"
                    raise CodexAppServerError(detail)
                if final_text.strip():
                    return final_text.strip()
                items = turn.get("items", []) if isinstance(turn, dict) else []
                for item in items:
                    if isinstance(item, dict) and item.get("type") == "agentMessage":
                        candidate = str(item.get("text", "")).strip()
                        if candidate:
                            return candidate
                raise CodexAppServerError("Codex completed the turn without returning text.")

    def _wait_for_response_locked(self, request_id: int, *, timeout_seconds: int) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = max(deadline - time.monotonic(), 0.1)
            message = self._read_message_locked(timeout_seconds=remaining)
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    error = message.get("error") or {}
                    detail = str(error.get("message", "")).strip() or f"Codex request {request_id} failed."
                    raise CodexAppServerError(detail)
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            self._handle_aux_message_locked(message)

    def _read_message_locked(self, *, timeout_seconds: float) -> dict[str, Any]:
        if timeout_seconds <= 0:
            raise CodexAppServerError("Timed out while waiting for Codex.")
        deadline = time.monotonic() + timeout_seconds
        while True:
            if self._cancel_event.is_set():
                raise CodexAppServerError("Codex turn was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexAppServerError(self._timeout_message())
            try:
                return self._stdout_queue.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                continue

    def _handle_aux_message_locked(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if not isinstance(method, str):
            return
        if "id" in message:
            self._respond_to_server_request_locked(message)
            return
        params = message.get("params") or {}
        if method == "account/updated":
            auth_mode = params.get("authMode")
            self._last_auth_mode = str(auth_mode) if isinstance(auth_mode, str) else None
        elif method == "account/login/completed":
            self._last_login_result = params if isinstance(params, dict) else {}

    def _respond_to_server_request_locked(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id is None:
            return
        method = str(message.get("method", ""))
        if method.startswith("item/") and method.endswith("/requestApproval"):
            self._send_locked({"id": request_id, "result": "decline"})
            return
        self._send_locked(
            {
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"{method} is not supported by AutoCruise CE.",
                },
            }
        )

    def _ensure_started_locked(self) -> None:
        if self._process is not None and self._process.poll() is None and self._initialized:
            return
        self.close()
        self._cancel_event.clear()
        spec = self._resolve_command()
        self._process = subprocess.Popen(
            self._launch_args(spec.command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(self.workspace_root),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if self._process.stdin is None or self._process.stdout is None or self._process.stderr is None:
            self.close()
            raise CodexAppServerUnavailable("Codex app-server could not open stdio pipes.")
        self._stdout_thread = threading.Thread(target=self._stdout_reader, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_reader, daemon=True)
        self._stderr_thread.start()
        self._bootstrap_locked()

    def _bootstrap_locked(self) -> None:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._send_locked(
            {
                "method": "initialize",
                "id": request_id,
                "params": {
                    "clientInfo": {
                        "name": self.client_name,
                        "title": self.client_title,
                        "version": self.client_version,
                    }
                },
            }
        )
        self._wait_for_response_locked(request_id, timeout_seconds=DEFAULT_STARTUP_TIMEOUT_SECONDS)
        self._send_locked({"method": "initialized", "params": {}})
        self._initialized = True

    def _send_locked(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise CodexAppServerUnavailable("Codex app-server is not running.")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except Exception as exc:  # noqa: BLE001
            raise CodexAppServerUnavailable(self._timeout_message()) from exc

    def _stdout_reader(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                self._stderr_buffer.append(text)
                continue
            if isinstance(payload, dict):
                self._stdout_queue.put(payload)

    def _stderr_reader(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            text = line.strip()
            if text:
                self._stderr_buffer.append(text)

    def _timeout_message(self) -> str:
        detail = self._latest_stderr()
        if detail:
            return f"Codex app-server did not respond. {detail}"
        return (
            "Codex app-server is unavailable. Install or update Codex CLI with "
            "`npm i -g @openai/codex@latest` and sign in with ChatGPT."
        )

    def _latest_stderr(self) -> str:
        if not self._stderr_buffer:
            return ""
        return self._stderr_buffer[-1]

    @classmethod
    def _resolve_command(cls) -> CodexAppServerCommand:
        with cls._command_lock:
            if cls._cached_command is not None:
                return cls._cached_command
            candidates = [
                CodexAppServerCommand("codex app-server", "codex app-server"),
                CodexAppServerCommand(
                    "npx -y @openai/codex@latest app-server",
                    "npx @openai/codex@latest app-server",
                ),
            ]
            for candidate in candidates:
                if _supports_app_server(candidate.command):
                    cls._cached_command = candidate
                    return candidate
        raise CodexAppServerUnavailable(
            "Codex app-server is not available. Install or update Codex CLI with "
            "`npm i -g @openai/codex@latest`."
        )

    @staticmethod
    def _launch_args(command: str) -> list[str]:
        if os.name == "nt":
            return ["cmd.exe", "/d", "/s", "/c", command]
        return ["/bin/sh", "-lc", command]


def _supports_app_server(command: str) -> bool:
    try:
        completed = subprocess.run(
            CodexAppServerConnection._launch_args(f"{command} --help"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DEFAULT_STARTUP_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return completed.returncode == 0 and any(marker in output for marker in APP_SERVER_HELP_MARKERS)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if completed.returncode == 0 or process.poll() is not None:
                return
        except Exception:  # noqa: BLE001
            pass
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            return
