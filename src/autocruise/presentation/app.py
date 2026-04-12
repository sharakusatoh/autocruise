from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import threading
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from autocruise.domain.models import utc_now
from autocruise.infrastructure.ipc import send_command
from autocruise.infrastructure.storage import WorkspacePaths, append_jsonl, load_structured
from autocruise.presentation.labels import set_locale, tr
from autocruise.presentation.ui.shell import launch_ui
from autocruise.version import APP_TITLE


def launch(argv: list[str] | None = None) -> None:
    args = _parse_args(argv or sys.argv[1:])
    workspace_root = _resolve_workspace_root()
    data_root = _resolve_data_root(workspace_root)
    _migrate_runtime_data(workspace_root, data_root)
    paths = WorkspacePaths(workspace_root, data_root=data_root)
    paths.ensure()
    set_locale(load_structured(paths.preferences_path()).get("language", "en"))
    _install_runtime_guards(paths)

    if args.run_task and send_command(workspace_root, {"command": "run_task", "task_id": args.run_task}):
        return
    if not args.run_task and send_command(workspace_root, {"command": "show_main"}):
        return

    try:
        launch_ui(workspace_root, data_root=data_root, pending_task_id=args.run_task, start_hidden=bool(args.run_task))
    except Exception as exc:  # noqa: BLE001
        _report_unhandled_exception(paths, type(exc), exc, exc.__traceback__, source="launch")
        _show_fatal_error_dialog(paths)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-task", dest="run_task", default="")
    return parser.parse_args(argv)


def _resolve_workspace_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_root = Path(sys.executable).resolve().parent
        bundled_root = Path(getattr(sys, "_MEIPASS", executable_root))
        if (executable_root / "constitution").exists():
            return executable_root
        if (bundled_root / "constitution").exists():
            return bundled_root
        return executable_root
    return Path(__file__).resolve().parents[3]


def _resolve_data_root(workspace_root: Path) -> Path:
    override = os.environ.get("AUTOCRUISE_CE_DATA_DIR") or os.environ.get("AUTOCRUISE_DATA_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        local_appdata = Path(os.environ.get("LOCALAPPDATA", str(workspace_root)))
        return local_appdata / "AutoCruiseCE"
    return workspace_root


def _migrate_runtime_data(workspace_root: Path, data_root: Path) -> None:
    if workspace_root == data_root:
        return
    for name in ("users", "logs", "screenshots"):
        source = workspace_root / name
        target = data_root / name
        if source.exists() and not target.exists():
            shutil.copytree(source, target)


def _install_runtime_guards(paths: WorkspacePaths) -> None:
    def handle_main_exception(exc_type, exc_value, exc_traceback) -> None:
        _report_unhandled_exception(paths, exc_type, exc_value, exc_traceback, source="sys.excepthook")
        _show_fatal_error_dialog(paths)

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        _report_unhandled_exception(
            paths,
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            source=f"thread:{getattr(args.thread, 'name', 'unknown')}",
        )

    sys.excepthook = handle_main_exception
    threading.excepthook = handle_thread_exception


def _report_unhandled_exception(
    paths: WorkspacePaths,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback,
    *,
    source: str,
) -> None:
    append_jsonl(
        paths.logs_dir / "crash_log.jsonl",
        {
            "timestamp": utc_now(),
            "source": source,
            "exception_type": getattr(exc_type, "__name__", str(exc_type)),
            "message": str(exc_value),
            "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
        },
    )


def _show_fatal_error_dialog(paths: WorkspacePaths) -> None:
    app = QApplication.instance()
    if app is None:
        return
    QMessageBox.critical(
        None,
        APP_TITLE,
        tr("message.fatal_error", path=str(paths.logs_dir / "crash_log.jsonl")),
    )
