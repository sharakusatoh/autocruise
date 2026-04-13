from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from autocruise.domain.models import (
    Action,
    ActionType,
    Bounds,
    ExpectedSignal,
    ExpectedSignalKind,
    Observation,
    ObservationKind,
    PlanStep,
    PointerPoint,
    PointerStroke,
    RetrievedContext,
    RiskLevel,
    TargetRef,
)
from autocruise.infrastructure.providers import ProviderError, ProviderRegistry
from autocruise.infrastructure.storage import ProviderSettingsRepository, SecureSecretStore

CONTEXTUAL_RUN_ALIASES = {
    "paint": {"display": "Paint", "command": "mspaint", "terms": ("paint", "mspaint", "ペイント")},
    "gimp": {"display": "GIMP", "command": "gimp", "terms": ("gimp",)},
    "notepad": {"display": "Notepad", "command": "notepad", "terms": ("notepad", "メモ帳")},
    "calculator": {"display": "Calculator", "command": "calc", "terms": ("calculator", "calc", "電卓")},
    "file_explorer": {"display": "File Explorer", "command": "explorer", "terms": ("file explorer", "explorer", "エクスプローラー")},
    "excel": {"display": "Excel", "command": "excel", "terms": ("excel", "エクセル")},
    "word": {"display": "Word", "command": "winword", "terms": ("word", "ワード")},
    "powerpoint": {"display": "PowerPoint", "command": "powerpnt", "terms": ("powerpoint", "power point", "パワポ")},
    "outlook": {"display": "Outlook", "command": "outlook", "terms": ("outlook", "メール", "outlook メール")},
    "edge": {"display": "Microsoft Edge", "command": "msedge", "terms": ("edge", "microsoft edge", "ブラウザ")},
    "chrome": {"display": "Chrome", "command": "chrome", "terms": ("chrome", "グーグルクローム")},
    "terminal": {"display": "Windows Terminal", "command": "wt", "terms": ("terminal", "windows terminal", "powershell", "cmd", "ターミナル")},
    "vscode": {"display": "Visual Studio Code", "command": "code", "terms": ("vscode", "visual studio code", "vs code")},
}


