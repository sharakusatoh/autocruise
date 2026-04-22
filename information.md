# AutoCruise CE Information

AutoCruise CE is an experimental Windows desktop operator that uses Codex App Server with ChatGPT sign-in. It observes the desktop, asks Codex for the next concrete action, executes through UIA / Win32 / optional browser adapters / vision fallback, and repeats until the goal is complete or the run stops.

## Prompt Context

The model context is intentionally small:

1. User instruction
2. `constitution/constitution.md`
3. Selected system prompt from `users/default/systemprompt/`
4. Custom instructions from `users/default/user_custom_prompt.md` and `users/default/custom_prompts/*.md`

No other bundled prompt-source categories are loaded as model context.

## Main Capabilities

- Windows app launch, focus, click, drag, scroll, hotkeys, and text input
- Microsoft UI Automation element inspection and operation routing
- Win32 mouse, keyboard, clipboard, screenshot, window, and hotkey operations
- Optional Playwright/CDP browser adapter when a connected browser page is available
- Vision fallback for areas that UIA / browser adapters cannot inspect
- Manual runs and scheduled runs through Windows Task Scheduler

## Distribution

`build_windows.bat` creates the PyInstaller app folder and portable ZIP under `release/`. AutoCruise CE is distributed as a portable package only; no installer is built or published. The release package includes source-independent runtime files, UIA PowerShell support, docs, constitution, system prompts, custom prompts, README, and icon assets.
