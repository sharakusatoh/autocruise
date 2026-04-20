from __future__ import annotations

import json
import shutil
from datetime import datetime

from autocruise.infrastructure.storage import ScheduledJobRepository, WorkspacePaths, read_jsonl, read_text
from autocruise.presentation.labels import (
    friendly_app_name,
    friendly_job_state,
    friendly_knowledge_kind,
    friendly_result,
    tr,
)


CAPTURE_SUFFIXES = {".png", ".ppm", ".jpg", ".jpeg", ".webp", ".gif"}


def _format_timestamp(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def load_session_history(paths: WorkspacePaths, limit: int = 200) -> list[dict]:
    records = read_jsonl(paths.logs_dir / "session_history.jsonl", limit=limit)
    records.reverse()
    return [_decorate_history_record(record) for record in records]


def load_session_detail(paths: WorkspacePaths, session_id: str) -> dict:
    history = _decorate_history_record(
        next(
            (item for item in read_jsonl(paths.logs_dir / "session_history.jsonl") if item.get("session_id") == session_id),
            {},
        )
    )
    audit = [item for item in read_jsonl(paths.logs_dir / "audit_log.jsonl") if item.get("session_id") == session_id]
    execution = [item for item in read_jsonl(paths.logs_dir / "execution_log.jsonl") if item.get("session_id") == session_id]
    capture_dir = paths.session_screenshot_path(session_id)
    captures = []
    if capture_dir.exists():
        captures = [
            str(path)
            for path in sorted(capture_dir.iterdir())
            if path.is_file() and path.suffix.lower() in CAPTURE_SUFFIXES
        ]
    return {
        "history": history,
        "audit": audit,
        "execution": execution,
        "captures": captures,
    }


def delete_session_thread(paths: WorkspacePaths, session_id: str) -> bool:
    if not session_id:
        return False

    removed = False
    removed |= _rewrite_jsonl(
        paths.logs_dir / "session_history.jsonl",
        lambda item: item.get("session_id") != session_id,
    )
    removed |= _rewrite_jsonl(
        paths.logs_dir / "audit_log.jsonl",
        lambda item: item.get("session_id") != session_id,
    )
    removed |= _rewrite_jsonl(
        paths.logs_dir / "execution_log.jsonl",
        lambda item: item.get("session_id") != session_id,
    )

    capture_dir = paths.session_screenshot_path(session_id)
    if capture_dir.exists():
        shutil.rmtree(capture_dir, ignore_errors=False)
        removed = True

    return removed


def build_knowledge_items(paths: WorkspacePaths) -> dict[str, list[dict]]:
    prompt_path = paths.users_dir / "default" / "user_custom_prompt.md"
    prompt_items = []
    if prompt_path.exists():
        prompt_items.append(
            {
                "id": "prompt:default",
                "name": tr("category.custom_prompt"),
                "target": "default",
                "updated_at": _format_timestamp(datetime.fromtimestamp(prompt_path.stat().st_mtime).astimezone().isoformat()),
                "kind": "user",
                "kind_label": friendly_knowledge_kind("user"),
                "status": tr("value.active"),
                "summary": _summary_from_text(read_text(prompt_path)),
                "detail_path": str(prompt_path),
            }
        )
    for path in sorted(paths.custom_prompt_dir.glob("*.md")):
        prompt_items.append(
            {
                "id": f"prompt:{path.stem}",
                "name": path.stem,
                "target": "custom",
                "updated_at": _format_timestamp(datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()),
                "kind": "user",
                "kind_label": friendly_knowledge_kind("user"),
                "status": tr("value.active"),
                "summary": _summary_from_text(read_text(path)),
                "detail_path": str(path),
            }
        )

    return {
        "custom_prompt": prompt_items,
    }


def load_scheduled_jobs(paths: WorkspacePaths) -> list[dict]:
    repository = ScheduledJobRepository(paths)
    items: list[dict] = []
    for job in repository.list():
        summary = _schedule_summary(job)
        items.append(
            {
                "task_id": job.task_id,
                "name": _instruction_summary(job.instruction),
                "instruction": job.instruction,
                "recurrence": job.recurrence.value,
                "run_at": job.run_at,
                "run_time": _time_from_value(job.run_at),
                "weekday": job.weekdays[0] if job.weekdays else "Monday",
                "interval_minutes": job.interval_minutes,
                "random_runs_per_day": job.random_runs_per_day,
                "next_run_at": job.next_run_at,
                "enabled": job.enabled,
                "summary": summary,
                "result": friendly_job_state(job.last_result.value),
                "state_label": friendly_job_state(job.last_result.value),
                "tone": _job_tone(job.last_result.value),
                "last_result_text": _last_result_text(job),
            }
        )
    return items


def _summary_from_text(text: str) -> str:
    lines = [line.strip("# ").strip() for line in text.splitlines() if line.strip()]
    return lines[1] if len(lines) > 1 else (lines[0] if lines else "")


def _decorate_history_record(record: dict) -> dict:
    if not record:
        return {}
    enriched = dict(record)
    enriched["display_time"] = _format_timestamp(str(enriched.get("executed_at", "")))
    enriched["display_result"] = friendly_result(str(enriched.get("result", "")))
    enriched["display_app"] = friendly_app_name(str(enriched.get("target_app", "")))
    return enriched


def _rewrite_jsonl(path, keep_record) -> bool:
    records = read_jsonl(path)
    filtered = [record for record in records if keep_record(record)]
    changed = len(filtered) != len(records)
    if not changed:
        return False
    payload = "\n".join(_serialize_jsonl_record(record) for record in filtered)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")
    return True


def _serialize_jsonl_record(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False)


def _instruction_summary(text: str) -> str:
    stripped = " ".join(text.split())
    return stripped[:70] + ("..." if len(stripped) > 70 else "")


def _schedule_summary(job) -> str:
    recurrence = job.recurrence.value
    if recurrence == "once":
        return _format_timestamp(job.run_at)
    if recurrence == "daily":
        return f"{tr('schedule.daily')} - {_time_from_value(job.run_at)}"
    if recurrence == "weekdays":
        return f"{tr('schedule.weekdays')} - {_time_from_value(job.run_at)}"
    if recurrence == "weekly":
        weekday = job.weekdays[0] if job.weekdays else "Monday"
        weekday_label = tr(f"weekday.{weekday.lower()}") if weekday else tr("weekday.monday")
        return f"{tr('schedule.weekly')} - {weekday_label} - {_time_from_value(job.run_at)}"
    if recurrence == "interval":
        hours, minutes = divmod(max(1, int(job.interval_minutes or 0)), 60)
        return f"{tr('schedule.interval')} - {hours:02d}:{minutes:02d}"
    if recurrence == "random_hourly":
        return tr("schedule.random_hourly")
    if recurrence == "random_daily":
        return tr("schedule.random_daily_summary", count=max(1, int(job.random_runs_per_day or 1)))
    return recurrence


def _time_from_value(value: str) -> str:
    if "T" in value:
        try:
            return datetime.fromisoformat(value).strftime("%H:%M")
        except ValueError:
            return value[-5:]
    return value


def _job_tone(value: str) -> str:
    if value == "running":
        return "running"
    if value == "completed":
        return "done"
    if value in {"failed", "skipped"}:
        return "error"
    return "ready"


def _last_result_text(job) -> str:
    if not job.last_run_at:
        return tr("schedule.empty")
    return f"{friendly_job_state(job.last_result.value)} - {_format_timestamp(job.last_run_at)}"
