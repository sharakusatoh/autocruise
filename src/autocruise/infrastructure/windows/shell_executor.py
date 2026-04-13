from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from autocruise.domain.models import Action, ExecutionResult


TEXT_READ_ENCODINGS = ("utf-8", "utf-8-sig", "cp932", "utf-16")
MAX_CAPTURE_CHARS = 4000
MAX_TIMEOUT_SECONDS = 600


class ShellExecutor:
    def __init__(self, default_cwd: Path) -> None:
        self.default_cwd = default_cwd

    def execute(self, action: Action) -> ExecutionResult:
        kind = str(action.shell_kind or "powershell").strip().lower() or "powershell"
        command = str(action.shell_command or "").strip()
        if not command:
            return ExecutionResult(success=False, details="Shell command is empty", error="Shell command is empty")

        cwd = self._resolve_cwd(action.shell_cwd)
        if cwd is None:
            return ExecutionResult(
                success=False,
                details="Shell working directory does not exist",
                error="Shell working directory does not exist",
            )

        timeout_seconds = self._normalize_timeout(action.shell_timeout_seconds)
        if kind == "powershell":
            argv = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        elif kind == "cmd":
            argv = ["cmd.exe", "/d", "/s", "/c", command]
        elif kind == "process":
            try:
                argv = shlex.split(command, posix=False)
            except ValueError as exc:
                message = str(exc).strip() or "Process command could not be parsed"
                return ExecutionResult(success=False, details=message, error=message)
            if not argv:
                return ExecutionResult(success=False, details="Process command is empty", error="Process command is empty")
        else:
            return ExecutionResult(success=False, details=f"Unsupported shell kind: {kind}", error=f"Unsupported shell kind: {kind}")

        if action.shell_detach:
            return self._launch_detached(kind, command, argv, cwd)
        return self._run_and_capture(kind, command, argv, cwd, timeout_seconds)

    def _run_and_capture(
        self,
        kind: str,
        command: str,
        argv: list[str],
        cwd: Path,
        timeout_seconds: int,
    ) -> ExecutionResult:
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                timeout=timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = self._decode_output(exc.stdout)
            stderr = self._decode_output(exc.stderr)
            payload = {
                "kind": kind,
                "command": command,
                "cwd": str(cwd),
                "detach": False,
                "timeout_seconds": timeout_seconds,
                "timed_out": True,
                "stdout": stdout,
                "stderr": stderr,
            }
            return ExecutionResult(
                success=False,
                details=f"Shell command timed out after {timeout_seconds}s",
                error=f"Shell command timed out after {timeout_seconds}s",
                payload=payload,
            )
        except OSError as exc:
            message = str(exc).strip() or "Shell command failed to start"
            return ExecutionResult(success=False, details=message, error=message)

        stdout = self._decode_output(completed.stdout)
        stderr = self._decode_output(completed.stderr)
        payload = {
            "kind": kind,
            "command": command,
            "cwd": str(cwd),
            "detach": False,
            "timeout_seconds": timeout_seconds,
            "exit_code": int(completed.returncode),
            "stdout": stdout,
            "stderr": stderr,
        }
        success = completed.returncode == 0
        detail = f"{kind} exited with code {completed.returncode}"
        if stdout:
            detail = f"{detail}. {self._headline(stdout)}"
        elif stderr:
            detail = f"{detail}. {self._headline(stderr)}"
        return ExecutionResult(success=success, details=detail, error="" if success else detail, payload=payload)

    def _launch_detached(self, kind: str, command: str, argv: list[str], cwd: Path) -> ExecutionResult:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if kind in {"powershell", "cmd"}:
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                shell=False,
                creationflags=creationflags,
            )
        except OSError as exc:
            message = str(exc).strip() or "Detached process failed to start"
            return ExecutionResult(success=False, details=message, error=message)
        payload = {
            "kind": kind,
            "command": command,
            "cwd": str(cwd),
            "detach": True,
            "pid": int(process.pid),
            "started": True,
        }
        return ExecutionResult(
            success=True,
            details=f"Started detached {kind} process {process.pid}",
            payload=payload,
        )

    def _resolve_cwd(self, requested_cwd: str) -> Path | None:
        normalized = str(requested_cwd or "").strip()
        if not normalized:
            return self.default_cwd
        candidate = Path(normalized)
        if not candidate.is_absolute():
            candidate = self.default_cwd / candidate
        candidate = candidate.resolve()
        if not candidate.exists() or not candidate.is_dir():
            return None
        return candidate

    def _normalize_timeout(self, raw_timeout: int) -> int:
        try:
            parsed = int(raw_timeout or 0)
        except (TypeError, ValueError):
            parsed = 0
        if parsed <= 0:
            parsed = 20
        return max(1, min(MAX_TIMEOUT_SECONDS, parsed))

    def _decode_output(self, value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return self._trim_text(value)
        for encoding in TEXT_READ_ENCODINGS:
            try:
                return self._trim_text(value.decode(encoding))
            except UnicodeDecodeError:
                continue
        return self._trim_text(value.decode("utf-8", errors="replace"))

    def _trim_text(self, text: str) -> str:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(normalized) <= MAX_CAPTURE_CHARS:
            return normalized
        return normalized[:MAX_CAPTURE_CHARS].rstrip() + "..."

    def _headline(self, text: str) -> str:
        normalized = self._trim_text(text)
        if not normalized:
            return ""
        return normalized.splitlines()[0][:180]