class LiveActionPlanner:
    def __init__(
        self,
        provider_repo: ProviderSettingsRepository,
        secret_store: SecureSecretStore,
        provider_registry: ProviderRegistry,
        notice_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.provider_repo = provider_repo
        self.secret_store = secret_store
        self.provider_registry = provider_registry
        self.notice_callback = notice_callback
        self._last_notice = ""

    def plan(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        context: RetrievedContext | dict[str, Any] | None,
    ) -> PlanStep | None:
        retrieved_context, planning_meta = self._normalize_context(context)
        settings = self.provider_repo.get_default()
        api_key = self.secret_store.load_api_key(settings.provider)

        if not settings.base_url.strip() or not settings.model.strip():
            self._notice("AI connection is not configured. Complete the provider settings first.")
            return None

        if settings.provider not in {"local", "codex"} and not api_key.strip():
            self._notice("AI connection is not configured. Complete the provider settings first.")
            return None

        try:
            response_text = self.provider_registry.get(settings.provider).generate_text(
                settings=settings,
                api_key=api_key,
                instructions=self._build_instructions(goal, retrieved_context),
                prompt=self._build_prompt(goal, observation, recent_actions, retrieved_context, planning_meta),
                image_path=self._image_for_observation(observation),
                session_key=str(planning_meta.get("session_id", "")).strip() or None,
                output_schema=self._output_schema(),
            )
            plan = self._parse_plan(response_text)
            self._last_notice = ""
            return plan
        except ProviderError as exc:
            self._notice(f"{exc.user_message} Continuing with fallback mode.")
            return None
        except Exception:
            self._notice("The AI connection could not be verified. Continuing with fallback mode.")
            return None

    def _build_instructions(self, goal: str, context: RetrievedContext | None) -> str:
        launch_hint = self._build_launch_hint(goal, context)
        return (
            "You are the autopilot planner for a Windows desktop GUI agent. "
            "Return exactly one next action or declare completion. "
            "Keep advancing toward the user's goal until it is visibly complete or truly blocked. "
            "Use short strings to minimize tokens. "
            "Do not stop early just because one step succeeded. "
            "Do not ask the user for confirmation. Keep moving. "
            "Always think at two levels: the overall objective route and the immediate next step. "
            "Treat browsers like any other Windows application. "
            "If the requested app is not open, launch it immediately using the shortest reliable Windows path. "
            "For known Windows apps with a direct executable alias, prefer shell_execute with shell_kind process before using Win+R or Search. "
            f"{launch_hint}"
            "Use Search only when Run or a visible launcher item is not enough. Do not bounce between opening and closing Search. "
            "If one launcher path fails, switch to another direct path on the next step. "
            "If the app is starting, use wait only until the target UI is visible. "
            "Once the app is open, continue with the next concrete step such as selecting a tool, focusing a field, typing text, or drawing on a canvas. "
            "Use whichever combination of mouse, keyboard, menus, ribbons, toolbars, dialogs, shortcuts, and visible text gets to the goal fastest. "
            "Use shell_execute when a terminal or direct process launch is faster and more reliable than GUI interaction. "
            "Prefer shell_execute for development tasks, repository inspection, tests, builds, file-system bulk operations, and direct executable launch. "
            "Use shell_kind powershell for Windows shell commands, cmd for cmd-style commands, and process to launch an executable directly. "
            "If shell_execute does not need a visible UI change, leave expected_signals empty and keep wait_timeout_ms short. "
            "If shell_execute should open an app window, use shell_kind process and set the target window title when you know it. "
            "If shell_cwd is empty, the command will run in the current AutoCruise workspace root. "
            "Use type_text only for a focused or clearly editable field. Do not point type_text at buttons or launcher controls. "
            "After WIN+S opens Windows Search, assume the search field already has keyboard focus unless the screenshot clearly shows otherwise. "
            "Use hotkey for Enter, Tab, Escape, arrow keys, function keys, and modifier combinations. "
            "For drawing or painting tasks, think in vector-like strokes. "
            "Before drawing, choose the tool and settings, then compute the stroke plan. "
            "Prefer pointer_script for drawing tasks so one action can execute multiple left-button strokes in sequence. "
            "Use one drag action per stroke only when pointer_script is unavailable and include a plan_outline with the next 2 to 5 milestones. "
            "When the target is a canvas, prefer drag_coordinate_mode relative and express drag_path in canvas-relative coordinates from 0 to 1000 on each axis. "
            "For pointer_script on a canvas, prefer relative coordinates from 0 to 1000 on each axis for every stroke. "
            "Approximate curves with 6 to 16 points, not just 2 or 3 points. "
            "For Paint tasks, after the window appears, choose Pencil or Brush and build the sketch in visible subgoals such as head outline, ears, face, body, and tail. "
            "For business tasks, prefer standard shortcuts, clearly labeled controls, and the fastest direct route before deeper navigation. "
            "Save, export, send, or submit when that is the obvious completion state for the user's goal. "
            "The request may include a real desktop screenshot of the current screen. When a screenshot is available, use it as the primary visual truth. "
            "Prefer structured automation data before visual guessing: UI Automation on Windows, then Playwright locators for browser pages, then CDP, then vision fallback. "
            "Use vision-only coordinates only for regions that UIA, Playwright, and CDP cannot expose. "
            "The screenshot may include a cursor marker and an active-window outline. "
            "Treat those overlays and the structured visual_guides payload as trustworthy hints about global Windows screen coordinates. "
            "If visual_guides are present, remember that screenshot pixel (0,0) maps to the reported screen origin, not always to global (0,0). "
            "Use the cursor marker and active-window bounds to estimate precise click, drag, and drawing coordinates. "
            "When screenshot input is unavailable, rely on the UI automation summary and textual hints instead. "
            "If the sensor snapshot is unchanged, do not ask for a fresh image. Reuse the structured observation and keep moving. "
            "Always populate expected_signals with the cheapest observable UI changes for the chosen action. "
            "Prefer signals that UIA, Playwright, or CDP can verify before using vision_change. "
            "When screen_understanding.ui_candidates is present, prefer those numbered UI candidates before visual guessing. "
            "Treat screen_understanding.ocr_text_blocks as a separate channel from UI automation data. "
            "If there is no exact target, choose the most progress-making action: focus the likely window, click a "
            "clearly labeled control, type into a visible edit field, use a launcher shortcut, scroll, or wait briefly. "
            "Prefer UI automation targets, labeled controls, shortcuts, visual hints, then coordinates. "
            "Return only valid JSON matching the provided output schema."
        )

    def _build_launch_hint(self, goal: str, context: RetrievedContext | None) -> str:
        relevant: list[tuple[str, str]] = []
        seen: set[str] = set()
        goal_candidates = self._goal_alias_candidates(goal)
        for app_name in goal_candidates:
            alias = CONTEXTUAL_RUN_ALIASES.get(app_name)
            if alias is None or app_name in seen:
                continue
            seen.add(app_name)
            relevant.append((alias["display"], alias["command"]))
        if not goal_candidates:
            for app_name in getattr(context, "app_candidates", []) or []:
                alias = CONTEXTUAL_RUN_ALIASES.get(app_name)
                if alias is None or app_name in seen:
                    continue
                seen.add(app_name)
                relevant.append((alias["display"], alias["command"]))

        if relevant:
            alias_text = ", ".join(f"{display} -> {command}" for display, command in relevant[:4])
            return (
                f"For this task, use Win+R with these relevant aliases: {alias_text}. "
                "Use only a relevant alias for this task. Do not type unrelated app names or commands. "
            )

        return (
            "When a known Windows app is clearly requested, prefer Win+R with that app's own executable alias. "
            "Do not type unrelated commands or unrelated app names. "
        )

    def _goal_alias_candidates(self, goal: str) -> list[str]:
        normalized_goal = goal.lower()
        matches: list[tuple[int, int, str]] = []
        for app_name, spec in CONTEXTUAL_RUN_ALIASES.items():
            score = 0
            longest = 0
            explicit_terms = {app_name.replace("_", " "), spec["display"].lower(), spec["command"].lower()}
            explicit_terms.update(term.lower() for term in spec.get("terms", ()) if term)
            for term in explicit_terms:
                if term and term in normalized_goal:
                    score += 1
                    longest = max(longest, len(term))
            if score:
                matches.append((score, longest, app_name))
        matches.sort(reverse=True)
        return [app_name for _, _, app_name in matches]

    def _build_prompt(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        context: RetrievedContext | None,
        planning_meta: dict[str, Any],
    ) -> str:
        visible_windows = [{"title": item.title, "class_name": item.class_name} for item in observation.visible_windows[:5]]
        detected_elements = [
            {
                "name": item.name,
                "automation_id": item.automation_id,
                "control_type": item.control_type,
                "bounds": asdict(item.bounds) if item.bounds else None,
            }
            for item in observation.detected_elements[:8]
        ]
        visual_guides = observation.raw_ref.get("visual_guides", {}) if isinstance(observation.raw_ref, dict) else {}
        screen_bounds = observation.raw_ref.get("screen_bounds", {}) if isinstance(observation.raw_ref, dict) else {}
        automation = observation.raw_ref.get("automation", {}) if isinstance(observation.raw_ref, dict) else {}
        screen_understanding = observation.raw_ref.get("screen_understanding", {}) if isinstance(observation.raw_ref, dict) else {}
        sensor_snapshot = observation.raw_ref.get("sensor_snapshot", {}) if isinstance(observation.raw_ref, dict) else {}
        last_execution = observation.raw_ref.get("last_execution", {}) if isinstance(observation.raw_ref, dict) else {}
        observation_kind = observation.raw_ref.get("observation_kind", ObservationKind.FULL.value) if isinstance(observation.raw_ref, dict) else ObservationKind.FULL.value
        change_summary = observation.raw_ref.get("change_summary", "") if isinstance(observation.raw_ref, dict) else ""
        knowledge = []
        if context:
            for selection in context.selections[:4]:
                knowledge.append(
                    {
                        "kind": selection.kind,
                        "path": Path(selection.path).name,
                        "reason": selection.reason,
                        "excerpt": selection.excerpt[:200],
                    }
                )

        return json.dumps(
            {
                "goal": goal,
                "autopilot_mode": True,
                "autonomy_mode": planning_meta.get("autonomy_mode", "autonomous"),
                "planning_style": "Maintain an overall route, choose the next best step, then re-observe.",
                "confirmation_policy": planning_meta.get(
                    "confirmation_policy",
                    "Do not ask the user. Keep executing until the goal is complete or blocked.",
                ),
                "step_count": planning_meta.get("step_count", 0),
                "remaining_step_budget": planning_meta.get("remaining_steps", 0),
                "recent_failure_reason": planning_meta.get("recent_failure_reason", ""),
                "recent_failure_count": planning_meta.get("recent_failure_count", 0),
                "active_window": observation.active_window.title if observation.active_window else "",
                "active_window_bounds": (
                    asdict(observation.active_window.bounds)
                    if observation.active_window is not None and observation.active_window.bounds is not None
                    else None
                ),
                "screen_bounds": screen_bounds,
                "observation_kind": observation_kind,
                "change_summary": change_summary,
                "sensor_snapshot": sensor_snapshot,
                "cursor_position": {"x": observation.cursor_position[0], "y": observation.cursor_position[1]},
                "visual_guides": visual_guides,
                "automation": {
                    "priority": automation.get("priority", ["uia", "playwright", "cdp", "vision"]),
                    "source": automation.get("source", ""),
                    "vision_fallback_allowed": automation.get("vision_fallback_allowed", True),
                    "elements": (automation.get("elements") or [])[:8],
                },
                "screen_understanding": {
                    "ui_candidates": (screen_understanding.get("ui_candidates") or [])[:8],
                    "ocr_text_blocks": (screen_understanding.get("ocr_text_blocks") or [])[:12],
                    "ocr_available": bool(screen_understanding.get("ocr_available", False)),
                },
                "last_action_result": {
                    "success": bool(last_execution.get("success", False)),
                    "details": str(last_execution.get("details", ""))[:400],
                    "error": str(last_execution.get("error", ""))[:300],
                    "payload": {
                        "kind": str((last_execution.get("payload") or {}).get("kind", ""))[:40],
                        "exit_code": (last_execution.get("payload") or {}).get("exit_code"),
                        "stdout": str((last_execution.get("payload") or {}).get("stdout", ""))[:1000],
                        "stderr": str((last_execution.get("payload") or {}).get("stderr", ""))[:700],
                        "pid": (last_execution.get("payload") or {}).get("pid"),
                        "cwd": str((last_execution.get("payload") or {}).get("cwd", ""))[:240],
                        "detach": bool((last_execution.get("payload") or {}).get("detach", False)),
                    },
                },
                "ui_summary": observation.ui_tree_summary[:700],
                "focused_element": observation.focused_element,
                "textual_hints": observation.textual_hints[:5],
                "visible_windows": visible_windows,
                "detected_elements": detected_elements,
                "recent_actions": [
                    {
                        "type": action.type.value,
                        "target": action.target.name or action.target.window_title,
                        "purpose": action.purpose,
                        "expected_outcome": action.expected_outcome,
                    }
                    for action in recent_actions[-4:]
                ],
                "context_apps": context.app_candidates if context else [],
                "context_tasks": context.task_candidates if context else [],
                "knowledge": knowledge,
                "drawing_guidance": {
                    "coordinate_space": "If a canvas target is visible, drag_coordinate_mode relative means 0..1000 mapped inside target bounds.",
                    "curve_guidance": "Use multiple points for arcs and curves instead of one straight segment.",
                    "stroke_policy": "One visible stroke per action, then re-observe.",
                },
            },
            ensure_ascii=False,
        )

    def _parse_plan(self, response_text: str) -> PlanStep:
        payload = self._extract_json(response_text)
        if bool(payload.get("is_complete")):
            summary = str(payload.get("summary") or "Completed.")
            return PlanStep(
                summary=summary,
                is_complete=True,
                completion_reason=str(payload.get("completion_reason") or summary),
                reasoning=str(payload.get("reasoning") or "live-provider"),
                plan_outline=self._parse_plan_outline(payload.get("plan_outline")),
            )

        action_payload = payload.get("action") or {}
        action_type = ActionType(str(action_payload.get("type", "wait")))
        target_payload = action_payload.get("target") or {}
        bounds_payload = target_payload.get("bounds") or None
        bounds = None
        if isinstance(bounds_payload, dict) and {"left", "top", "width", "height"} <= set(bounds_payload):
            bounds = Bounds(
                left=int(bounds_payload["left"]),
                top=int(bounds_payload["top"]),
                width=int(bounds_payload["width"]),
                height=int(bounds_payload["height"]),
            )

        action = Action(
            type=action_type,
            target=TargetRef(
                window_title=str(target_payload.get("window_title", "")),
                automation_id=str(target_payload.get("automation_id", "")),
                name=str(target_payload.get("name", "")),
                control_type=str(target_payload.get("control_type", "")),
                bounds=bounds,
                fallback_visual_hint=str(target_payload.get("fallback_visual_hint", "")),
            ),
            purpose=str(action_payload.get("purpose", "")),
            reason=str(action_payload.get("reason", "")),
            preconditions=[str(item) for item in action_payload.get("preconditions", [])][:6],
            expected_outcome=str(action_payload.get("expected_outcome", "")),
            risk_level=RiskLevel(str(action_payload.get("risk_level", "low"))),
            confidence=max(0.0, min(float(action_payload.get("confidence", 0.5)), 1.0)),
            text=str(action_payload.get("text", "")),
            hotkey=str(action_payload.get("hotkey", "")),
            scroll_amount=int(action_payload.get("scroll_amount", 0) or 0),
            drag_coordinate_mode=self._parse_drag_coordinate_mode(action_payload.get("drag_coordinate_mode")),
            drag_path=self._parse_drag_path(action_payload.get("drag_path")),
            drag_duration_ms=max(0, int(action_payload.get("drag_duration_ms", 0) or 0)),
            pointer_script=self._parse_pointer_script(action_payload.get("pointer_script")),
            shell_kind=self._parse_shell_kind(action_payload.get("shell_kind")),
            shell_command=str(action_payload.get("shell_command", "")),
            shell_cwd=str(action_payload.get("shell_cwd", "")),
            shell_timeout_seconds=max(0, int(action_payload.get("shell_timeout_seconds", 0) or 0)),
            shell_detach=bool(action_payload.get("shell_detach", False)),
            expected_signals=self._parse_expected_signals(action_payload.get("expected_signals")),
            wait_timeout_ms=max(0, int(action_payload.get("wait_timeout_ms", 0) or 0)),
        )
        if not action.expected_signals:
            action.expected_signals = self._default_expected_signals(action)
        if action.wait_timeout_ms <= 0:
            action.wait_timeout_ms = self._default_wait_timeout_ms(action)
        return PlanStep(
            summary=str(payload.get("summary") or action.purpose or "Proceed to the next step."),
            action=action,
            reasoning=str(payload.get("reasoning") or "live-provider"),
            plan_outline=self._parse_plan_outline(payload.get("plan_outline")),
        )

    def _parse_expected_signals(self, payload: Any) -> list[ExpectedSignal]:
        if not isinstance(payload, list):
            return []
        signals: list[ExpectedSignal] = []
        for item in payload[:6]:
            if isinstance(item, dict):
                kind_name = str(item.get("kind", "")).strip().lower()
                target = str(item.get("target", "")).strip()
                detail = str(item.get("detail", "")).strip()
            else:
                kind_name = str(item).strip().lower()
                target = ""
                detail = ""
            try:
                kind = ExpectedSignalKind(kind_name)
            except ValueError:
                continue
            signals.append(ExpectedSignal(kind=kind, target=target, detail=detail))
        return signals

    def _default_expected_signals(self, action: Action) -> list[ExpectedSignal]:
        target_label = action.target.name or action.target.automation_id or action.target.window_title
        if action.type == ActionType.SHELL_EXECUTE:
            if action.shell_kind == "process":
                return [ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=target_label or action.shell_command)]
            return []
        if action.type == ActionType.CLICK:
            return [
                ExpectedSignal(ExpectedSignalKind.ELEMENT_ENABLED_CHANGED, target=target_label),
                ExpectedSignal(ExpectedSignalKind.DIALOG_OPENED, target=target_label),
                ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=target_label),
            ]
        if action.type == ActionType.TYPE_TEXT:
            return [
                ExpectedSignal(ExpectedSignalKind.VALUE_CHANGED, target=target_label),
                ExpectedSignal(ExpectedSignalKind.TEXT_CHANGED, target=target_label),
            ]
        if action.type == ActionType.SCROLL:
            return [ExpectedSignal(ExpectedSignalKind.ELEMENT_APPEARED, target=target_label)]
        if action.type == ActionType.DRAG:
            return [ExpectedSignal(ExpectedSignalKind.VISION_CHANGE, target=target_label)]
        return [ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=target_label or action.type.value)]

    def _default_wait_timeout_ms(self, action: Action) -> int:
        if action.type == ActionType.SHELL_EXECUTE:
            if action.shell_kind == "process":
                return 2500
            return 200
        if action.type == ActionType.DRAG:
            return 900
        if action.type == ActionType.HOTKEY:
            return 2000
        if action.type == ActionType.WAIT:
            return 1200
        return 1800

    def _image_for_observation(self, observation: Observation) -> str | None:
        if not observation.screenshot_path:
            return None
        raw_ref = observation.raw_ref if isinstance(observation.raw_ref, dict) else {}
        observation_kind = str(raw_ref.get("observation_kind", ObservationKind.FULL.value))
        vision_required = bool(raw_ref.get("vision_fallback_required", False))
        if observation_kind != ObservationKind.FULL.value and not vision_required:
            return None
        return observation.screenshot_path

    def _output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "reasoning": {"type": "string"},
                "plan_outline": {"type": "array", "items": {"type": "string"}},
                "is_complete": {"type": "boolean"},
                "completion_reason": {"type": "string"},
                "action": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "type": {"type": "string"},
                        "target": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "window_title": {"type": "string"},
                                "automation_id": {"type": "string"},
                                "name": {"type": "string"},
                                "control_type": {"type": "string"},
                                "bounds": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "left": {"type": "integer"},
                                        "top": {"type": "integer"},
                                        "width": {"type": "integer"},
                                        "height": {"type": "integer"},
                                    },
                                    "required": ["left", "top", "width", "height"],
                                },
                                "fallback_visual_hint": {"type": "string"},
                            },
                            "required": ["window_title", "automation_id", "name", "control_type", "fallback_visual_hint"],
                        },
                        "purpose": {"type": "string"},
                        "reason": {"type": "string"},
                        "preconditions": {"type": "array", "items": {"type": "string"}},
                        "expected_outcome": {"type": "string"},
                        "risk_level": {"type": "string"},
                        "confidence": {"type": "number"},
                        "text": {"type": "string"},
                        "hotkey": {"type": "string"},
                        "scroll_amount": {"type": "integer"},
                        "drag_coordinate_mode": {"type": "string"},
                        "drag_path": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "x": {"type": "integer"},
                                    "y": {"type": "integer"},
                                },
                                "required": ["x", "y"],
                            },
                        },
                        "drag_duration_ms": {"type": "integer"},
                        "pointer_script": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "coordinate_mode": {"type": "string"},
                                    "duration_ms": {"type": "integer"},
                                    "pause_after_ms": {"type": "integer"},
                                    "button": {"type": "string"},
                                    "path": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "additionalProperties": False,
                                            "properties": {
                                                "x": {"type": "integer"},
                                                "y": {"type": "integer"},
                                            },
                                            "required": ["x", "y"],
                                        },
                                    },
                                },
                                "required": ["coordinate_mode", "duration_ms", "pause_after_ms", "button", "path"],
                            },
                        },
                        "shell_kind": {"type": "string"},
                        "shell_command": {"type": "string"},
                        "shell_cwd": {"type": "string"},
                        "shell_timeout_seconds": {"type": "integer"},
                        "shell_detach": {"type": "boolean"},
                        "wait_timeout_ms": {"type": "integer"},
                        "expected_signals": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "kind": {"type": "string"},
                                    "target": {"type": "string"},
                                    "detail": {"type": "string"},
                                },
                                "required": ["kind"],
                            },
                        },
                    },
                    "required": [
                        "type",
                        "target",
                        "purpose",
                        "reason",
                        "preconditions",
                        "expected_outcome",
                        "risk_level",
                        "confidence",
                        "text",
                        "hotkey",
                        "scroll_amount",
                        "drag_coordinate_mode",
                        "drag_path",
                        "drag_duration_ms",
                        "pointer_script",
                        "shell_kind",
                        "shell_command",
                        "shell_cwd",
                        "shell_timeout_seconds",
                        "shell_detach",
                        "wait_timeout_ms",
                        "expected_signals",
                    ],
                },
            },
            "required": ["summary", "reasoning", "plan_outline", "is_complete", "completion_reason"],
        }

    def _extract_json(self, text: str) -> dict:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise ValueError("Planner response did not contain JSON")

    def _parse_drag_path(self, payload: Any) -> list[PointerPoint]:
        if not isinstance(payload, list):
            return []
        points: list[PointerPoint] = []
        for item in payload[:20]:
            if isinstance(item, dict) and {"x", "y"} <= set(item):
                points.append(PointerPoint(x=int(item["x"]), y=int(item["y"])))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                points.append(PointerPoint(x=int(item[0]), y=int(item[1])))
        if len(points) == 1 and points[0] == PointerPoint(0, 0):
            return []
        return points

    def _parse_pointer_script(self, payload: Any) -> list[PointerStroke]:
        if not isinstance(payload, list):
            return []
        strokes: list[PointerStroke] = []
        for item in payload[:16]:
            if not isinstance(item, dict):
                continue
            path = self._parse_drag_path(item.get("path"))
            if len(path) < 2:
                continue
            strokes.append(
                PointerStroke(
                    path=path,
                    coordinate_mode=self._parse_drag_coordinate_mode(item.get("coordinate_mode")),
                    duration_ms=max(0, int(item.get("duration_ms", 0) or 0)),
                    pause_after_ms=max(0, int(item.get("pause_after_ms", 0) or 0)),
                    button=str(item.get("button", "left") or "left").strip().lower() or "left",
                )
            )
        return strokes

    def _parse_drag_coordinate_mode(self, value: Any) -> str:
        normalized = str(value or "absolute").strip().lower()
        if normalized in {"relative", "canvas_relative", "normalized"}:
            return "relative"
        return "absolute"

    def _parse_shell_kind(self, value: Any) -> str:
        normalized = str(value or "powershell").strip().lower()
        if normalized in {"powershell", "cmd", "process"}:
            return normalized
        return "powershell"

    def _parse_plan_outline(self, payload: Any) -> list[str]:
        if not isinstance(payload, list):
            return []
        outline: list[str] = []
        for item in payload[:5]:
            text = str(item).strip()
            if text:
                outline.append(text)
        return outline

    def _normalize_context(
        self,
        context: RetrievedContext | dict[str, Any] | None,
    ) -> tuple[RetrievedContext | None, dict[str, Any]]:
        if isinstance(context, dict):
            retrieved = context.get("retrieved_context")
            return (retrieved if isinstance(retrieved, RetrievedContext) else None), context
        return context, {}

    def _notice(self, message: str) -> None:
        if message == self._last_notice:
            return
        self._last_notice = message
        if self.notice_callback is not None:
            self.notice_callback(message)
