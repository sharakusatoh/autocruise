from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, NORMAL, DISABLED, Button, Frame, Label, Tk, Text, messagebox


APP_EXE_NAME = "AutoCruiseCE.exe"
BOOTSTRAPPER_NAME = "AutoCruise Bootstrapper"
NODE_WINGET_ID = "OpenJS.NodeJS.LTS"
CODEX_PACKAGE = "@openai/codex@latest"
APP_SERVER_HELP_MARKERS = ("Usage: codex app-server", "Run the app server")


def hidden_subprocess_kwargs() -> dict:
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


def shell_args(command: str) -> list[str]:
    if os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", command]
    return ["/bin/sh", "-lc", command]


def refreshed_env() -> dict[str, str]:
    env = dict(os.environ)
    path_items = [env.get("PATH", "")]
    common_node_dirs = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs",
    ]
    for item in common_node_dirs:
        if item.exists():
            path_items.append(str(item))
    env["PATH"] = os.pathsep.join(part for part in path_items if part)
    return env


def run_shell(command: str, *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        shell_args(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=refreshed_env(),
        **hidden_subprocess_kwargs(),
    )


def has_command(command: str) -> bool:
    return shutil.which(command, path=refreshed_env().get("PATH")) is not None


def command_version(command: str) -> str:
    completed = run_shell(f"{command} --version", timeout=30)
    text = (completed.stdout or completed.stderr).strip()
    return text.splitlines()[0] if completed.returncode == 0 and text else ""


def supports_codex_app_server() -> tuple[bool, str]:
    candidates = [
        ("codex app-server", "codex app-server"),
        (f"npx -y {CODEX_PACKAGE} app-server", f"npx {CODEX_PACKAGE} app-server"),
    ]
    for command, label in candidates:
        try:
            completed = run_shell(f"{command} --help", timeout=180)
        except (OSError, subprocess.SubprocessError):
            continue
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        if completed.returncode == 0 and any(marker in output for marker in APP_SERVER_HELP_MARKERS):
            return True, label
    return False, ""


def locate_autocruise_exe() -> Path | None:
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parent)
    roots.append(Path.cwd())
    for root in roots:
        candidates = [
            root / APP_EXE_NAME,
            root / "release" / "AutoCruiseCE" / APP_EXE_NAME,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
    return None


class SetupApp(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(BOOTSTRAPPER_NAME)
        self.geometry("760x520")
        self.minsize(680, 440)
        self.messages: queue.Queue[str] = queue.Queue()
        self.buttons: list[Button] = []
        self._build_ui()
        self.after(100, self._drain_messages)
        self._log("AutoCruise Bootstrapper checks Node.js, npm/npx, and Codex app-server.")
        self._log("If everything is ready, launch AutoCruise and sign in with ChatGPT from Settings.")

    def _build_ui(self) -> None:
        Label(
            self,
            text=BOOTSTRAPPER_NAME,
            font=("Segoe UI", 18, "bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(16, 4))
        Label(
            self,
            text="Prepare the Codex runtime, then launch AutoCruise CE.",
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 12))

        button_row = Frame(self)
        button_row.pack(fill="x", padx=18, pady=(0, 12))
        self._add_button(button_row, "Run automatic setup", self.run_automatic_setup)
        self._add_button(button_row, "Install Node.js LTS", self.install_node)
        self._add_button(button_row, "Prepare Codex", self.prepare_codex)
        self._add_button(button_row, "Launch AutoCruise", self.launch_autocruise)
        self._add_button(button_row, "Open Node.js download", lambda: webbrowser.open("https://nodejs.org/en/download"))

        self.output = Text(self, wrap="word", font=("Consolas", 10), state=DISABLED)
        self.output.pack(fill=BOTH, expand=True, padx=18, pady=(0, 18))

    def _add_button(self, parent: Frame, text: str, command) -> None:
        button = Button(parent, text=text, command=command, padx=10, pady=6)
        button.pack(side=LEFT, padx=(0, 8))
        self.buttons.append(button)

    def _set_busy(self, busy: bool) -> None:
        for button in self.buttons:
            button.configure(state=DISABLED if busy else NORMAL)

    def _log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.messages.put(f"[{timestamp}] {message}")

    def _drain_messages(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            self.output.configure(state=NORMAL)
            self.output.insert(END, message + "\n")
            self.output.see(END)
            self.output.configure(state=DISABLED)
        self.after(100, self._drain_messages)

    def _run_worker(self, target) -> None:
        self._set_busy(True)

        def wrapper() -> None:
            try:
                target()
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERROR: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=wrapper, daemon=True).start()

    def run_automatic_setup(self) -> None:
        self._run_worker(self._automatic_setup)

    def install_node(self) -> None:
        self._run_worker(self._install_node)

    def prepare_codex(self) -> None:
        self._run_worker(self._prepare_codex)

    def _automatic_setup(self) -> None:
        self._log("Checking current runtime...")
        self._log_runtime_versions()
        available, label = supports_codex_app_server()
        if available:
            self._log(f"Codex app-server is available through: {label}")
            self._log("Setup is complete.")
            return

        if not has_command("node") or not has_command("npm") or not has_command("npx"):
            self._log("Node.js/npm/npx is not available.")
            self._install_node()
        else:
            self._log("Node.js/npm/npx is available.")

        self._prepare_codex()
        available, label = supports_codex_app_server()
        if available:
            self._log(f"Codex app-server is ready through: {label}")
            self._log("Setup is complete. Launch AutoCruise and sign in with ChatGPT from Settings.")
        else:
            self._log("Codex app-server is still unavailable. Check the log above, then try installing Node.js manually.")

    def _install_node(self) -> None:
        if has_command("node") and has_command("npm") and has_command("npx"):
            self._log("Node.js/npm/npx is already available.")
            self._log_runtime_versions()
            return
        if not has_command("winget"):
            self._log("winget is not available. Open the Node.js download page and install Node.js LTS manually.")
            return
        self._log("Installing Node.js LTS with winget. A Windows installer prompt may appear.")
        command = (
            f"winget install --id {NODE_WINGET_ID} -e --source winget "
            "--accept-package-agreements --accept-source-agreements"
        )
        completed = run_shell(command, timeout=900)
        self._log_command_result(completed)
        self._log_runtime_versions()

    def _prepare_codex(self) -> None:
        if not has_command("npx"):
            self._log("npx is not available, so Codex cannot be prepared yet.")
            return
        self._log("Preparing Codex through npx. The first run can take a few minutes.")
        completed = run_shell(f"npx -y {CODEX_PACKAGE} app-server --help", timeout=300)
        self._log_command_result(completed)

    def _log_runtime_versions(self) -> None:
        for command in ("node", "npm", "npx", "codex", "winget"):
            version = command_version(command)
            if version:
                self._log(f"{command}: {version}")
            else:
                self._log(f"{command}: not found")

    def _log_command_result(self, completed: subprocess.CompletedProcess[str]) -> None:
        self._log(f"Command exit code: {completed.returncode}")
        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip())
        if output:
            for line in output.splitlines()[-24:]:
                self._log(line)

    def launch_autocruise(self) -> None:
        exe = locate_autocruise_exe()
        if exe is None:
            messagebox.showerror(BOOTSTRAPPER_NAME, f"{APP_EXE_NAME} was not found next to this setup tool.")
            return
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), **hidden_subprocess_kwargs())
        except OSError as exc:
            messagebox.showerror(BOOTSTRAPPER_NAME, str(exc))
            return
        self._log(f"Launched {exe}")


def main() -> None:
    SetupApp().mainloop()


if __name__ == "__main__":
    main()
