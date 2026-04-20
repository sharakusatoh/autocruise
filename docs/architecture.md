# AutoCruise Architecture

## Product Definition

AutoCruise CE is a Windows desktop application for autonomous GUI operation. The main screen focuses on the goal input, current state, current activity, compact pause/stop controls, screenshot preview, thread history, knowledge, schedules, settings, and diagnostics. The AI runtime is Codex App Server with ChatGPT sign-in.

## Technical Selection

### Why Python + PySide6

- PySide6 provides a real Windows desktop UI with better input-method behavior than a minimal widget toolkit.
- The codebase can call Win32 APIs through `ctypes` for screenshots, windows, keyboard, mouse, clipboard, and hotkeys.
- PowerShell is used only for the Microsoft UI Automation client layer where .NET UIA APIs are the most direct Windows path.
- PyInstaller can produce a portable Windows folder and optional installer package from the same codebase.

### Why Structured Automation First

Desktop automation is not reliable if every step depends on image coordinates. AutoCruise CE therefore prefers structured adapters before vision:

1. UIA for native Windows controls, element properties, and control patterns.
2. Win32 for screenshots, windows, pointer, keyboard, clipboard, and global hotkeys.
3. Playwright only when an integration supplies a live browser page object.
4. CDP DOM / Accessibility / Input domains only as a browser fallback.
5. Vision for remaining areas such as canvases, custom-rendered controls, and coordinate-level drawing.

Playwright and browser binaries are optional and are not bundled in the standard package.

## Layered Architecture

### Presentation Layer

- `presentation/app.py`
- `presentation/ui/shell.py`
- PySide6 main window, manager panels, compact floating controls, tray integration, settings, thread history, schedules, and diagnostics.

### Application Layer

- `application/orchestrator.py`
- `application/state_machine.py`
- `application/retrieval.py`
- `application/live_planner.py`
- Session lifecycle, prompt retrieval, planning, execution loop, validation, and recovery.

### Domain Layer

- `domain/models.py`
- `domain/automation.py`
- Typed observations, actions, session states, execution results, scheduled jobs, retrieval decisions, and cross-backend automation interfaces.

### Infrastructure Layer

- `infrastructure/providers.py`
- `infrastructure/codex_app_server.py`
- `infrastructure/storage.py`
- `infrastructure/windows/*`
- `infrastructure/browser/*`
- Codex connection, JSON/JSONL/YAML storage, screenshot capture, window enumeration, UIA client layer, Win32 input execution, optional Playwright/CDP adapters, and visual guidance.

## State Machine

Explicit states:

- `IDLE`
- `LOADING_CONTEXT`
- `OBSERVING`
- `PLANNING`
- `PRECHECK`
- `EXECUTING`
- `POSTCHECK`
- `REPLANNING`
- `PAUSED`
- `STOPPED`
- `FAILED`
- `COMPLETED`

Rules:

- Every transition is validated against an allowed transition map.
- Every transition is persisted to `logs/audit_log.jsonl`.
- Unexpected transitions stop the run with a diagnostic reason.
- The orchestrator executes one concrete action per planning cycle, then re-observes.

## Execution Loop

1. Interpret the user goal.
2. Select the constitution, selected system prompt, and custom instruction files.
3. Capture a screenshot and visible window state.
4. Query UIA for root, focused element, active-window descendants, and target candidates.
5. Add optional Playwright/CDP state when a connected browser page is available.
6. Build the observation payload for Codex.
7. Ask Codex for the next action.
8. Re-observe in `PRECHECK`.
9. Resolve the target through UIA / browser adapter / visual target fallback.
10. Execute one action through the best available backend.
11. Re-observe in `POSTCHECK`.
12. Validate visible progress, replan, complete, or stop with an issue record.

## Automation Interface

The shared automation interface provides:

- Enumerate elements.
- Find elements.
- Get root / focused / element-at-point / active-window descendants.
- Get element state.
- List available operations.
- Click.
- Input text.
- Select.
- Scroll.

UIA element state includes `Name`, `AutomationId`, `ClassName`, `ControlType`, `BoundingRectangle`, `IsEnabled`, `HasKeyboardFocus`, `RuntimeId`, `ProcessId`, and detected patterns. The UIA client uses `CacheRequest` to prefetch properties and pattern availability to reduce repeated cross-process calls.

Supported pattern abstraction:

- `Invoke`
- `Value`
- `SelectionItem`
- `ExpandCollapse`
- `Toggle`
- `Scroll`
- `Text`
- `Window`
- `LegacyIAccessible`

## Browser Adapter

The browser adapter is locator-first:

1. `getByRole`
2. `getByLabel`
3. `getByText`
4. `getByPlaceholder`
5. `getByAltText`
6. `getByTitle`

If locator operations fail and CDP is available, the adapter can use CDP `DOM`, `Accessibility`, and `Input` domains for targeted fallback operations. If no browser page is connected, the adapter reports unavailable and the desktop loop continues through UIA / Win32 / vision.

## Prompt Context Model

Priority order:

1. Constitution
2. Session mission
3. Selected system prompt
4. User custom prompt and custom prompt files
5. Runtime observation
6. Recent execution context

No other bundled prompt-source categories are loaded into the model context in this edition.

## Logging and Storage

- `logs/execution_log.jsonl`: step-level execution records
- `logs/audit_log.jsonl`: state transitions, retrieval decisions, automation diagnostics, and issue records
- `screenshots/session_{id}/`: screenshot capture per session

Screenshot retention:

- Default TTL is configurable in user preferences.
- Important screenshots can be retained longer for diagnosis.
- Cleanup runs on session startup and can also be triggered from the UI.

## Settings

The settings screen includes:

- Language
- Autonomy mode
- Optional maximum step count, blank by default for unlimited runs
- Pause and stop hotkeys
- Codex App Server status
- ChatGPT sign-in / sign-out
- Codex model
- Reasoning effort
- Planning response size
- Screenshot retention
- History display size

## Distribution

`build_windows.bat` produces the PyInstaller folder, portable ZIP, and installer when Inno Setup is installed. The package includes the UIA PowerShell scripts, docs, prompt assets, icon assets, and default user configuration.

Before release, run the checks in `docs/release_qa_checklist.md`.
