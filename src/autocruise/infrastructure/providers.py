from __future__ import annotations

import base64
import re
import tempfile
from pathlib import Path

from autocruise.domain.models import ProviderSettings, ProviderTestResult
from autocruise.infrastructure.codex_app_server import CodexAppServerConnection, CodexAppServerError


REDACTION_PATTERNS = (
    (re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)", re.IGNORECASE), r"\1[redacted]"),
    (re.compile(r'("api_key"\s*:\s*")([^"]+)(")', re.IGNORECASE), r"\1[redacted]\3"),
    (re.compile(r"(data:image\/[a-zA-Z0-9.+-]+;base64,)[A-Za-z0-9+/=]+"), r"\1[redacted]"),
)


class ProviderError(RuntimeError):
    def __init__(self, user_message: str, detail: str = "") -> None:
        scrubbed = scrub_sensitive_text(detail or user_message)
        super().__init__(scrubbed)
        self.user_message = user_message
        self.detail = scrubbed


class ProviderClient:
    def test_connection(self, settings: ProviderSettings, api_key: str) -> ProviderTestResult:
        temp_path: Path | None = None
        try:
            temp_path = _write_connection_probe_image()
            self.generate_text(
                settings=settings,
                api_key=api_key,
                instructions="You are a connection test. Reply with exactly OK.",
                prompt="Reply with exactly OK after receiving this test image.",
                image_path=str(temp_path),
                session_key=None,
            )
            return ProviderTestResult(ok=True, message="Connection confirmed. Text and screenshot input are available.")
        except ProviderError as exc:
            return ProviderTestResult(ok=False, message=exc.user_message)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def generate_text(
        self,
        settings: ProviderSettings,
        api_key: str,
        instructions: str,
        prompt: str,
        image_path: str | None = None,
        session_key: str | None = None,
        output_schema: dict | None = None,
    ) -> str:
        raise NotImplementedError


class CodexProviderClient(ProviderClient):
    def __init__(self, workspace_root: Path, app_server: CodexAppServerConnection | None = None) -> None:
        self.workspace_root = workspace_root
        self.app_server = app_server or CodexAppServerConnection(workspace_root)
        self._active_session_key = ""
        self._active_thread_id = ""

    def test_connection(self, settings: ProviderSettings, api_key: str) -> ProviderTestResult:
        _ = api_key
        try:
            account = self.app_server.read_account(refresh_token=False)
        except CodexAppServerError as exc:
            return ProviderTestResult(
                ok=False,
                message=scrub_sensitive_text(str(exc))
                or "Codex App Server is unavailable. Install or update Codex CLI, then sign in with ChatGPT.",
            )
        if account.auth_mode != "chatgpt":
            return ProviderTestResult(
                ok=False,
                message="Codex is not signed in with ChatGPT. Open Settings and choose Sign in with ChatGPT.",
            )
        return super().test_connection(settings, "")

    def generate_text(
        self,
        settings: ProviderSettings,
        api_key: str,
        instructions: str,
        prompt: str,
        image_path: str | None = None,
        session_key: str | None = None,
        output_schema: dict | None = None,
    ) -> str:
        _ = api_key
        try:
            account = self.app_server.read_account(refresh_token=False)
        except CodexAppServerError as exc:
            raise ProviderError(
                "Codex App Server is unavailable. Install or update Codex CLI, then sign in with ChatGPT.",
                str(exc),
            ) from exc

        if account.auth_mode != "chatgpt":
            raise ProviderError("Codex is not signed in with ChatGPT. Open Settings and choose Sign in with ChatGPT.")

        thread_id, transient = self._thread_for_session(settings, session_key)
        input_items = [{"type": "text", "text": f"{instructions}\n\n{prompt}"}]
        if image_path:
            input_items.append({"type": "localImage", "path": str(Path(image_path).resolve())})

        try:
            return self.app_server.run_turn(
                thread_id,
                input_items=input_items,
                model=settings.model or "gpt-5.4",
                cwd=self.workspace_root,
                effort=(settings.reasoning_effort or "medium"),
                service_tier=(settings.service_tier or "auto"),
                timeout_seconds=max(30, int(settings.timeout_seconds or 180)),
                output_schema=output_schema,
            )
        except CodexAppServerError as exc:
            raise ProviderError("Codex could not complete the request.", str(exc)) from exc
        finally:
            if transient:
                self.app_server.unsubscribe_thread(thread_id)

    def _thread_for_session(self, settings: ProviderSettings, session_key: str | None) -> tuple[str, bool]:
        normalized_key = (session_key or "").strip()
        if not normalized_key:
            return self.app_server.start_thread(settings.model or "gpt-5.4", self.workspace_root), True
        if normalized_key != self._active_session_key:
            if self._active_thread_id:
                self.app_server.unsubscribe_thread(self._active_thread_id)
            self._active_thread_id = self.app_server.start_thread(settings.model or "gpt-5.4", self.workspace_root)
            self._active_session_key = normalized_key
        return self._active_thread_id, False


def _write_connection_probe_image() -> Path:
    raw_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn4n4QAAAAASUVORK5CYII="
    )
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        handle.write(raw_png)
        handle.flush()
        return Path(handle.name)
    finally:
        handle.close()


def scrub_sensitive_text(value: str) -> str:
    scrubbed = value or ""
    for pattern, replacement in REDACTION_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


class ProviderRegistry:
    def __init__(
        self,
        workspace_root: Path | None = None,
        codex_app_server: CodexAppServerConnection | None = None,
    ) -> None:
        self.workspace_root = workspace_root or Path.cwd()
        self.codex_app_server = codex_app_server or CodexAppServerConnection(self.workspace_root)
        self._codex_client = CodexProviderClient(self.workspace_root, self.codex_app_server)

    def get(self, provider: str) -> ProviderClient:
        if provider == "codex":
            return self._codex_client
        raise ProviderError(
            "Only Codex App Server is available in AutoCruise CE.",
            f"Unsupported provider: {provider}",
        )
