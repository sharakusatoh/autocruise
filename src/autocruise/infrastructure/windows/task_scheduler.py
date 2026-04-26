from __future__ import annotations

import random
import subprocess
from datetime import datetime, time, timedelta

from autocruise.domain.models import ScheduleKind, ScheduledJob


class TaskSchedulerError(RuntimeError):
    pass


class WindowsTaskSchedulerService:
    def task_name(self, task_id: str) -> str:
        return f"AutoCruise_{task_id}"

    def register_job(self, job: ScheduledJob, execute: str, arguments: str, working_directory: str) -> None:
        trigger = self._trigger_expression(job)
        script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute '{self._ps_literal(execute)}' -Argument '{self._ps_literal(arguments)}' -WorkingDirectory '{self._ps_literal(working_directory)}'
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -StartWhenAvailable
$trigger = {trigger}
Register-ScheduledTask -TaskName '{self._ps_literal(self.task_name(job.task_id))}' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
if ({'$true' if job.enabled else '$false'} -eq $false) {{
    Disable-ScheduledTask -TaskName '{self._ps_literal(self.task_name(job.task_id))}' | Out-Null
}}
"""
        self._run(script)

    def delete_job(self, task_id: str) -> None:
        script = f"""
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName '{self._ps_literal(self.task_name(task_id))}' -ErrorAction SilentlyContinue
if ($task) {{
    Unregister-ScheduledTask -TaskName '{self._ps_literal(self.task_name(task_id))}' -Confirm:$false
}}
"""
        self._run(script)

    def set_enabled(self, task_id: str, enabled: bool) -> None:
        command = "Enable-ScheduledTask" if enabled else "Disable-ScheduledTask"
        script = f"""
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName '{self._ps_literal(self.task_name(task_id))}' -ErrorAction SilentlyContinue
if ($task) {{
    {command} -TaskName '{self._ps_literal(self.task_name(task_id))}' | Out-Null
}}
"""
        self._run(script)

    def stop_job(self, task_id: str) -> None:
        script = f"""
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName '{self._ps_literal(self.task_name(task_id))}' -ErrorAction SilentlyContinue
if ($task -and $task.State -eq 'Running') {{
    Stop-ScheduledTask -TaskName '{self._ps_literal(self.task_name(task_id))}' | Out-Null
}}
"""
        self._run(script)

    def _trigger_expression(self, job: ScheduledJob) -> str:
        scheduled_at = job.next_run_at
        if not scheduled_at:
            raise TaskSchedulerError("Scheduled job has no future run time.")
        return f"New-ScheduledTaskTrigger -Once -At ([datetime]'{self._ps_literal(scheduled_at)}')"

    def _time_text(self, value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%H:%M")
        except ValueError:
            return value[-5:]

    def _run(self, script: str) -> None:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "Task Scheduler command failed."
            raise TaskSchedulerError(message)

    def _ps_literal(self, value: str) -> str:
        return value.replace("'", "''")


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


def schedule_next_run(job: ScheduledJob, *, reference: datetime | None = None, consume_current: bool = False) -> ScheduledJob:
    now = _normalize_reference(reference)
    if consume_current:
        now += timedelta(minutes=1)

    planned = [item for item in job.planned_run_times if _parse_datetime(item) and _parse_datetime(item) >= now]
    next_run = ""

    if job.recurrence == ScheduleKind.ONCE:
        target = _parse_datetime(job.run_at)
        if target is not None and target >= now:
            next_run = target.isoformat(timespec="minutes")
        planned = []
    elif job.recurrence == ScheduleKind.DAILY:
        next_run = _next_daily(job.run_at, now).isoformat(timespec="minutes")
        planned = []
    elif job.recurrence == ScheduleKind.WEEKDAYS:
        next_run = _next_weekly(job.run_at, now, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]).isoformat(timespec="minutes")
        planned = []
    elif job.recurrence == ScheduleKind.WEEKLY:
        next_run = _next_weekly(job.run_at, now, job.weekdays or ["Monday"]).isoformat(timespec="minutes")
        planned = []
    elif job.recurrence == ScheduleKind.INTERVAL:
        minutes = max(1, int(job.interval_minutes or 0))
        next_run = (now + timedelta(minutes=minutes)).isoformat(timespec="minutes")
        planned = []
    elif job.recurrence == ScheduleKind.RANDOM_HOURLY:
        next_run = _next_random_hourly(now).isoformat(timespec="minutes")
        planned = [next_run]
    elif job.recurrence == ScheduleKind.RANDOM_DAILY:
        if not planned:
            planned = _next_random_daily_runs(now, max(1, int(job.random_runs_per_day or 1)))
        next_run = planned[0] if planned else ""

    return ScheduledJob(
        task_id=job.task_id,
        instruction=job.instruction,
        run_at=job.run_at,
        recurrence=job.recurrence,
        enabled=job.enabled,
        last_result=job.last_result,
        last_message=job.last_message,
        last_run_at=job.last_run_at,
        weekdays=job.weekdays,
        interval_minutes=job.interval_minutes,
        random_runs_per_day=job.random_runs_per_day,
        next_run_at=next_run,
        planned_run_times=planned,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _normalize_reference(reference: datetime | None) -> datetime:
    current = reference or datetime.now()
    current = current.replace(tzinfo=None)
    if current.second or current.microsecond:
        current = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return current.replace(second=0, microsecond=0)


def _parse_time(value: str) -> time:
    text = (value or "").strip()
    if "T" in text:
        try:
            return datetime.fromisoformat(text).time().replace(second=0, microsecond=0)
        except ValueError:
            pass
    try:
        return datetime.strptime(text[-5:], "%H:%M").time()
    except ValueError:
        return time(9, 0)


def _parse_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None, second=0, microsecond=0)
    except ValueError:
        return None


def _next_daily(run_at: str, now: datetime) -> datetime:
    target_time = _parse_time(run_at)
    candidate = datetime.combine(now.date(), target_time)
    if candidate < now:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly(run_at: str, now: datetime, weekdays: list[str]) -> datetime:
    target_time = _parse_time(run_at)
    allowed = {_weekday_number(day) for day in weekdays}
    for offset in range(8):
        candidate_date = now.date() + timedelta(days=offset)
        candidate = datetime.combine(candidate_date, target_time)
        if candidate.weekday() in allowed and candidate >= now:
            return candidate
    return datetime.combine(now.date() + timedelta(days=7), target_time)


def _weekday_number(label: str) -> int:
    mapping = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    return mapping.get((label or "").strip().lower(), 0)


def _next_random_hourly(now: datetime) -> datetime:
    window_start = now.replace(minute=0)
    candidate = _random_in_window(window_start, window_start + timedelta(hours=1), not_before=now)
    if candidate is not None:
        return candidate
    next_window = window_start + timedelta(hours=1)
    return _random_in_window(next_window, next_window + timedelta(hours=1), not_before=next_window) or next_window


def _next_random_daily_runs(now: datetime, runs_per_day: int) -> list[str]:
    days_ahead = 0
    while days_ahead < 3:
        day_start = datetime.combine((now + timedelta(days=days_ahead)).date(), time(0, 0))
        day_end = day_start + timedelta(days=1)
        not_before = now if days_ahead == 0 else day_start
        slots = _random_slots_in_window(day_start, day_end, runs_per_day, not_before=not_before)
        if slots:
            return [slot.isoformat(timespec="minutes") for slot in slots]
        days_ahead += 1
    fallback = now + timedelta(days=1)
    return [fallback.isoformat(timespec="minutes")]


def _random_slots_in_window(
    start: datetime,
    end: datetime,
    count: int,
    *,
    not_before: datetime,
) -> list[datetime]:
    lower_bound = max(start, not_before)
    available_minutes = int((end - lower_bound).total_seconds() // 60)
    if available_minutes <= 0:
        return []
    sample_size = min(max(1, count), available_minutes)
    offsets = sorted(random.sample(range(available_minutes), sample_size))
    return [lower_bound + timedelta(minutes=offset) for offset in offsets]


def _random_in_window(start: datetime, end: datetime, *, not_before: datetime) -> datetime | None:
    slots = _random_slots_in_window(start, end, 1, not_before=not_before)
    return slots[0] if slots else None
