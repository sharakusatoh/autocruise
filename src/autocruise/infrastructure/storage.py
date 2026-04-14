from __future__ import annotations

import base64
import ctypes
import json
import os
import time
from ctypes import wintypes
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from autocruise.domain.models import ProviderSettings, ScheduleKind, ScheduledJob, ScheduledJobState, utc_now


DEFAULT_PROVIDER_SETTINGS: list[ProviderSettings] = [
    ProviderSettings(
        provider="codex",
        base_url="codex app-server",
        model="gpt-5.4",
        reasoning_effort="medium",
        timeout_seconds=180,
        retry_count=0,
        max_tokens=2048,
        allow_images=True,
        is_default=True,
        service_tier="auto",
    ),
]

CRYPTPROTECT_UI_FORBIDDEN = 0x01
LEGACY_MAX_STEPS_DEFAULT = 60
MAX_STEPS_LIMIT_MIN = 5
MAX_STEPS_LIMIT_MAX = 5000
TEXT_READ_ENCODINGS = ("utf-8", "utf-8-sig", "cp932", "utf-16")


def make_json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return {key: make_json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    for encoding in TEXT_READ_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def write_text_file(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    retries: int = 6,
    retry_delay_seconds: float = 0.05,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    last_error: OSError | None = None
    for attempt in range(max(1, retries)):
        try:
            temp_path.write_text(text, encoding=encoding)
            os.replace(temp_path, path)
            return
        except OSError as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)
            if attempt + 1 < max(1, retries):
                time.sleep(retry_delay_seconds * (attempt + 1))
    if last_error is not None:
        raise last_error


def load_structured(path: Path) -> dict[str, Any]:
    text = read_text(path).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = _try_load_yaml(text)
    return parsed if isinstance(parsed, dict) else {}


def normalize_max_steps_preference(raw_preferences: dict[str, Any] | None) -> tuple[bool, int | None]:
    preferences = raw_preferences or {}
    raw_enabled = preferences.get("max_steps_limit_enabled")
    raw_value = preferences.get("max_steps_per_session")

    if raw_enabled is None:
        parsed = _coerce_optional_int(raw_value)
        if parsed is None or parsed <= 0 or parsed == LEGACY_MAX_STEPS_DEFAULT:
            return False, None
        return True, max(MAX_STEPS_LIMIT_MIN, min(MAX_STEPS_LIMIT_MAX, parsed))

    enabled = _coerce_bool(raw_enabled)
    if not enabled:
        return False, None

    parsed = _coerce_optional_int(raw_value)
    if parsed is None or parsed <= 0:
        return False, None
    return True, max(MAX_STEPS_LIMIT_MIN, min(MAX_STEPS_LIMIT_MAX, parsed))


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(make_json_safe(record), ensure_ascii=False) + "\n")


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit is not None:
        lines = lines[-limit:]
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


