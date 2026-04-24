# AutoCruise Architecture

## Product Definition

AutoCruise CE is a Windows desktop application for autonomous GUI operation. The main screen focuses on the goal input, current state, current activity, compact pause/stop controls, screenshot preview, thread history, knowledge, schedules, settings, and diagnostics. The AI runtime is Codex App Server with ChatGPT sign-in.

## Technical Selection

### Why Python + PySide6

- PySide6 provides a real Windows desktop UI with better input-method behavior than a minimal widget toolkit.
- The codebase can call Win32 APIs through `ctypes` for screenshots, windows, keyboard, mouse, clipboard, and hotkeys.
- PowerShell is used only for the Microsoft UI Automation client layer where .NET UIA APIs are the most direct Windows path.
- PyInstaller produces the portable Windows folder used for releases.

### Why Smart Windows Operator First

Desktop automation is not reliable if every step depends on screenshots and coordinates. AutoCruise CE therefore chooses the richest direct control surface available before falling back to visual input:

- App-specific APIs and object models first. Microsoft Office tasks should use COM/Object Model access for workbooks, cells, documents, messages, calendars, selections, and attachments before touching the UI.
- Browser automation for Edge, Chrome, Chromium, and web apps. Playwright locators are preferred, with CDP DOM / Runtime / Network / Input / Event domains as targeted fallback.
- PowerShell CIM/WMI and native management cmdlets for OS and administration data such as processes, services, devices, network state, registry, installed software, and settings.
- UIA for normal Windows desktop apps without a richer app API.
- MSAA or targeted Win32 messages for legacy controls when UIA is weak and the exact control/message is known.
- Vision, OCR, screenshots, raw keyboard, mouse, and coordinates only as the final fallback.

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
- Codex model selection is fixed to `gpt-5.5`; stored provider settings are normalized to that model before use.

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
3. Capture the active Windows state, structured automation state, and screenshot fallback evidence.
4. Query the direct-control stack: app object models, browser automation, OS management APIs, UIA, and legacy control paths where available.
5. Build the observation payload for Codex.
6. Ask Codex for the next action.
7. Re-observe in `PRECHECK`.
8. Resolve the target through the best available direct backend before visual fallback.
9. Execute one action through the best available backend.
10. Re-observe in `POSTCHECK`.
11. Validate visible progress, replan, complete, or stop with an issue record.

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

Prompt sources:

- Constitution
- Selected system prompt
- User custom prompt and custom prompt files

Runtime inputs:

- Current session mission
- Current screen observation

Session history, thread history, audit logs, execution logs, and learning-memory sources are not loaded into the model context in this edition. Each Codex App Server call starts a fresh thread.

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
- Pause and stop hotkeys
- Codex App Server status
- ChatGPT sign-in / sign-out
- Fixed Codex model: `gpt-5.5`
- Reasoning effort
- Planning response size
- Screenshot retention
- History display size

## Distribution

`build_windows.bat` produces the PyInstaller folder and portable ZIP. AutoCruise CE no longer builds or publishes an installer. The package includes the UIA PowerShell scripts, docs, prompt assets, icon assets, and default user configuration.

Before release, run the checks in `docs/release_qa_checklist.md`.
