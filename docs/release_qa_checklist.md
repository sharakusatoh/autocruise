# AutoCruise CE Release QA Checklist

Use this checklist before shipping a Windows build. Record the build path, date, tester, and result in diagnostics or the release QA memo.

## Build

- Run `python -m unittest discover -s tests -v`.
- Run `build_windows.bat`.
- Confirm `release\AutoCruiseCE\AutoCruiseCE.exe` starts.
- Confirm `release\AutoCruiseCE-portable-1.0.0.zip` exists.
- Confirm `autocruise\infrastructure\windows\uia_client.ps1` is present in the release folder.
- Confirm Playwright or browser binaries are not bundled by default.

## Runtime

- Open Settings and confirm Codex App Server status is visible.
- Sign in with ChatGPT and run the connection test.
- Confirm model, reasoning effort, and planning response size can be saved and restored.
- Confirm Japanese language selection persists after restart.

## Desktop Operation

- Run `ペイントを開いて、簡単な猫の絵を描いてください。`.
- Confirm Paint launches through a direct Windows path such as Run, visible launcher, or search.
- Confirm the agent waits for the Paint window and canvas.
- Confirm click, drag, and curve-like multi-point drawing work on the canvas.
- Confirm the run pauses when the requested drawing is complete.

## Japanese Input

- Enter a Japanese goal in the top input field.
- Confirm IME candidate UI appears near the insertion point.
- Confirm Japanese text can be entered into a target app through direct typing or clipboard fallback.

## Compact Window

- Start a long instruction and minimize AutoCruise CE.
- Confirm the compact window remains readable.
- Confirm long status text is truncated without crushing pause/stop buttons.
- Confirm Pause shows `F8` and Stop shows `F12` when those hotkeys are configured.

## Threads

- Run at least one task and open Threads.
- Confirm the selected thread detail view renders correctly.
- Delete the thread.
- Confirm related logs and captures are removed and the bottom-right product text is not clipped.

## Structured Automation

- Run the UIA diagnostic or smoke command for root, focused element, element at point, and active-window descendants.
- Confirm element properties include name, automation id, class name, control type, bounds, enabled state, keyboard focus, runtime id, and process id when available.
- Confirm available patterns are listed for common buttons and edit fields.
- Confirm UIA unavailability is logged and the run continues through Win32 or vision fallback.

## Browser Adapter

- In a developer/test environment with a connected Playwright page, confirm locator-first order starts with role locators.
- Confirm CDP fallback is used only after locator operation failure.
- In a normal release environment without Playwright, confirm startup, settings, tests, and the packaged app still work.

## Background Controls

- Start a run and minimize AutoCruise CE.
- Press `F8` and confirm the run pauses.
- Press `F8` again or Resume and confirm the run continues.
- Press `F12` and confirm the run stops cleanly.