class WorkspacePaths:
    def __init__(self, root: Path, data_root: Path | None = None) -> None:
        self.root = root
        self.data_root = data_root or root
        self.constitution_dir = root / "constitution"
        self.apps_dir = root / "apps"
        self.tasks_dir = root / "tasks"
        self.bundled_users_dir = root / "users"
        self.bundled_systemprompt_dir = self.bundled_users_dir / "default" / "systemprompt"
        self.users_dir = self.data_root / "users"
        self.systemprompt_dir = self.users_dir / "default" / "systemprompt"
        self.custom_prompt_dir = self.users_dir / "default" / "custom_prompts"
        self.logs_dir = self.data_root / "logs"
        self.screenshots_dir = self.data_root / "screenshots"

    def ensure(self) -> None:
        for directory in (
            self.constitution_dir,
            self.apps_dir,
            self.tasks_dir,
            self.data_root,
            self.users_dir,
            self.systemprompt_dir,
            self.custom_prompt_dir,
            self.logs_dir,
            self.screenshots_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        for log_name in ("execution_log.jsonl", "learning_log.jsonl", "audit_log.jsonl", "session_history.jsonl"):
            (self.logs_dir / log_name).touch(exist_ok=True)

        for profile in self.apps_dir.glob("*/app_profile.md"):
            (profile.parent / "app_memory.jsonl").touch(exist_ok=True)

        for recipe in self.tasks_dir.glob("*/task_recipe.md"):
            (recipe.parent / "task_memory.jsonl").touch(exist_ok=True)

        (self.users_dir / "default").mkdir(parents=True, exist_ok=True)
        self._seed_user_file("provider_settings.json")
        self._seed_user_file("preferences.yaml")
        self._seed_user_file("user_custom_prompt.md")
        self._seed_user_markdown_directory("custom_prompts")
        (self.users_dir / "default" / "scheduled_jobs.json").touch(exist_ok=True)
        if not any(self.iter_systemprompt_names()):
            write_text_file(
                self.systemprompt_dir / "default.md",
                "# Default System Prompt\n\nFocus on practical progress and concise planning.\n",
                encoding="utf-8",
            )

    def app_memory_path(self, app_name: str) -> Path:
        return self.apps_dir / app_name / "app_memory.jsonl"

    def task_memory_path(self, task_name: str) -> Path:
        return self.tasks_dir / task_name / "task_memory.jsonl"

    def provider_settings_path(self, user_id: str = "default") -> Path:
        return self.users_dir / user_id / "provider_settings.json"

    def preferences_path(self, user_id: str = "default") -> Path:
        return self.users_dir / user_id / "preferences.yaml"

    def scheduled_jobs_path(self, user_id: str = "default") -> Path:
        return self.users_dir / user_id / "scheduled_jobs.json"

    def session_screenshot_path(self, session_id: str) -> Path:
        return self.screenshots_dir / f"session_{session_id}"

    def session_screenshot_dir(self, session_id: str) -> Path:
        path = self.session_screenshot_path(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def iter_systemprompt_names(self) -> list[str]:
        names: set[str] = set()
        for directory in self.systemprompt_search_dirs():
            if not directory.exists():
                continue
            names.update(path.name for path in directory.glob("*.md") if path.is_file())
        return sorted(names)

    def resolve_systemprompt_path(self, name: str) -> Path | None:
        normalized = str(name or "").strip()
        if not normalized:
            return None
        if not Path(normalized).suffix:
            normalized = f"{normalized}.md"
        runtime_path = self.systemprompt_dir / normalized
        bundled_path = self.bundled_systemprompt_dir / normalized
        runtime_exists = runtime_path.exists()
        bundled_exists = bundled_path.exists()
        if runtime_exists and bundled_exists:
            runtime_text = read_text(runtime_path)
            bundled_text = read_text(bundled_path)
            if runtime_text == bundled_text:
                return bundled_path
            runtime_mtime = runtime_path.stat().st_mtime
            bundled_mtime = bundled_path.stat().st_mtime
            return runtime_path if runtime_mtime >= bundled_mtime else bundled_path
        if runtime_exists:
            return runtime_path
        if bundled_exists:
            return bundled_path
        return None

    def systemprompt_search_dirs(self) -> list[Path]:
        directories: list[Path] = []
        seen: set[Path] = set()
        for directory in (self.systemprompt_dir, self.bundled_systemprompt_dir):
            resolved = directory.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            directories.append(directory)
        return directories

    def _seed_user_file(self, name: str) -> None:
        target = self.users_dir / "default" / name
        source = self.bundled_users_dir / "default" / name
        if target.exists() and target.stat().st_size > 0:
            if not self._should_refresh_default_user_file(name, target, source):
                return
        if source.exists():
            write_text_file(target, source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            target.touch(exist_ok=True)

    def _seed_user_markdown_directory(self, name: str) -> None:
        source_dir = self.root / "users" / "default" / name
        target_dir = self.users_dir / "default" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        if not source_dir.exists():
            return
        for source in source_dir.glob("*.md"):
            if not source.is_file():
                continue
            target = target_dir / source.name
            if target.exists() and target.stat().st_size > 0:
                continue
            write_text_file(target, source.read_text(encoding="utf-8"), encoding="utf-8")

    def _should_refresh_default_user_file(self, name: str, target: Path, source: Path) -> bool:
        if name != "user_custom_prompt.md" or not source.exists():
            return False
        current = target.read_text(encoding="utf-8")
        legacy_markers = (
            "## Caution Preference",
            "## Confirmation Granularity",
            "Favor reliability and auditability over raw speed.",
        )
        return any(marker in current for marker in legacy_markers)


class JsonlLogger:
    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    def execution(self, record: dict[str, Any]) -> None:
        append_jsonl(self.paths.logs_dir / "execution_log.jsonl", record)

    def learning(self, record: dict[str, Any]) -> None:
        append_jsonl(self.paths.logs_dir / "learning_log.jsonl", record)

    def audit(self, record: dict[str, Any]) -> None:
        append_jsonl(self.paths.logs_dir / "audit_log.jsonl", record)

    def history(self, record: dict[str, Any]) -> None:
        append_jsonl(self.paths.logs_dir / "session_history.jsonl", record)


class ScreenshotRetentionService:
    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    def mark_important(self, screenshot_path: Path) -> None:
        screenshot_path.with_suffix(screenshot_path.suffix + ".keep").write_text(
            "important",
            encoding="utf-8",
        )

    def mark_high_risk(self, screenshot_path: Path) -> None:
        self.mark_important(screenshot_path)

    def purge(
        self,
        default_ttl_days: int,
        important_ttl_days: int | None = None,
        high_risk_ttl_days: int | None = None,
    ) -> int:
        if not self.paths.screenshots_dir.exists():
            return 0

        retained_ttl_days = important_ttl_days if important_ttl_days is not None else high_risk_ttl_days
        if retained_ttl_days is None:
            retained_ttl_days = default_ttl_days
        now = time.time()
        deleted = 0
        for path in self.paths.screenshots_dir.rglob("*"):
            if not path.is_file() or path.suffix == ".keep":
                continue

            keep_sidecar = path.with_suffix(path.suffix + ".keep")
            ttl_days = retained_ttl_days if keep_sidecar.exists() else default_ttl_days
            age_seconds = now - path.stat().st_mtime
            if age_seconds > ttl_days * 86400:
                path.unlink(missing_ok=True)
                keep_sidecar.unlink(missing_ok=True)
                deleted += 1
        return deleted


class ProviderSettingsRepository:
    def __init__(self, paths: WorkspacePaths, user_id: str = "default") -> None:
        self.paths = paths
        self.user_id = user_id

    def load(self) -> list[ProviderSettings]:
        path = self.paths.provider_settings_path(self.user_id)
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return [ProviderSettings(**make_json_safe(item)) for item in DEFAULT_PROVIDER_SETTINGS]

        defaults = {item.provider: item for item in DEFAULT_PROVIDER_SETTINGS}
        try:
            raw_payload = json.loads(text)
        except json.JSONDecodeError:
            return [ProviderSettings(**make_json_safe(item)) for item in DEFAULT_PROVIDER_SETTINGS]
        payload = [
            self._coerce_setting(item, defaults.get(str(item.get("provider", ""))))
            for item in raw_payload
            if isinstance(item, dict)
        ]
        merged: dict[str, ProviderSettings] = {item.provider: item for item in payload}
        ordered: list[ProviderSettings] = []
        found_default = any(item.is_default for item in merged.values())
        for default in DEFAULT_PROVIDER_SETTINGS:
            current = merged.get(default.provider, default)
            ordered.append(
                ProviderSettings(
                    provider=default.provider,
                    base_url=self._normalize_base_url(default.provider),
                    model=self._normalize_model(default.provider, current.model or default.model),
                    reasoning_effort=self._normalize_effort(
                        str(getattr(current, "reasoning_effort", default.reasoning_effort) or default.reasoning_effort)
                    ),
                    timeout_seconds=self._coerce_int(current.timeout_seconds, default.timeout_seconds, minimum=10, maximum=300),
                    retry_count=self._coerce_int(current.retry_count, default.retry_count, minimum=0, maximum=5),
                    max_tokens=self._coerce_int(current.max_tokens, default.max_tokens, minimum=256, maximum=4096),
                    allow_images=True,
                    is_default=current.is_default if found_default else default.is_default,
                    service_tier=self._normalize_service_tier(getattr(current, "service_tier", default.service_tier)),
                )
            )
        return ordered

    def save(self, settings: list[ProviderSettings]) -> None:
        path = self.paths.provider_settings_path(self.user_id)
        settings = self._normalize_defaults(settings)
        path.write_text(
            json.dumps([make_json_safe(item) for item in settings], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_default(self) -> ProviderSettings:
        settings = self.load()
        for item in settings:
            if item.is_default:
                return item
        return settings[0]

    def upsert(self, setting: ProviderSettings) -> list[ProviderSettings]:
        settings = self.load()
        updated: list[ProviderSettings] = []
        replaced = False
        for current in settings:
            if current.provider == setting.provider:
                updated.append(setting)
                replaced = True
            else:
                updated.append(current)
        if not replaced:
            updated.append(setting)
        updated = self._normalize_defaults(updated)
        self.save(updated)
        return updated

    def _normalize_defaults(self, settings: list[ProviderSettings]) -> list[ProviderSettings]:
        allowed = {item.provider for item in DEFAULT_PROVIDER_SETTINGS}
        settings = [item for item in settings if item.provider in allowed]
        providers = {item.provider for item in settings}
        for default in DEFAULT_PROVIDER_SETTINGS:
            if default.provider not in providers:
                settings.append(default)

        default_provider = next((item.provider for item in settings if item.is_default), "codex")
        normalized: list[ProviderSettings] = []
        seen: set[str] = set()
        for current in settings:
            if current.provider in seen:
                continue
            seen.add(current.provider)
            normalized.append(
                ProviderSettings(
                    provider=current.provider,
                    base_url=self._normalize_base_url(current.provider),
                    model=self._normalize_model(current.provider, current.model),
                    reasoning_effort=self._normalize_effort(getattr(current, "reasoning_effort", "")),
                    timeout_seconds=self._coerce_int(
                        current.timeout_seconds,
                        self._default_for(current.provider).timeout_seconds,
                        minimum=10,
                        maximum=300,
                    ),
                    retry_count=self._coerce_int(
                        current.retry_count,
                        self._default_for(current.provider).retry_count,
                        minimum=0,
                        maximum=5,
                    ),
                    max_tokens=self._coerce_int(
                        current.max_tokens,
                        self._default_for(current.provider).max_tokens,
                        minimum=256,
                        maximum=4096,
                    ),
                    allow_images=True,
                    is_default=current.provider == default_provider,
                    service_tier=self._normalize_service_tier(getattr(current, "service_tier", "")),
                )
            )
        order = {item.provider: index for index, item in enumerate(DEFAULT_PROVIDER_SETTINGS)}
        normalized.sort(key=lambda item: order.get(item.provider, 99))
        return normalized

    def _normalize_model(self, provider: str, model: str) -> str:
        normalized = (model or "").strip()
        return normalized or self._default_for(provider).model

    def _normalize_effort(self, effort: str) -> str:
        normalized = (effort or "").strip().lower()
        if normalized in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            return normalized
        return "medium"

    def _normalize_service_tier(self, service_tier: Any) -> str:
        normalized = (service_tier or "").strip().lower()
        if not normalized or normalized in {"default", "standard"}:
            return "auto"
        return normalized

    def _normalize_base_url(self, provider: str) -> str:
        return self._default_for(provider).base_url

    def _default_for(self, provider: str) -> ProviderSettings:
        for item in DEFAULT_PROVIDER_SETTINGS:
            if item.provider == provider:
                return item
        return DEFAULT_PROVIDER_SETTINGS[0]

    def _coerce_setting(self, payload: dict[str, Any], default: ProviderSettings | None) -> ProviderSettings:
        provider = str(payload.get("provider", default.provider if default else "")).strip().lower()
        fallback = default or self._default_for(provider or "codex")
        return ProviderSettings(
            provider=provider or fallback.provider,
            base_url=self._normalize_base_url(provider or fallback.provider),
            model=self._normalize_model(provider or fallback.provider, str(payload.get("model", fallback.model))),
            reasoning_effort=self._normalize_effort(str(payload.get("reasoning_effort", fallback.reasoning_effort))),
            timeout_seconds=self._coerce_int(payload.get("timeout_seconds"), fallback.timeout_seconds, minimum=10, maximum=300),
            retry_count=self._coerce_int(payload.get("retry_count"), fallback.retry_count, minimum=0, maximum=5),
            max_tokens=self._coerce_int(payload.get("max_tokens"), fallback.max_tokens, minimum=256, maximum=4096),
            allow_images=True,
            is_default=bool(payload.get("is_default", fallback.is_default)),
            service_tier=self._normalize_service_tier(payload.get("service_tier", fallback.service_tier)),
        )

    def _coerce_int(self, value: Any, fallback: int, minimum: int = 0, maximum: int = 600) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(minimum, min(maximum, parsed))


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(raw: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(raw)
    return DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))


class SecureSecretStore:
    def __init__(self, paths: WorkspacePaths) -> None:
        override_dir = os.environ.get("AUTOCRUISE_CE_SECRET_DIR") or os.environ.get("AUTOCRUISE_SECRET_DIR")
        local_appdata = Path(os.environ.get("LOCALAPPDATA", str(paths.root)))
        if override_dir:
            self.secret_dir = Path(override_dir)
        else:
            self.secret_dir = local_appdata / "AutoCruiseCE" / "Secrets"
        self.secret_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_secrets(paths.root / ".secrets")
        self._migrate_legacy_secrets(local_appdata / "AutoCruise" / "Secrets")
        self._mark_hidden(self.secret_dir)

    def _protect(self, raw: bytes) -> bytes:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob = _blob_from_bytes(raw)
        out_blob = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "AutoCruise CE",
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        ):
            raise OSError("CryptProtectData failed")

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def _unprotect(self, raw: bytes) -> bytes:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob = _blob_from_bytes(raw)
        out_blob = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        ):
            raise OSError("CryptUnprotectData failed")

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def save_api_key(self, provider: str, api_key: str) -> None:
        encrypted = self._protect(api_key.encode("utf-8"))
        target = self.secret_dir / f"{provider}.bin"
        target.write_text(base64.b64encode(encrypted).decode("ascii"), encoding="utf-8")
        self._mark_hidden(target)

    def load_api_key(self, provider: str) -> str:
        target = self.secret_dir / f"{provider}.bin"
        if not target.exists():
            return ""
        payload = base64.b64decode(target.read_text(encoding="utf-8"))
        return self._unprotect(payload).decode("utf-8")

    def _migrate_legacy_secrets(self, legacy_dir: Path) -> None:
        if not legacy_dir.exists():
            return
        for secret_file in legacy_dir.glob("*.bin"):
            target = self.secret_dir / secret_file.name
            if not target.exists():
                target.write_bytes(secret_file.read_bytes())
                self._mark_hidden(target)
            secret_file.unlink(missing_ok=True)
        try:
            legacy_dir.rmdir()
        except OSError:
            return

    def _mark_hidden(self, path: Path) -> None:
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
        except Exception:  # noqa: BLE001
            return


class ScheduledJobRepository:
    def __init__(self, paths: WorkspacePaths, user_id: str = "default") -> None:
        self.paths = paths
        self.user_id = user_id

    def load(self) -> list[ScheduledJob]:
        path = self.paths.scheduled_jobs_path(self.user_id)
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        jobs: list[ScheduledJob] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                jobs.append(
                    ScheduledJob(
                        task_id=str(item["task_id"]),
                        instruction=str(item["instruction"]),
                        run_at=str(item["run_at"]),
                        recurrence=ScheduleKind(str(item["recurrence"])),
                        enabled=bool(item.get("enabled", True)),
                        last_result=ScheduledJobState(str(item.get("last_result", ScheduledJobState.SCHEDULED.value))),
                        last_message=str(item.get("last_message", "")),
                        last_run_at=str(item.get("last_run_at", "")),
                        weekdays=[str(day) for day in item.get("weekdays", []) if str(day).strip()],
                        interval_minutes=int(item.get("interval_minutes", 0) or 0),
                        random_runs_per_day=int(item.get("random_runs_per_day", 0) or 0),
                        next_run_at=str(item.get("next_run_at", "")),
                        planned_run_times=[str(value) for value in item.get("planned_run_times", []) if str(value).strip()],
                        created_at=str(item.get("created_at", "")),
                        updated_at=str(item.get("updated_at", "")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        jobs.sort(key=lambda job: job.updated_at or job.created_at, reverse=True)
        return jobs

    def save(self, jobs: list[ScheduledJob]) -> None:
        path = self.paths.scheduled_jobs_path(self.user_id)
        path.write_text(
            json.dumps([make_json_safe(job) for job in jobs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list(self) -> list[ScheduledJob]:
        return self.load()

    def get(self, task_id: str) -> ScheduledJob | None:
        return next((job for job in self.load() if job.task_id == task_id), None)

    def upsert(self, job: ScheduledJob) -> ScheduledJob:
        jobs = self.load()
        updated: list[ScheduledJob] = []
        replaced = False
        for current in jobs:
            if current.task_id == job.task_id:
                updated.append(job)
                replaced = True
            else:
                updated.append(current)
        if not replaced:
            updated.append(job)
        self.save(updated)
        return job

    def delete(self, task_id: str) -> None:
        jobs = [job for job in self.load() if job.task_id != task_id]
        self.save(jobs)

    def set_enabled(self, task_id: str, enabled: bool) -> ScheduledJob | None:
        job = self.get(task_id)
        if job is None:
            return None
        updated = ScheduledJob(
            task_id=job.task_id,
            instruction=job.instruction,
            run_at=job.run_at,
            recurrence=job.recurrence,
            enabled=enabled,
            last_result=job.last_result,
            last_message=job.last_message,
            last_run_at=job.last_run_at,
            weekdays=job.weekdays,
            interval_minutes=job.interval_minutes,
            random_runs_per_day=job.random_runs_per_day,
            next_run_at=job.next_run_at,
            planned_run_times=job.planned_run_times,
            created_at=job.created_at,
            updated_at=utc_now(),
        )
        return self.upsert(updated)

    def record_result(
        self,
        task_id: str,
        result: ScheduledJobState,
        message: str,
        ran_at: str,
    ) -> ScheduledJob | None:
        job = self.get(task_id)
        if job is None:
            return None
        updated = ScheduledJob(
            task_id=job.task_id,
            instruction=job.instruction,
            run_at=job.run_at,
            recurrence=job.recurrence,
            enabled=job.enabled,
            last_result=result,
            last_message=message,
            last_run_at=ran_at,
            weekdays=job.weekdays,
            interval_minutes=job.interval_minutes,
            random_runs_per_day=job.random_runs_per_day,
            next_run_at=job.next_run_at,
            planned_run_times=job.planned_run_times,
            created_at=job.created_at,
            updated_at=ran_at,
        )
        return self.upsert(updated)


def _try_load_yaml(text: str) -> Any:
    try:
        import yaml
    except Exception:  # noqa: BLE001
        return {}
    try:
        return yaml.safe_load(text) or {}
    except Exception:  # noqa: BLE001
        return {}
