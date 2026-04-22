from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtGui import QImage

from autocruise.domain.automation import AutomationBackend
from autocruise.domain.models import (
    Action,
    ActionType,
    ExpectedSignal,
    ExpectedSignalKind,
    ExecutionResult,
    Observation,
    ObservationKind,
    PlanStep,
    TargetRef,
    ValidationResult,
    VerificationResult,
)
from autocruise.infrastructure.automation import AutomationRouter
from autocruise.infrastructure.browser.sensor import BrowserSensorHub
from autocruise.infrastructure.windows.input_executor import InputExecutor
from autocruise.infrastructure.windows.observation_builder import WindowsObservationBuilder
from autocruise.infrastructure.windows.primary_sensor import PrimarySensorHub, observation_sensor_snapshot
from autocruise.infrastructure.windows.shell_executor import ShellExecutor
from autocruise.infrastructure.windows.uia_adapter import UIAAdapter
from autocruise.infrastructure.windows.window_manager import WindowManager


PRIMARY_ACTION_LABELS = {
    "start",
    "open",
    "next",
    "continue",
    "ok",
    "run",
    "apply",
    "search",
    "go",
    "done",
    "finish",
    "select",
    "開始",
    "開く",
    "次へ",
    "続行",
    "実行",
    "適用",
    "検索",
    "完了",
    "選択",
}
EDIT_CONTROL_HINTS = {"edit", "document", "text", "combo", "pane"}
RUN_DIALOG_HINTS = {"run", "ファイル名を指定して実行"}
APP_LAUNCH_SPECS = {
    "paint": {"display": "Paint", "command": "mspaint", "terms": ("paint", "ペイント", "mspaint"), "launch_strategy": "process"},
    "gimp": {"display": "GIMP", "command": "gimp", "terms": ("gimp",), "launch_strategy": "process"},
    "notepad": {"display": "Notepad", "command": "notepad", "terms": ("notepad", "メモ帳"), "launch_strategy": "process"},
    "calculator": {"display": "Calculator", "command": "calc", "terms": ("calculator", "電卓", "calc"), "launch_strategy": "process"},
    "excel": {"display": "Excel", "command": "excel", "terms": ("excel", "エクセル"), "launch_strategy": "process"},
    "word": {"display": "Word", "command": "winword", "terms": ("word", "ワード"), "launch_strategy": "process"},
    "powerpoint": {"display": "PowerPoint", "command": "powerpnt", "terms": ("powerpoint", "パワポ", "power point"), "launch_strategy": "process"},
    "outlook": {"display": "Outlook", "command": "outlook", "terms": ("outlook",), "launch_strategy": "process"},
    "edge": {"display": "Edge", "command": "msedge", "terms": ("edge", "microsoft edge"), "launch_strategy": "process"},
    "chrome": {"display": "Chrome", "command": "chrome", "terms": ("chrome",), "launch_strategy": "process"},
    "terminal": {"display": "Windows Terminal", "command": "wt", "terms": ("terminal", "windows terminal", "powershell", "cmd"), "launch_strategy": "process"},
    "vscode": {"display": "Visual Studio Code", "command": "code", "terms": ("vscode", "visual studio code", "vs code"), "launch_strategy": "process"},
    "file_explorer": {"display": "File Explorer", "command": "explorer", "terms": ("file explorer", "explorer", "エクスプローラー"), "launch_strategy": "process"},
}


class WindowsAgentToolset:
    def __init__(
        self,
        root: Path,
        observation_builder: WindowsObservationBuilder,
        window_manager: WindowManager,
        input_executor: InputExecutor,
        uia_adapter: UIAAdapter,
        live_planner=None,
        automation_router: AutomationRouter | None = None,
        browser_sensor: BrowserSensorHub | None = None,
        primary_sensor: PrimarySensorHub | None = None,
        shell_executor: ShellExecutor | None = None,
    ) -> None:
        self.root = root
        self.observation_builder = observation_builder
        self.window_manager = window_manager
        self.input_executor = input_executor
        self.uia_adapter = uia_adapter
        self.live_planner = live_planner
        self.browser_sensor = browser_sensor or getattr(observation_builder, "browser_sensor", None) or BrowserSensorHub()
        self.automation_router = automation_router or getattr(observation_builder, "automation_router", None) or AutomationRouter([uia_adapter])
        self.primary_sensor = primary_sensor or getattr(observation_builder, "primary_sensor", None) or PrimarySensorHub(
            window_manager,
            uia_adapter,
            self.browser_sensor,
        )
        self.shell_executor = shell_executor or ShellExecutor(root)

    def list_windows(self):
        return self.window_manager.list_windows()

    def focus_window(self, window_id: int) -> bool:
        return self.window_manager.focus_window(window_id)

    def find_elements(self, query: str):
        return self.uia_adapter.find_elements(query)

    def capture_observation(
        self,
        session_id: str,
        *,
        previous_observation: Observation | None = None,
        recent_actions: list[str] | None = None,
        force_full: bool = False,
    ) -> Observation:
        recent_actions = recent_actions or []
        sensor_started = time.monotonic()
        sensor_snapshot = self.primary_sensor.snapshot()
        sensor_poll_ms = int((time.monotonic() - sensor_started) * 1000)
        if previous_observation is not None and not force_full:
            previous_snapshot = observation_sensor_snapshot(previous_observation)
            if previous_snapshot is not None and previous_snapshot.fingerprint == sensor_snapshot.fingerprint and not sensor_snapshot.has_events:
                observation = self.observation_builder.reuse(previous_observation, sensor_snapshot=sensor_snapshot)
                observation.raw_ref["sensor_poll_ms"] = sensor_poll_ms
                observation.raw_ref["screenshot_count"] = 0
                observation.raw_ref["planner_skip_reason"] = "sensor_unchanged"
                return observation
            observation = self.observation_builder.refresh_structured(
                recent_actions,
                previous_observation=previous_observation,
                sensor_snapshot=sensor_snapshot,
            )
            observation.raw_ref["sensor_poll_ms"] = sensor_poll_ms
            observation.raw_ref["screenshot_count"] = 0
            return observation
        screenshot_dir = self.root / "screenshots" / f"session_{session_id}"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / f"screen_{uuid.uuid4().hex[:6]}.png"
        observation = self.observation_builder.capture_full(
            screenshot_path,
            recent_actions=recent_actions,
            previous_observation=previous_observation,
            sensor_snapshot=sensor_snapshot,
        )
        observation.raw_ref["sensor_poll_ms"] = sensor_poll_ms
        observation.raw_ref["screenshot_count"] = 1
        return observation

    def wait_for_expected_change(
        self,
        session_id: str,
        action: Action,
        previous_observation: Observation,
        *,
        recent_actions: list[str] | None = None,
        execution_result: ExecutionResult | None = None,
    ) -> Observation:
        recent_actions = recent_actions or []
        if action.type == ActionType.SHELL_EXECUTE:
            return self._wait_for_shell_completion(
                action,
                previous_observation,
                recent_actions=recent_actions,
                execution_result=execution_result,
            )
        previous_snapshot = observation_sensor_snapshot(previous_observation) or self.primary_sensor.snapshot()
        expected_signals = action.expected_signals or self._default_expected_signals(action)
        wait_started = time.monotonic()
        wait_result = self.primary_sensor.wait_for_expected_signals(
            previous_snapshot,
            expected_signals,
            timeout_ms=max(int(action.wait_timeout_ms or 0), 200),
        )
        if wait_result["matched"]:
            observation = self.observation_builder.refresh_structured(
                recent_actions,
                previous_observation=previous_observation,
                sensor_snapshot=wait_result["snapshot"],
            )
        elif self._requires_vision_fallback(action, previous_observation):
            screenshot_dir = self.root / "screenshots" / f"session_{session_id}"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = screenshot_dir / f"vision_{uuid.uuid4().hex[:6]}.png"
            observation = self.observation_builder.capture_vision_fallback(
                screenshot_path,
                recent_actions,
                previous_observation=previous_observation,
                sensor_snapshot=wait_result["snapshot"],
                target_bounds=action.target.bounds,
            )
        else:
            observation = self.observation_builder.refresh_structured(
                recent_actions,
                previous_observation=previous_observation,
                sensor_snapshot=wait_result["snapshot"],
            )
        observation.raw_ref["wait"] = {
            "matched": bool(wait_result["matched"]),
            "matched_signal": str(wait_result.get("matched_signal", "")),
            "wait_satisfied_by": str(wait_result.get("wait_satisfied_by", "")),
            "timeout_ms": int(action.wait_timeout_ms or 0),
            "elapsed_ms": int((time.monotonic() - wait_started) * 1000),
        }
        observation.raw_ref["wait_satisfied_by"] = observation.raw_ref["wait"]["wait_satisfied_by"]
        observation.raw_ref["browser_refresh_ms"] = 0
        observation.raw_ref["uia_host_ms"] = observation.raw_ref.get("sensor_poll_ms", 0)
        if execution_result is not None:
            observation.raw_ref["last_execution"] = {
                "success": bool(execution_result.success),
                "details": execution_result.details,
                "error": execution_result.error,
                "payload": dict(execution_result.payload or {}),
            }
        if observation.screenshot_path:
            observation.raw_ref["image_turn_count"] = 1
            observation.raw_ref["screenshot_count"] = 1
        else:
            observation.raw_ref["image_turn_count"] = 0
            observation.raw_ref["screenshot_count"] = 0
        return observation

    def plan_next_action(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        context=None,
    ) -> PlanStep:
        retrieved_context, planning_meta = self._normalize_context(context)
        launch_step = self._plan_direct_app_launch(goal, observation, recent_actions, retrieved_context, planning_meta)
        if launch_step is not None:
            return self._with_wait_defaults(launch_step)
        completion_step = self._complete_editor_goal_if_ready(goal, observation, recent_actions, retrieved_context)
        if self.live_planner is not None:
            live_plan = self.live_planner.plan(goal, observation, recent_actions, context)
            if live_plan is not None:
                if self._looks_like_editor_goal(goal, retrieved_context):
                    live_plan = self._override_editor_wait(goal, observation, recent_actions, retrieved_context, live_plan)
                if completion_step is not None and (
                    live_plan.is_complete or live_plan.action is None or live_plan.action.type == ActionType.WAIT
                ):
                    return self._with_wait_defaults(completion_step)
                return self._with_wait_defaults(live_plan)
        if completion_step is not None:
            return self._with_wait_defaults(completion_step)

        preferred_window = self._pick_window(goal, observation.visible_windows, retrieved_context)
        if preferred_window and (
            not observation.active_window or observation.active_window.title != preferred_window.title
        ):
            return self._with_wait_defaults(self._focus_step(preferred_window))

        explicit_text_step = self._plan_explicit_text_entry(goal, observation, recent_actions, retrieved_context)
        if explicit_text_step is not None:
            return self._with_wait_defaults(explicit_text_step)

        editor_text_step = self._plan_editor_text_entry(
            goal,
            observation,
            recent_actions,
            retrieved_context,
            self._extract_requested_text(goal),
        )
        if editor_text_step is not None:
            return self._with_wait_defaults(editor_text_step)

        quoted = [item.strip() for item in re.findall(r'["“”「『](.*?)["”」』]', goal) if item.strip()]
        editable_target = self._pick_edit_target(observation.detected_elements)
        if quoted and editable_target and not self._recently_repeated(
            recent_actions,
            ActionType.TYPE_TEXT,
            editable_target.name,
            quoted[0],
        ):
            return PlanStep(
                summary=f"「{quoted[0]}」を入力します。",
                action=Action(
                    type=ActionType.TYPE_TEXT,
                    target=TargetRef(
                        window_title=observation.active_window.title if observation.active_window else "",
                        name=editable_target.name,
                        automation_id=editable_target.automation_id,
                        control_type=editable_target.control_type,
                        bounds=editable_target.bounds,
                    ),
                    purpose="目的達成に必要なテキストを入力する",
                    reason="指示文に明確な入力文字列が含まれています。",
                    preconditions=["入力欄が見えていること"],
                    expected_outcome="入力欄の内容が更新されます。",
                    confidence=max(0.7, editable_target.confidence),
                    text=quoted[0],
                ),
                reasoning="Quoted text plus a visible edit field is a direct text input fallback.",
            )

        normalized = goal.lower()
        direct_matches: list[tuple[int, Any]] = []
        for element in observation.detected_elements:
            score = self._match_score(normalized, element.name)
            if score > 0 and element.bounds is not None:
                direct_matches.append((score, element))
        if direct_matches:
            direct_matches.sort(key=lambda item: item[0], reverse=True)
            for _, element in direct_matches:
                if not self._recently_repeated(recent_actions, ActionType.CLICK, element.name):
                    return self._click_step(
                        observation,
                        element,
                        summary=f"{element.name} を選択します。",
                        purpose="目的に一致する見えている操作を進める",
                        reason="指示文と画面上のラベルが一致しています。",
                        expected_outcome=f"{element.name} により画面が次の状態に進みます。",
                    )

        primary_action = self._pick_primary_action(observation.detected_elements, normalized)
        if primary_action and not self._recently_repeated(recent_actions, ActionType.CLICK, primary_action.name):
            return self._click_step(
                observation,
                primary_action,
                summary=f"{primary_action.name} を押して先へ進みます。",
                purpose="分かりやすい主要操作を進める",
                reason="画面上に主要な操作が見えています。",
                expected_outcome=f"{primary_action.name} により次の画面や次の段階に進みます。",
            )

        if any(keyword in normalized for keyword in ("scroll", "スクロール", "下へ", "上へ")) and not self._recently_repeated(
            recent_actions,
            ActionType.SCROLL,
            observation.active_window.title if observation.active_window else "",
        ):
            return PlanStep(
                summary="現在の画面をスクロールします。",
                action=Action(
                    type=ActionType.SCROLL,
                    target=TargetRef(window_title=observation.active_window.title if observation.active_window else ""),
                    purpose="現在の画面内で次の候補を探す",
                    reason="指示文または画面状況からスクロールが必要です。",
                    preconditions=["アクティブな画面がスクロール可能であること"],
                    expected_outcome="スクロール後の表示内容を確認できます。",
                    confidence=0.74,
                    scroll_amount=-360,
                ),
                reasoning="Scrolling is a direct discovery action.",
            )

        if planning_meta.get("recent_failure_reason") and not self._recently_repeated(
            recent_actions,
            ActionType.WAIT,
            observation.active_window.title if observation.active_window else "",
        ):
            return PlanStep(
                summary="少し待ってから画面をもう一度確認します。",
                action=Action(
                    type=ActionType.WAIT,
                    target=TargetRef(window_title=observation.active_window.title if observation.active_window else ""),
                    purpose="読み込みや描画の完了を待つ",
                    reason="直前の失敗理由から、表示の安定待ちが有効な可能性があります。",
                    preconditions=[],
                    expected_outcome="待機後に画面が安定し、次の判断材料が増えます。",
                    confidence=0.56,
                ),
                reasoning="A short wait can let the UI finish updating.",
            )

        return PlanStep(
            summary="画面を安定させて次の候補を探します。",
            action=Action(
                type=ActionType.WAIT,
                target=TargetRef(window_title=observation.active_window.title if observation.active_window else ""),
                purpose="次の観察へつなぐ",
                reason="今の画面から次の対象がまだ足りません。",
                preconditions=[],
                expected_outcome="待機後に画面が安定し、次の判断材料が増えます。",
                confidence=0.5,
            ),
            reasoning="Fallback to a short wait instead of ending the session.",
        )

    def verify_target(self, action: Action, observation: Observation) -> VerificationResult:
        if action.type == ActionType.DRAG:
            self._refine_drag_target(action, observation)
        if action.type == ActionType.SHELL_EXECUTE:
            return self._verify_shell_action(action)
        if action.type == ActionType.FOCUS_WINDOW:
            for window in observation.visible_windows:
                if action.target.window_title and action.target.window_title == window.title:
                    return VerificationResult(True, 0.92, "Matching window remains visible")
            return VerificationResult(False, 0.0, "Target window is not visible")
        if action.type in {ActionType.CLICK, ActionType.TYPE_TEXT, ActionType.SCROLL}:
            structured = self.automation_router.resolve_target(action.target)
            if structured is not None:
                if structured.bounds is not None and action.target.bounds is None:
                    action.target.bounds = structured.bounds
                if structured.name and not action.target.name:
                    action.target.name = structured.name
                if structured.automation_id and not action.target.automation_id:
                    action.target.automation_id = structured.automation_id
                return VerificationResult(True, 0.93, f"Structured target resolved via {structured.backend.value}")

        observed_match = self._match_target_elements(action, observation.detected_elements)
        if observed_match is not None:
            return observed_match

        global_match = self._match_target_elements(action, self._lookup_global_elements(action))
        if global_match is not None:
            return global_match

        bounds_match = self._match_visible_bounds(action, observation)
        if bounds_match is not None:
            return bounds_match

        if action.type in {ActionType.TYPE_TEXT, ActionType.HOTKEY, ActionType.SCROLL, ActionType.WAIT}:
            if action.type == ActionType.TYPE_TEXT:
                if any(self._is_edit_element(element.control_type) for element in observation.detected_elements):
                    return VerificationResult(True, 0.72, "Visible editable field found")
                if self._is_edit_element(observation.focused_element):
                    return VerificationResult(True, 0.64, "Focused element is available for text input")
            if action.type == ActionType.HOTKEY and action.hotkey.strip():
                return VerificationResult(True, 0.66, "Hotkey action does not require a pointer target")
            return VerificationResult(True, 0.6, "Action does not require a unique pointer target")
        return VerificationResult(False, 0.2, "Target element is not visible")

    def execute_action(self, action: Action) -> ExecutionResult:
        if action.type == ActionType.SHELL_EXECUTE:
            return self.shell_executor.execute(action)
        structured_result = self._execute_with_structured_automation(action)
        if structured_result is not None:
            return structured_result
        try:
            ok, details = self.input_executor.execute(action)
        except Exception as exc:  # noqa: BLE001
            details = str(exc).strip() or f"{action.type.value} failed"
            return ExecutionResult(success=False, details=details, error=details)
        return ExecutionResult(success=ok, details=details, error="" if ok else details)

    def _execute_with_structured_automation(self, action: Action) -> ExecutionResult | None:
        if action.type not in {ActionType.CLICK, ActionType.TYPE_TEXT, ActionType.SCROLL}:
            return None
        resolver = getattr(self.automation_router, "resolve_target", None)
        if not callable(resolver):
            return None
        element = resolver(action.target)
        if element is None:
            return None

        try:
            if action.type == ActionType.CLICK:
                result = self.automation_router.click(element)
            elif action.type == ActionType.TYPE_TEXT:
                result = self.automation_router.input_text(element, action.text)
            else:
                result = self.automation_router.scroll(element, action.scroll_amount or -360)
        except Exception:  # noqa: BLE001
            return None
        if not result.success:
            return None
        detail = f"{result.backend.value}:{result.used_operation.value if result.used_operation else 'operation'} {result.details}"
        return ExecutionResult(success=True, details=detail)

    def validate_outcome(
        self,
        expected_outcome: str,
        observation: Observation,
        previous_observation: Observation | None = None,
        action: Action | None = None,
    ) -> ValidationResult:
        if previous_observation is None:
            return ValidationResult(True, 0.5, expected_outcome)
        wait_payload = observation.raw_ref.get("wait", {}) if isinstance(observation.raw_ref, dict) else {}
        if bool(wait_payload.get("matched")):
            matched_signal = str(wait_payload.get("matched_signal", "")).strip()
            wait_source = str(wait_payload.get("wait_satisfied_by", "")).strip()
            confidence = 0.9 if wait_source in {"uia_event", "browser"} else 0.78
            return ValidationResult(True, confidence, expected_outcome or matched_signal or "Expected change detected.")
        marker_result = self._validate_marker_outcome(action, observation)
        if marker_result is not None:
            return marker_result
        shell_result = self._shell_result_from_observation(observation)
        if action is not None and action.type == ActionType.SHELL_EXECUTE and shell_result:
            if bool(shell_result.get("success", False)):
                details = expected_outcome or str(shell_result.get("details", "")).strip() or "Shell command completed."
                return ValidationResult(True, 0.82, details)
            details = str(shell_result.get("error") or shell_result.get("details") or "Shell command failed").strip()
            return ValidationResult(False, 0.2, details)
        if action is not None and action.type == ActionType.TYPE_TEXT:
            text_result = self._validate_text_entry(action, observation, previous_observation)
            if text_result is not None:
                return text_result
        if self._active_window_title(observation) != self._active_window_title(previous_observation):
            return ValidationResult(True, 0.84, expected_outcome)
        if observation.focused_element != previous_observation.focused_element:
            return ValidationResult(True, 0.75, expected_outcome)
        if self._element_signature(observation) != self._element_signature(previous_observation):
            return ValidationResult(True, 0.72, expected_outcome)
        if observation.ui_tree_summary != previous_observation.ui_tree_summary:
            return ValidationResult(True, 0.68, expected_outcome)
        if tuple(observation.textual_hints[:6]) != tuple(previous_observation.textual_hints[:6]):
            return ValidationResult(True, 0.64, expected_outcome)
        changed, confidence = self._image_changed(previous_observation.screenshot_path, observation.screenshot_path, expected_outcome)
        if changed:
            return ValidationResult(True, confidence, expected_outcome or "The screen visibly changed.")
        expected_lower = expected_outcome.lower()
        if any(
            token in expected_lower
            for token in ("wait", "stable", "responsive", "scroll", "viewport", "待機", "安定", "スクロール", "読み込み")
        ):
            return ValidationResult(True, 0.56, expected_outcome or "Observation refreshed after wait or scroll.")
        return ValidationResult(False, 0.35, "No visible change detected after action")

    def abort_session(self, reason: str) -> None:
        return None

    def _with_wait_defaults(self, plan: PlanStep) -> PlanStep:
        action = plan.action
        if action is None:
            return plan
        if not action.expected_signals:
            action.expected_signals = self._default_expected_signals(action)
        if int(action.wait_timeout_ms or 0) <= 0:
            action.wait_timeout_ms = self._default_wait_timeout_ms(action)
        return plan

    def _default_expected_signals(self, action: Action) -> list[ExpectedSignal]:
        target_label = action.target.name or action.target.automation_id or action.target.window_title
        if action.type == ActionType.SHELL_EXECUTE:
            if str(action.shell_kind or "").strip().lower() == "process":
                return [ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=self._shell_target_label(action))]
            return []
        if action.type == ActionType.CLICK:
            return [
                ExpectedSignal(ExpectedSignalKind.ELEMENT_ENABLED_CHANGED, target=target_label),
                ExpectedSignal(ExpectedSignalKind.DIALOG_OPENED, target=target_label),
                ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=target_label),
                ExpectedSignal(ExpectedSignalKind.FOCUS_CHANGED, target=target_label),
            ]
        if action.type == ActionType.TYPE_TEXT:
            if self._looks_like_browser_target(action):
                return [
                    ExpectedSignal(ExpectedSignalKind.VALUE_CHANGED, target=target_label),
                    ExpectedSignal(ExpectedSignalKind.TEXT_CHANGED, target=target_label),
                    ExpectedSignal(ExpectedSignalKind.DOM_MUTATION, target=target_label),
                ]
            return [
                ExpectedSignal(ExpectedSignalKind.VALUE_CHANGED, target=target_label),
                ExpectedSignal(ExpectedSignalKind.TEXT_CHANGED, target=target_label),
                ExpectedSignal(ExpectedSignalKind.FOCUS_CHANGED, target=target_label),
            ]
        if action.type == ActionType.SCROLL:
            if self._looks_like_browser_target(action):
                return [ExpectedSignal(ExpectedSignalKind.DOM_MUTATION, target=target_label)]
            return [ExpectedSignal(ExpectedSignalKind.ELEMENT_APPEARED, target=target_label)]
        if action.type == ActionType.HOTKEY:
            normalized_hotkey = self._normalize_text(action.hotkey)
            if normalized_hotkey in {self._normalize_text("CTRL+S"), self._normalize_text("CTRL+SHIFT+S")}:
                return [
                    ExpectedSignal(ExpectedSignalKind.DIALOG_OPENED, target=target_label),
                    ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=target_label),
                    ExpectedSignal(ExpectedSignalKind.FOCUS_CHANGED, target=target_label),
                ]
            if action.hotkey.strip().lower() in {"enter", "return"}:
                return [
                    ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=target_label),
                    ExpectedSignal(ExpectedSignalKind.DIALOG_OPENED, target=target_label),
                ]
            return [ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=action.hotkey)]
        if action.type == ActionType.FOCUS_WINDOW:
            return [ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=target_label)]
        if action.type == ActionType.DRAG:
            return [ExpectedSignal(ExpectedSignalKind.VISION_CHANGE, target=target_label)]
        return [ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=target_label)]

    def _default_wait_timeout_ms(self, action: Action) -> int:
        marker = (action.target.fallback_visual_hint or "").strip().lower()
        if marker.startswith("launch:"):
            return 5000
        if action.type == ActionType.SHELL_EXECUTE:
            if str(action.shell_kind or "").strip().lower() == "process":
                return 5000
            return 200
        if action.type == ActionType.DRAG:
            return 900
        if action.type == ActionType.HOTKEY:
            return 2000
        if action.type == ActionType.WAIT:
            return 1200
        return 1800

    def _requires_vision_fallback(self, action: Action, observation: Observation) -> bool:
        if any(signal.kind == ExpectedSignalKind.VISION_CHANGE for signal in action.expected_signals):
            return True
        if action.type == ActionType.DRAG:
            return True
        target_type = self._normalize_text(action.target.control_type)
        target_hint = self._normalize_text(action.target.fallback_visual_hint)
        if any(token in target_type for token in ("canvas", "image", "custom")):
            return True
        if any(token in target_hint for token in ("canvas", "bitmap", "ownerdraw", "drawing")):
            return True
        kind = observation.raw_ref.get("observation_kind", "") if isinstance(observation.raw_ref, dict) else ""
        return kind == ObservationKind.VISION_FALLBACK.value

    def _looks_like_browser_target(self, action: Action) -> bool:
        hint = self._normalize_text(" ".join([action.target.window_title, action.target.name, action.target.fallback_visual_hint]))
        return any(token in hint for token in ("chrome", "edge", "browser", "tab", "web"))

    def _verify_shell_action(self, action: Action) -> VerificationResult:
        command = str(action.shell_command or "").strip()
        if not command:
            return VerificationResult(False, 0.0, "Shell command is empty")
        kind = str(action.shell_kind or "powershell").strip().lower() or "powershell"
        if kind not in {"powershell", "cmd", "process"}:
            return VerificationResult(False, 0.0, f"Unsupported shell kind: {kind}")
        cwd = str(action.shell_cwd or "").strip()
        if cwd:
            candidate = Path(cwd)
            if not candidate.is_absolute():
                candidate = self.root / candidate
            if not candidate.exists() or not candidate.is_dir():
                return VerificationResult(False, 0.0, "Shell working directory does not exist")
        return VerificationResult(True, 0.95, f"Shell action is ready via {kind}")

    def _wait_for_shell_completion(
        self,
        action: Action,
        previous_observation: Observation,
        *,
        recent_actions: list[str],
        execution_result: ExecutionResult | None,
    ) -> Observation:
        expected_signals = action.expected_signals or self._default_expected_signals(action)
        if expected_signals:
            previous_snapshot = observation_sensor_snapshot(previous_observation) or self.primary_sensor.snapshot()
            wait_started = time.monotonic()
            wait_result = self.primary_sensor.wait_for_expected_signals(
                previous_snapshot,
                expected_signals,
                timeout_ms=max(int(action.wait_timeout_ms or 0), 200),
            )
            observation = self.observation_builder.refresh_structured(
                recent_actions,
                previous_observation=previous_observation,
                sensor_snapshot=wait_result["snapshot"],
            )
            elapsed_ms = int((time.monotonic() - wait_started) * 1000)
        else:
            snapshot = self.primary_sensor.snapshot()
            observation = self.observation_builder.refresh_structured(
                recent_actions,
                previous_observation=previous_observation,
                sensor_snapshot=snapshot,
            )
            wait_result = {
                "matched": False,
                "snapshot": snapshot,
                "matched_signal": "",
                "wait_satisfied_by": "command",
            }
            elapsed_ms = 0
        observation.raw_ref["wait"] = {
            "matched": bool(wait_result["matched"]),
            "matched_signal": str(wait_result.get("matched_signal", "")),
            "wait_satisfied_by": str(wait_result.get("wait_satisfied_by", "")),
            "timeout_ms": int(action.wait_timeout_ms or 0),
            "elapsed_ms": elapsed_ms,
        }
        observation.raw_ref["wait_satisfied_by"] = observation.raw_ref["wait"]["wait_satisfied_by"]
        observation.raw_ref["browser_refresh_ms"] = 0
        observation.raw_ref["uia_host_ms"] = observation.raw_ref.get("sensor_poll_ms", 0)
        observation.raw_ref["image_turn_count"] = 0
        observation.raw_ref["screenshot_count"] = 0
        if execution_result is not None:
            observation.raw_ref["last_execution"] = {
                "success": bool(execution_result.success),
                "details": execution_result.details,
                "error": execution_result.error,
                "payload": dict(execution_result.payload or {}),
            }
        return observation

    def _shell_result_from_observation(self, observation: Observation) -> dict[str, Any]:
        raw_ref = observation.raw_ref if isinstance(observation.raw_ref, dict) else {}
        payload = raw_ref.get("last_execution", {})
        return payload if isinstance(payload, dict) else {}

    def _shell_target_label(self, action: Action) -> str:
        return action.target.window_title or action.target.name or action.shell_command or "shell_execute"

    def _normalize_context(self, context: Any) -> tuple[Any, dict[str, Any]]:
        if isinstance(context, dict):
            return context.get("retrieved_context"), context
        return context, {}

    def _pick_window(self, goal: str, windows, retrieved_context) -> Any | None:
        if not windows:
            return None
        hints = []
        hints.extend(self._goal_launch_candidates(goal))
        if retrieved_context and getattr(retrieved_context, "app_candidates", None):
            hints.extend(retrieved_context.app_candidates)
        hints.extend(["paint", "gimp", "excel", "chrome", "settings", "codex", "claude"])
        normalized_goal = goal.lower()
        for hint in hints:
            search = str(hint).replace("_", " ").lower()
            if search in normalized_goal or any(search in window.title.lower() or search in window.class_name.lower() for window in windows):
                for window in windows:
                    if search in window.title.lower() or search in window.class_name.lower():
                        return window
        return windows[0]

    def _pick_edit_target(self, elements):
        editable = [element for element in elements if element.bounds is not None and self._is_edit_element(element.control_type)]
        if not editable:
            return None
        editable.sort(key=lambda item: item.confidence, reverse=True)
        return editable[0]

    def _pick_primary_action(self, elements, goal_text: str):
        ranked = []
        for element in elements:
            name = (element.name or "").strip()
            if not name or element.bounds is None:
                continue
            lowered = name.lower()
            if lowered in PRIMARY_ACTION_LABELS or any(label in lowered for label in PRIMARY_ACTION_LABELS):
                ranked.append(element)
        if not ranked:
            return None
        ranked.sort(key=lambda item: item.confidence, reverse=True)
        return ranked[0]

    def _focus_step(self, window) -> PlanStep:
        return self._with_wait_defaults(PlanStep(
            summary=f"{window.title} を前面に切り替えます。",
            action=Action(
                type=ActionType.FOCUS_WINDOW,
                target=TargetRef(window_title=window.title, name=window.title),
                purpose="目的に近いウィンドウを操作可能にする",
                reason="対象アプリが見えているので前面に出します。",
                preconditions=["対象ウィンドウが見えていること"],
                expected_outcome=f"{window.title} が操作中の画面になります。",
                confidence=0.86,
            ),
            reasoning="Focusing the target window is a direct recovery step.",
        ))

    def _click_step(
        self,
        observation: Observation,
        element,
        summary: str,
        purpose: str,
        reason: str,
        expected_outcome: str,
        fallback_hint: str = "",
    ) -> PlanStep:
        return self._with_wait_defaults(PlanStep(
            summary=summary,
            action=Action(
                type=ActionType.CLICK,
                target=TargetRef(
                    window_title=observation.active_window.title if observation.active_window else "",
                    name=element.name,
                    automation_id=element.automation_id,
                    control_type=element.control_type,
                    bounds=element.bounds,
                    fallback_visual_hint=fallback_hint,
                ),
                purpose=purpose,
                reason=reason,
                preconditions=["対象が見えていること"],
                expected_outcome=expected_outcome,
                confidence=max(0.68, element.confidence),
            ),
            reasoning="A visible labeled control is a direct clickable fallback.",
        ))

    def _match_score(self, goal_text: str, element_name: str) -> int:
        if not element_name:
            return 0
        lowered = element_name.lower().strip()
        score = 0
        if lowered and lowered in goal_text:
            score += 4
        for token in re.split(r"\s+", goal_text):
            if len(token) >= 3 and token in lowered:
                score += 1
        return score

    def _recently_repeated(
        self,
        recent_actions: list[Action],
        action_type: ActionType,
        target_name: str,
        text: str = "",
    ) -> bool:
        repeated = 0
        for action in recent_actions[-4:]:
            if action.type != action_type:
                continue
            action_target = action.target.name or action.target.window_title
            if action_target != target_name:
                continue
            if text and action.text != text:
                continue
            repeated += 1
        return repeated >= 2

    def _recent_text_sent(self, recent_actions: list[Action], text: str) -> bool:
        return any(action.type == ActionType.TYPE_TEXT and action.text == text for action in recent_actions[-3:])

    def _plan_direct_app_launch(self, goal: str, observation: Observation, recent_actions: list[Action], retrieved_context, planning_meta: dict[str, Any]) -> PlanStep | None:
        if self._is_save_dialog_observation(observation):
            return None
        app_key = self._requested_launch_app(goal, retrieved_context)
        if not app_key or self._observation_has_app(observation, app_key):
            return None

        strategy = str(APP_LAUNCH_SPECS[app_key].get("launch_strategy", "run_dialog") or "run_dialog").strip().lower()
        if strategy == "process" and not self._should_fallback_launch_to_run_dialog(app_key, observation, planning_meta):
            return self._plan_process_launch(app_key)

        app_element = self._find_element_by_terms(observation.detected_elements, APP_LAUNCH_SPECS[app_key]["terms"])
        if app_element is not None and not self._recently_repeated(recent_actions, ActionType.CLICK, app_element.name):
            display = APP_LAUNCH_SPECS[app_key]["display"]
            return self._click_step(
                observation,
                app_element,
                summary=f"{display} を起動します。",
                purpose=f"{display} を起動する",
                reason=f"{display} が見えているのでそのまま起動します。",
                expected_outcome=f"{display} のウィンドウが表示されます。",
                fallback_hint=f"launch:{app_key}",
            )

        if self._is_run_dialog_observation(observation):
            return self._plan_run_dialog_launch(app_key, observation, recent_actions)

        display = APP_LAUNCH_SPECS[app_key]["display"]
        return PlanStep(
            summary=f"{display} を起動するため実行ダイアログを開きます。",
            action=Action(
                type=ActionType.HOTKEY,
                target=TargetRef(fallback_visual_hint="screen:run-dialog"),
                purpose="実行ダイアログを開く",
                reason=f"{display} を直接起動する最短ルートに切り替えます。",
                preconditions=["デスクトップが操作可能であること"],
                expected_outcome="実行ダイアログが開いて入力欄が表示されます。",
                confidence=0.98,
                hotkey="WIN+R",
            ),
            reasoning="Known apps launch more reliably from the Run dialog.",
        )

    def _should_fallback_launch_to_run_dialog(
        self,
        app_key: str,
        observation: Observation,
        planning_meta: dict[str, Any],
    ) -> bool:
        spec = APP_LAUNCH_SPECS.get(app_key, {})
        command = self._normalize_text(spec.get("command", ""))
        if not command:
            return False
        shell_result = self._shell_result_from_observation(observation)
        payload = shell_result.get("payload", {}) if isinstance(shell_result, dict) else {}
        executed_kind = self._normalize_text(payload.get("kind", ""))
        executed_command = self._normalize_text(payload.get("command", ""))
        if executed_kind != "process" or executed_command != command:
            return False
        if not bool(shell_result.get("success", False)):
            return True
        recent_failure_reason = self._normalize_text(planning_meta.get("recent_failure_reason", ""))
        if not recent_failure_reason:
            return False
        if any(token in recent_failure_reason for token in ("notvisibleyet", "targetverificationfailure", "validationfailed")):
            return True
        return command in recent_failure_reason or self._normalize_text(app_key) in recent_failure_reason

    def _plan_process_launch(self, app_key: str) -> PlanStep:
        spec = APP_LAUNCH_SPECS[app_key]
        display = spec["display"]
        command = spec["command"]
        return PlanStep(
            summary=f"{display} を直接起動します。",
            action=Action(
                type=ActionType.SHELL_EXECUTE,
                target=TargetRef(
                    window_title=display,
                    name=display,
                    fallback_visual_hint=f"launch:{app_key}",
                ),
                purpose=f"{display} を最短経路で起動する",
                reason=f"{display} は実行ダイアログを経由せず直接起動した方が安定します。",
                preconditions=["デスクトップで外部プロセスを起動できること"],
                expected_outcome=f"{display} のウィンドウが表示されます。",
                confidence=0.98,
                shell_kind="process",
                shell_command=command,
                shell_detach=True,
            ),
            reasoning="A direct process launch is faster and avoids Run dialog focus problems.",
        )

    def _plan_run_dialog_launch(self, app_key: str, observation: Observation, recent_actions: list[Action]) -> PlanStep:
        spec = APP_LAUNCH_SPECS[app_key]
        display = spec["display"]
        command = spec["command"]
        if self._observation_contains_text(observation, command) or self._recent_text_sent(recent_actions, command):
            return PlanStep(
                summary=f"{display} を実行します。",
                action=Action(
                    type=ActionType.HOTKEY,
                    target=TargetRef(
                        window_title=observation.active_window.title if observation.active_window else "",
                        fallback_visual_hint=f"launch:{app_key}",
                    ),
                    purpose=f"{display} を起動する",
                    reason=f"実行ダイアログに {command} が入っているのでそのまま実行します。",
                    preconditions=["実行ダイアログが開いていること"],
                    expected_outcome=f"{display} のウィンドウが表示されます。",
                    confidence=0.97,
                    hotkey="ENTER",
                ),
                reasoning="Enter is the shortest way to launch from Run once the command is present.",
            )

        edit_target = self._pick_edit_target(observation.detected_elements)
        return PlanStep(
            summary=f"実行ダイアログへ {command} を入力します。",
            action=Action(
                type=ActionType.TYPE_TEXT,
                target=TargetRef(
                    window_title=observation.active_window.title if observation.active_window else "",
                    name=edit_target.name if edit_target else "",
                    automation_id=edit_target.automation_id if edit_target else "",
                    control_type=edit_target.control_type if edit_target else "ControlType.Edit",
                    bounds=edit_target.bounds if edit_target else None,
                    fallback_visual_hint=f"input:run:{app_key}",
                ),
                purpose=f"{display} の実行コマンドを入力する",
                reason=f"実行ダイアログから {display} を直接起動します。",
                preconditions=["実行ダイアログの入力欄が使えること"],
                expected_outcome=f"実行ダイアログの入力欄に {command} が入ります。",
                confidence=0.96 if edit_target else 0.84,
                text=command,
            ),
            reasoning="Typing the executable alias is the direct Run dialog launch path.",
        )

    def _requested_launch_app(self, goal: str, retrieved_context) -> str:
        explicit_matches = self._goal_launch_candidates(goal)
        if explicit_matches:
            return explicit_matches[0]

        goal_lower = goal.lower()
        if retrieved_context and getattr(retrieved_context, "app_candidates", None):
            for app_name in retrieved_context.app_candidates:
                if app_name in APP_LAUNCH_SPECS:
                    return app_name
        for app_name, spec in APP_LAUNCH_SPECS.items():
            if any(term in goal_lower for term in spec["terms"]):
                return app_name
        return ""

    def _goal_launch_candidates(self, goal: str) -> list[str]:
        normalized_goal = self._normalize_text(goal)
        matches: list[tuple[int, int, str]] = []
        for app_name, spec in APP_LAUNCH_SPECS.items():
            terms = {self._normalize_text(term) for term in spec["terms"] if term}
            terms.add(self._normalize_text(app_name.replace("_", " ")))
            score = 0
            longest = 0
            for term in terms:
                if term and term in normalized_goal:
                    score += 1
                    longest = max(longest, len(term))
            if score:
                matches.append((score, longest, app_name))
        matches.sort(reverse=True)
        return [app_name for _, _, app_name in matches]

    def _extract_requested_text(self, goal: str) -> str:
        quoted = [item.strip() for item in re.findall(r'["“”「『](.*?)["”」』]', goal, flags=re.DOTALL) if item.strip()]
        if quoted:
            return quoted[0]

        clauses = [part.strip() for part in re.split(r"[、,。．\n]+", goal) if part.strip()]
        search_spaces = []
        if clauses:
            search_spaces.append(clauses[-1])
        search_spaces.append(goal)
        patterns = (
            r"(?:次の文章|次の文|以下の文章|以下の文|次のテキスト|以下のテキスト)\s*[:：]\s*(.+)$",
            r"(?:次を入力|以下を入力|次を書いて|以下を書いて|次を貼り付けて|以下を貼り付けて)\s*[:：]\s*(.+)$",
            r"(.+?)\s*と(?:入力|記入|書いて|書く|貼り付けて)",
        )
        for source in search_spaces:
            for pattern in patterns:
                match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
                if not match:
                    continue
                candidate = re.sub(r"\s+", " ", match.group(1)).strip(" \t\r\n\"“”「」『』")
                if candidate and len(candidate) <= 5000:
                    return candidate
        return ""
    def _synthesize_editor_text_draft(self, goal: str, retrieved_context, requested_text: str) -> str:
        _ = retrieved_context
        if requested_text:
            return requested_text
        if not self._looks_like_self_introduction_request(goal):
            return self._synthesize_generic_editor_draft(goal, retrieved_context)
        if self._goal_prefers_japanese(goal):
            return (
                "こんにちは。私はAutoCruise CEです。"
                "Windows上の作業を支援するデスクトップ操作エージェントです。"
                "画面の確認、アプリの起動、文章入力などを手伝えます。よろしくお願いします。"
            )
        return (
            "Hello. I am AutoCruise CE, a Windows desktop operator. "
            "I can help open apps, inspect the screen, and carry out simple writing tasks."
        )

    def _synthesize_generic_editor_draft(self, goal: str, retrieved_context) -> str:
        if not self._looks_like_editor_goal(goal, retrieved_context):
            return ""
        normalized_goal = self._normalize_text(goal)
        wants_paragraph = any(
            self._normalize_text(term) in normalized_goal
            for term in ("paragraph", "essay", "article", "文章", "段落", "作文")
        )
        wants_note = any(
            self._normalize_text(term) in normalized_goal
            for term in ("note", "memo", "メモ", "覚え書き")
        )
        if self._goal_prefers_japanese(goal):
            if wants_paragraph:
                return (
                    "AutoCruise CEは依頼内容をもとに、自律的に文章を作成します。"
                    "目的や画面の状況を読み取り、必要な内容を判断しながら、自然に読める形へまとめます。"
                    "ユーザーが細かい文面を指定していない場合でも、作業を止めずに前へ進めることを重視します。"
                )
            if wants_note:
                return (
                    "作業メモ: AutoCruise CEは依頼内容を確認し、必要な内容を自律的に判断して入力しました。"
                    "追加の指定がない場合でも、作業の目的に沿って次の行動を選びます。"
                )
            return (
                "AutoCruise CEは依頼内容に合わせて、自律的に文章を作成しました。"
                "細かな文面が指定されていなくても、目的を満たす内容を判断して入力します。"
            )
        if wants_paragraph:
            return (
                "AutoCruise CE writes autonomously from the user's request. "
                "When the exact wording is not specified, it interprets the goal, chooses useful content, "
                "and continues the task instead of waiting for unnecessary clarification."
            )
        if wants_note:
            return (
                "Note: AutoCruise CE reviewed the request, chose the necessary content autonomously, "
                "and continued the task without requiring exact wording."
            )
        return (
            "AutoCruise CE created this text autonomously from the request. "
            "It chooses appropriate content and action when no exact wording is provided."
        )

    def _looks_like_self_introduction_request(self, goal: str) -> bool:
        normalized_goal = self._normalize_text(goal)
        terms = (
            "selfintroduction",
            "introduceyourself",
            "aboutme",
            "自己紹介",
            "自己紹介文",
        )
        return any(self._normalize_text(term) in normalized_goal for term in terms)

    def _goal_prefers_japanese(self, goal: str) -> bool:
        return any("\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff" for char in str(goal or ""))

    def _looks_like_editor_goal(self, goal: str, retrieved_context) -> bool:
        if self._requested_launch_app(goal, retrieved_context) == "notepad":
            return True
        normalized_goal = self._normalize_text(goal)
        editor_terms = (
            "メモ帳",
            "notepad",
            "write",
            "writing",
            "type",
            "text",
            "sentence",
            "paragraph",
            "文章",
            "テキスト",
            "入力",
            "書いて",
            "書く",
        )
        return any(self._normalize_text(term) in normalized_goal for term in editor_terms)

    def _looks_like_editor_window(self, observation: Observation) -> bool:
        active_window = observation.active_window
        if active_window is None:
            return False
        evidence = " ".join(
            [
                active_window.title,
                active_window.class_name,
                observation.focused_element,
                observation.ui_tree_summary,
                *observation.textual_hints[:8],
            ]
        )
        normalized = self._normalize_text(evidence)
        editor_terms = ("notepad", "メモ帳", "edit", "editor", "document", "text")
        if any(self._normalize_text(term) in normalized for term in editor_terms):
            return True
        return any(self._is_edit_element(element.control_type) for element in observation.detected_elements)

    def _extract_explicit_text(self, goal: str) -> str:
        quoted = [item.strip() for item in re.findall(r'["“”「『](.*?)["”」』]', goal, flags=re.DOTALL) if item.strip()]
        if quoted:
            return quoted[0]

        patterns = (
            r"(?:text|message|content|body)\s*[:：]\s*(.+)$",
            r"(?:次の文|次の文章|次のテキスト|文章|テキスト|本文|内容)\s*[:：]\s*(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, goal, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" \t\r\n\"“”「『」』")
            if candidate and len(candidate) <= 5000:
                return candidate
        return ""

    def _plan_explicit_text_entry(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        retrieved_context,
    ) -> PlanStep | None:
        requested_text = self._extract_explicit_text(goal)
        if not requested_text:
            return None
        if not self._looks_like_editor_goal(goal, retrieved_context):
            return None
        if not self._looks_like_editor_window(observation):
            return None
        editor_target = self._build_editor_target(observation)
        if self._recently_repeated(recent_actions, ActionType.TYPE_TEXT, editor_target.name, requested_text):
            return None
        return self._build_editor_type_step(observation, requested_text)

    def _build_editor_type_step(self, observation: Observation, text: str) -> PlanStep | None:
        active_window = observation.active_window
        if active_window is None:
            return None
        edit_target = self._pick_edit_target(observation.detected_elements)
        target = self._build_editor_target(observation)
        return PlanStep(
            summary="Type the requested text into the active editor.",
            action=Action(
                type=ActionType.TYPE_TEXT,
                target=target,
                purpose="Enter the requested text into the active editor.",
                reason="The requested editor window is already open and ready for input.",
                preconditions=["An editor window is active."],
                expected_outcome="The editor content updates with the requested text.",
                confidence=max(0.72, edit_target.confidence if edit_target else 0.72),
                text=text,
            ),
            reasoning="Editor tasks should advance with text input instead of waiting.",
        )

    def _build_editor_click_step(self, observation: Observation) -> PlanStep | None:
        active_window = observation.active_window
        if active_window is None or active_window.bounds is None:
            return None
        edit_target = self._pick_edit_target(observation.detected_elements)
        target = self._build_editor_target(observation)
        return PlanStep(
            summary="Place the caret inside the active editor.",
            action=Action(
                type=ActionType.CLICK,
                target=target,
                purpose="Place the caret in the active editor.",
                reason="Typing should start only after the editor surface is active.",
                preconditions=["The editor window is visible."],
                expected_outcome="The text caret is active in the editor surface.",
                confidence=max(0.7, edit_target.confidence if edit_target else 0.7),
            ),
            reasoning="A direct click into the editor is better than waiting.",
        )

    def _build_editor_target(self, observation: Observation, *, fallback_hint: str = "editor:window") -> TargetRef:
        active_window = observation.active_window
        edit_target = self._pick_edit_target(observation.detected_elements)
        stable_name = self._editor_anchor(observation, edit_target=edit_target)
        return TargetRef(
            window_title=active_window.title if active_window else "",
            name=stable_name,
            automation_id=edit_target.automation_id if edit_target else "",
            control_type=edit_target.control_type if edit_target else "ControlType.Document",
            bounds=edit_target.bounds if edit_target else (active_window.bounds if active_window else None),
            fallback_visual_hint=fallback_hint,
            search_terms=["editor", "document", "text", "file"],
        )

    def _editor_anchor(self, observation: Observation, *, edit_target=None) -> str:
        edit_target = edit_target if edit_target is not None else self._pick_edit_target(observation.detected_elements)
        if edit_target is not None:
            for value in (edit_target.automation_id, edit_target.name, edit_target.control_type):
                text = str(value or "").strip()
                if text:
                    return text
        active_window = observation.active_window
        if active_window is not None:
            if active_window.class_name.strip():
                return active_window.class_name.strip()
            if active_window.title.strip():
                return self._strip_editor_title_state(active_window.title)
        return "editor_surface"

    def _goal_requires_save(self, goal: str, retrieved_context) -> bool:
        if not self._looks_like_editor_goal(goal, retrieved_context):
            return False
        normalized_goal = self._normalize_text(goal)
        save_terms = (
            "save",
            "saveas",
            "filename",
            "filepath",
            "保存",
            "上書き保存",
            "名前を付けて保存",
            "ファイル名",
        )
        return any(self._normalize_text(term) in normalized_goal for term in save_terms)

    def _editor_save_path(self, goal: str) -> str:
        explicit = self._extract_requested_save_path(goal)
        if explicit:
            return explicit
        documents_dir = Path.home() / "Documents"
        if not documents_dir.exists():
            documents_dir = Path.home()
        digest = hashlib.sha1(goal.encode("utf-8", errors="ignore")).hexdigest()[:8]
        return str((documents_dir / f"AutoCruiseCE-note-{digest}.txt").resolve())

    def _extract_requested_save_path(self, goal: str) -> str:
        patterns = (
            r"([A-Za-z]:\\[^\"<>\r\n|?*]+\.(?:txt|md|log|json|csv))",
            r"((?:\.{0,2}[\\/])[^\"<>\r\n|?*]+\.(?:txt|md|log|json|csv))",
            r"(?:save(?:\s+as)?|filename|file\s*name|named|保存(?:して)?|ファイル名|名前)\s*[:：]?\s*[\"“]?([^\"”\r\n]+\.(?:txt|md|log|json|csv))",
        )
        for pattern in patterns:
            match = re.search(pattern, goal, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = str(match.group(1)).strip().strip("\"“”")
            if candidate:
                return candidate
        return ""

    def _is_save_dialog_observation(self, observation: Observation) -> bool:
        normalized_evidence = [self._normalize_text(value) for value in self._observation_evidence(observation)]
        dialog_terms = (
            self._normalize_text("save as"),
            self._normalize_text("file name"),
            self._normalize_text("filename"),
            self._normalize_text("名前を付けて保存"),
            self._normalize_text("ファイル名"),
        )
        if any(any(term and term in value for term in dialog_terms) for value in normalized_evidence):
            return True
        has_filename = any(self._normalize_text("file name") in value or self._normalize_text("filename") in value or self._normalize_text("ファイル名") in value for value in normalized_evidence)
        has_save = any(self._normalize_text("save") in value or self._normalize_text("保存") in value for value in normalized_evidence)
        return has_filename and has_save

    def _editor_window_looks_unsaved(self, observation: Observation) -> bool:
        title = observation.active_window.title if observation.active_window else ""
        stripped = self._strip_editor_title_state(title)
        normalized_title = self._normalize_text(stripped)
        untitled_terms = (
            "untitled",
            "無題",
            "タイトルなし",
        )
        if any(self._normalize_text(term) in normalized_title for term in untitled_terms):
            return True
        return any(marker in title for marker in ("*", "●", "•"))

    def _strip_editor_title_state(self, title: str) -> str:
        stripped = str(title or "").strip()
        for marker in ("*", "●", "•"):
            stripped = stripped.replace(marker, "")
        return stripped.strip()

    def _same_editor_context(self, action: Action, observation: Observation, editor_anchor: str) -> bool:
        marker = (action.target.fallback_visual_hint or "").strip().lower()
        if marker.startswith("editor:"):
            return True
        action_anchor = self._normalize_text(action.target.automation_id or action.target.name or action.target.control_type)
        current_anchor = self._normalize_text(editor_anchor)
        if action_anchor and current_anchor and action_anchor == current_anchor:
            return True
        current_title = self._normalize_text(self._strip_editor_title_state(observation.active_window.title if observation.active_window else ""))
        action_title = self._normalize_text(self._strip_editor_title_state(action.target.window_title))
        return bool(current_title and action_title and current_title == action_title)

    def _recent_hotkey_match(self, recent_actions: list[Action], hotkey: str, editor_anchor: str) -> bool:
        normalized_hotkey = self._normalize_text(hotkey)
        normalized_anchor = self._normalize_text(editor_anchor)
        for action in recent_actions[-4:]:
            if action.type != ActionType.HOTKEY:
                continue
            if self._normalize_text(action.hotkey) != normalized_hotkey:
                continue
            marker = (action.target.fallback_visual_hint or "").strip().lower()
            action_anchor = self._normalize_text(action.target.automation_id or action.target.name or action.target.control_type)
            if marker.startswith("editor:") or (normalized_anchor and action_anchor == normalized_anchor):
                return True
        return False

    def _recent_type_text_match(self, recent_actions: list[Action], text: str, editor_anchor: str) -> bool:
        normalized_anchor = self._normalize_text(editor_anchor)
        for action in recent_actions[-4:]:
            if action.type != ActionType.TYPE_TEXT:
                continue
            if action.text != text:
                continue
            marker = (action.target.fallback_visual_hint or "").strip().lower()
            action_anchor = self._normalize_text(action.target.automation_id or action.target.name or action.target.control_type)
            if marker.startswith("editor:") or (normalized_anchor and action_anchor == normalized_anchor):
                return True
        return False

    def _build_editor_hotkey_step(
        self,
        observation: Observation,
        *,
        hotkey: str,
        summary: str,
        purpose: str,
        reason: str,
        expected_outcome: str,
        fallback_hint: str,
    ) -> PlanStep:
        return PlanStep(
            summary=summary,
            action=Action(
                type=ActionType.HOTKEY,
                target=self._build_editor_target(observation, fallback_hint=fallback_hint),
                purpose=purpose,
                reason=reason,
                preconditions=["The editor window is visible."],
                expected_outcome=expected_outcome,
                confidence=0.84,
                hotkey=hotkey,
            ),
            reasoning="The editor shortcut is the shortest reliable way to continue the writing task.",
        )

    def _build_save_dialog_type_step(self, observation: Observation, save_path: str) -> PlanStep:
        return PlanStep(
            summary="Enter the save path into the Save dialog.",
            action=Action(
                type=ActionType.TYPE_TEXT,
                target=self._build_editor_target(observation, fallback_hint="editor:save-dialog"),
                purpose="Enter the destination file path into the Save dialog.",
                reason="The save dialog is open and needs a concrete file path before confirming.",
                preconditions=["The Save dialog is visible and the file name field is editable."],
                expected_outcome="The Save dialog file name field contains the target file path.",
                confidence=0.82,
                text=save_path,
            ),
            reasoning="Typing the destination path directly is faster than navigating folders manually.",
        )

    def _plan_editor_save_action(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        retrieved_context,
    ) -> PlanStep | None:
        if not self._goal_requires_save(goal, retrieved_context):
            return None
        if not self._looks_like_editor_window(observation) and not self._is_save_dialog_observation(observation):
            return None
        editor_anchor = self._editor_anchor(observation)
        save_path = self._editor_save_path(goal)
        if self._editor_save_recently_completed(observation, recent_actions, editor_anchor, save_path):
            return None
        if self._is_save_dialog_observation(observation):
            if self._recent_type_text_match(recent_actions, save_path, editor_anchor) or self._observation_contains_text(observation, Path(save_path).name):
                if not self._recent_hotkey_match(recent_actions, "ENTER", editor_anchor):
                    return self._build_editor_hotkey_step(
                        observation,
                        hotkey="ENTER",
                        summary="Confirm the Save dialog.",
                        purpose="Confirm the current save path and save the file.",
                        reason="The file path is ready, so the next step is to confirm the Save dialog.",
                        expected_outcome="The Save dialog closes and the editor switches to the saved document.",
                        fallback_hint="editor:saved",
                    )
                return None
            if not self._recently_repeated(recent_actions, ActionType.TYPE_TEXT, editor_anchor, save_path):
                return self._build_save_dialog_type_step(observation, save_path)
            return None
        if not self._recent_hotkey_match(recent_actions, "CTRL+S", editor_anchor):
            return self._build_editor_hotkey_step(
                observation,
                hotkey="CTRL+S",
                summary="Save the current editor document.",
                purpose="Start the save flow for the current editor document.",
                reason="The goal explicitly requires saving after the text is written.",
                expected_outcome="The document save flow starts, or the editor saves the document immediately.",
                fallback_hint="editor:save-request",
            )
        return None

    def _editor_save_recently_completed(
        self,
        observation: Observation,
        recent_actions: list[Action],
        editor_anchor: str,
        save_path: str,
    ) -> bool:
        if self._is_save_dialog_observation(observation):
            return False
        basename = Path(save_path).name if save_path else ""
        if basename and self._observation_contains_text(observation, basename):
            return True
        if not recent_actions:
            return False
        recent_editor_hotkey = any(
            action.type == ActionType.HOTKEY
            and self._normalize_text(action.hotkey) in {self._normalize_text("CTRL+S"), self._normalize_text("ENTER")}
            and self._same_editor_context(action, observation, editor_anchor)
            for action in recent_actions[-4:]
        )
        if not recent_editor_hotkey:
            return False
        return self._looks_like_editor_window(observation) and not self._editor_window_looks_unsaved(observation)

    def _plan_editor_text_entry(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        retrieved_context,
        requested_text: str,
    ) -> PlanStep | None:
        if not self._looks_like_editor_goal(goal, retrieved_context):
            return None
        if self._is_save_dialog_observation(observation):
            save_step = self._plan_editor_save_action(goal, observation, recent_actions, retrieved_context)
            if save_step is not None:
                return self._with_wait_defaults(save_step)
            return None
        if not self._looks_like_editor_window(observation):
            save_step = self._plan_editor_save_action(goal, observation, recent_actions, retrieved_context)
            if save_step is not None:
                return self._with_wait_defaults(save_step)
            return None

        editor_anchor = self._editor_anchor(observation)
        draft_text = self._synthesize_editor_text_draft(goal, retrieved_context, requested_text)
        completion_text = requested_text or ""
        if draft_text:
            if self._editor_text_recently_completed(observation, recent_actions, editor_anchor, completion_text):
                save_step = self._plan_editor_save_action(goal, observation, recent_actions, retrieved_context)
                if save_step is not None:
                    return self._with_wait_defaults(save_step)
                return PlanStep(
                    summary="The requested text has already been entered.",
                    is_complete=True,
                    completion_reason="The editor already contains the most recent requested text entry.",
                    reasoning="A successful text entry was already sent to the active editor, so repeating it would not make progress.",
                )
            if self._recently_repeated(recent_actions, ActionType.TYPE_TEXT, editor_anchor, draft_text):
                return None
            return self._with_wait_defaults(self._build_editor_type_step(observation, draft_text))

        if self._editor_text_recently_completed(observation, recent_actions, editor_anchor, completion_text):
            save_step = self._plan_editor_save_action(goal, observation, recent_actions, retrieved_context)
            if save_step is not None:
                return self._with_wait_defaults(save_step)
            return None

        if not self._is_edit_focus(observation.focused_element):
            if not self._recently_repeated(recent_actions, ActionType.CLICK, editor_anchor):
                return self._with_wait_defaults(self._build_editor_click_step(observation))
        return None

    def _override_editor_wait(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        retrieved_context,
        live_plan: PlanStep,
    ) -> PlanStep:
        if live_plan.action is None or live_plan.action.type != ActionType.WAIT:
            return live_plan
        editor_step = self._plan_editor_text_entry(
            goal,
            observation,
            recent_actions,
            retrieved_context,
            self._extract_requested_text(goal),
        )
        return editor_step or live_plan

    def _complete_editor_goal_if_ready(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        retrieved_context,
    ) -> PlanStep | None:
        if not recent_actions:
            return None
        if not self._looks_like_editor_goal(goal, retrieved_context):
            return None
        if not self._looks_like_editor_window(observation):
            return None
        requested_text = self._extract_requested_text(goal)
        draft_text = self._synthesize_editor_text_draft(goal, retrieved_context, requested_text)
        editor_anchor = self._editor_anchor(observation)
        last_typed_text = ""
        if recent_actions and recent_actions[-1].type == ActionType.TYPE_TEXT:
            last_typed_text = str(recent_actions[-1].text or "").strip()
        if not (draft_text or last_typed_text):
            return None
        if not self._editor_text_recently_completed(observation, recent_actions, editor_anchor, requested_text or ""):
            return None
        if self._goal_requires_save(goal, retrieved_context):
            save_path = self._editor_save_path(goal)
            if not self._editor_save_recently_completed(observation, recent_actions, editor_anchor, save_path):
                return None
            return PlanStep(
                summary="The requested writing and save task is complete.",
                is_complete=True,
                completion_reason="The requested text was entered into the active editor and the document was saved.",
                reasoning="The editor already contains the goal-aligned text and the save flow completed successfully.",
            )
        return PlanStep(
            summary="The requested writing task is complete.",
            is_complete=True,
            completion_reason="The requested text was entered into the active editor.",
            reasoning="The latest successful action already wrote the goal-aligned text, so the next best action is to stop.",
        )

    def _editor_text_recently_completed(
        self,
        observation: Observation,
        recent_actions: list[Action],
        editor_anchor: str,
        text: str,
    ) -> bool:
        if not recent_actions:
            return False
        last_action = recent_actions[-1]
        if last_action.type != ActionType.TYPE_TEXT:
            return False
        if not self._same_editor_context(last_action, observation, editor_anchor):
            return False
        if text and last_action.text != text:
            return False
        if not text and not str(last_action.text or "").strip():
            return False
        last_execution = observation.raw_ref.get("last_execution", {}) if isinstance(observation.raw_ref, dict) else {}
        return bool(last_execution.get("success"))

    def _observation_has_app(self, observation: Observation, app_key: str) -> bool:
        terms = APP_LAUNCH_SPECS.get(app_key, {}).get("terms", ())
        return self._observation_contains_terms(observation, terms)

    def _observation_contains_terms(self, observation: Observation, terms) -> bool:
        normalized_terms = [self._normalize_text(term) for term in terms if term]
        for value in self._observation_evidence(observation):
            normalized_value = self._normalize_text(value)
            if any(term and term in normalized_value for term in normalized_terms):
                return True
        return False

    def _find_element_by_terms(self, elements, terms):
        normalized_terms = [self._normalize_text(term) for term in terms if term]
        ranked = []
        for element in elements:
            name = self._normalize_text(element.name)
            if not name or element.bounds is None:
                continue
            if any(term in name for term in normalized_terms):
                ranked.append(element)
        if not ranked:
            return None
        ranked.sort(key=lambda item: item.confidence, reverse=True)
        return ranked[0]

    def _is_edit_element(self, control_type: str) -> bool:
        lowered = (control_type or "").lower()
        return any(hint in lowered for hint in EDIT_CONTROL_HINTS)

    def _is_run_dialog_observation(self, observation: Observation) -> bool:
        active_title = (observation.active_window.title if observation.active_window else "").lower()
        if any(hint in active_title for hint in RUN_DIALOG_HINTS):
            return True
        combined = " ".join(self._observation_evidence(observation)).lower()
        return any(hint in combined for hint in RUN_DIALOG_HINTS)

    def _match_target_elements(self, action: Action, elements) -> VerificationResult | None:
        for element in elements:
            if action.target.automation_id and action.target.automation_id == element.automation_id:
                self._sync_target_from_element(action, element)
                return VerificationResult(True, 0.9, "Matching automation id found")
            if action.target.name and action.target.name == element.name:
                self._sync_target_from_element(action, element)
                return VerificationResult(True, 0.78, "Matching element name found")
            if action.target.search_terms:
                haystack = self._normalize_text(
                    f"{element.name} {element.automation_id} {element.control_type}"
                )
                if any(self._normalize_text(term) in haystack for term in action.target.search_terms if term):
                    self._sync_target_from_element(action, element)
                    return VerificationResult(True, 0.72, "Matching target search terms found")
            if (
                action.target.bounds is not None
                and element.bounds is not None
                and abs(action.target.bounds.left - element.bounds.left) <= 8
                and abs(action.target.bounds.top - element.bounds.top) <= 8
                and abs(action.target.bounds.width - element.bounds.width) <= 12
                and abs(action.target.bounds.height - element.bounds.height) <= 12
            ):
                self._sync_target_from_element(action, element)
                return VerificationResult(True, 0.74, "Matching element bounds found")
        return None

    def _lookup_global_elements(self, action: Action):
        probes: list[str] = []
        if action.target.automation_id:
            probes.append(action.target.automation_id)
        if action.target.name:
            probes.append(action.target.name)
        if action.target.window_title:
            probes.append(action.target.window_title)
        if action.target.control_type:
            control_hint = action.target.control_type.split(".")[-1].strip()
            if control_hint:
                probes.append(control_hint)

        candidates = []
        seen: set[tuple[str, str, str, int, int, int, int]] = set()
        for probe in probes:
            for element in self.uia_adapter.find_elements(probe, limit=20):
                bounds = element.bounds
                key = (
                    element.name,
                    element.automation_id,
                    element.control_type,
                    bounds.left if bounds else 0,
                    bounds.top if bounds else 0,
                    bounds.width if bounds else 0,
                    bounds.height if bounds else 0,
                )
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(element)
        return candidates

    def _match_visible_bounds(self, action: Action, observation: Observation) -> VerificationResult | None:
        bounds = action.target.bounds
        if bounds is None or action.type not in {ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK, ActionType.DRAG}:
            return None
        center_x = bounds.left + bounds.width // 2
        center_y = bounds.top + bounds.height // 2
        for window in observation.visible_windows:
            if action.target.window_title and action.target.window_title != window.title:
                continue
            window_bounds = window.bounds
            if window_bounds is None:
                continue
            if (
                window_bounds.left <= center_x <= window_bounds.left + window_bounds.width
                and window_bounds.top <= center_y <= window_bounds.top + window_bounds.height
            ):
                return VerificationResult(True, 0.58, "Target bounds fall within a visible window")
        if observation.active_window and observation.active_window.bounds is not None:
            window_bounds = observation.active_window.bounds
            if (
                window_bounds.left <= center_x <= window_bounds.left + window_bounds.width
                and window_bounds.top <= center_y <= window_bounds.top + window_bounds.height
            ):
                return VerificationResult(True, 0.54, "Target bounds fall within the active window")
        return None

    def _refine_drag_target(self, action: Action, observation: Observation) -> None:
        if action.target.bounds is None and observation.active_window and observation.active_window.bounds is not None:
            action.target.window_title = action.target.window_title or observation.active_window.title
            action.target.bounds = observation.active_window.bounds
        if action.target.bounds is None:
            return
        if not self._looks_like_window_sized_drag_target(action, observation):
            return

        canvas = self._find_canvas_element(observation)
        if canvas is not None and canvas.bounds is not None:
            self._sync_target_from_element(action, canvas)
            action.target.window_title = action.target.window_title or self._active_window_title(observation)
            return

        heuristic_bounds = self._heuristic_canvas_bounds(observation)
        if heuristic_bounds is not None:
            action.target.bounds = heuristic_bounds
            action.target.window_title = action.target.window_title or self._active_window_title(observation)
            action.target.control_type = "ControlType.Pane"
            if not action.target.fallback_visual_hint:
                action.target.fallback_visual_hint = "canvas:heuristic"

    def _looks_like_window_sized_drag_target(self, action: Action, observation: Observation) -> bool:
        bounds = action.target.bounds
        if bounds is None:
            return False
        control_type = self._normalize_text(action.target.control_type)
        if any(token in control_type for token in ("pane", "document", "image", "canvas", "custom")):
            return False
        active_bounds = observation.active_window.bounds if observation.active_window else None
        if active_bounds is None:
            return True
        width_delta = abs(bounds.width - active_bounds.width)
        height_delta = abs(bounds.height - active_bounds.height)
        return width_delta <= 24 and height_delta <= 24

    def _find_canvas_element(self, observation: Observation):
        active_bounds = observation.active_window.bounds if observation.active_window else None
        if active_bounds is None:
            return None

        ranked: list[tuple[float, Any]] = []
        for element in observation.detected_elements:
            bounds = element.bounds
            if bounds is None:
                continue
            if bounds.width < max(160, active_bounds.width // 5) or bounds.height < max(120, active_bounds.height // 5):
                continue
            if bounds.left < active_bounds.left or bounds.top < active_bounds.top:
                continue
            if bounds.left + bounds.width > active_bounds.left + active_bounds.width:
                continue
            if bounds.top + bounds.height > active_bounds.top + active_bounds.height:
                continue

            score = 0.0
            normalized_name = self._normalize_text(f"{element.name} {element.automation_id}")
            normalized_type = self._normalize_text(element.control_type)
            if any(token in normalized_name for token in ("canvas", "document", "drawing", "workspace", "image", "page", "editarea")):
                score += 5.0
            if any(token in normalized_type for token in ("pane", "document", "image", "custom", "group")):
                score += 2.0
            if bounds.top >= active_bounds.top + max(48, active_bounds.height // 8):
                score += 1.5
            area_ratio = (bounds.width * bounds.height) / max(active_bounds.width * active_bounds.height, 1)
            if 0.2 <= area_ratio <= 0.9:
                score += min(area_ratio * 4.0, 3.0)
            if bounds.height >= active_bounds.height // 2:
                score += 1.0
            if score > 0:
                ranked.append((score, element))

        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def _heuristic_canvas_bounds(self, observation: Observation):
        active_window = observation.active_window
        if active_window is None or active_window.bounds is None:
            return None
        bounds = active_window.bounds
        title = self._normalize_text(active_window.title)
        if "paint" in title or "ペイント" in active_window.title:
            top_padding = max(112, int(bounds.height * 0.22))
            side_padding = max(28, int(bounds.width * 0.04))
            bottom_padding = max(34, int(bounds.height * 0.08))
        elif "gimp" in title:
            top_padding = max(86, int(bounds.height * 0.16))
            side_padding = max(24, int(bounds.width * 0.03))
            bottom_padding = max(28, int(bounds.height * 0.06))
        else:
            top_padding = max(80, int(bounds.height * 0.18))
            side_padding = max(24, int(bounds.width * 0.04))
            bottom_padding = max(28, int(bounds.height * 0.07))

        width = max(bounds.width - side_padding * 2, 120)
        height = max(bounds.height - top_padding - bottom_padding, 120)
        return type(bounds)(
            left=bounds.left + side_padding,
            top=bounds.top + top_padding,
            width=width,
            height=height,
        )

    def _sync_target_from_element(self, action: Action, element) -> None:
        if element.automation_id:
            action.target.automation_id = element.automation_id
        if element.name:
            action.target.name = element.name
        if element.control_type:
            action.target.control_type = element.control_type
        if element.bounds is not None:
            action.target.bounds = element.bounds

    def _element_signature(self, observation: Observation) -> tuple[tuple[str, str, str], ...]:
        entries = []
        for element in observation.detected_elements[:12]:
            entries.append((element.name, element.automation_id, element.control_type))
        return tuple(entries)

    def _active_window_title(self, observation: Observation) -> str:
        return observation.active_window.title if observation.active_window else ""

    def _validate_text_entry(
        self,
        action: Action,
        observation: Observation,
        previous_observation: Observation,
    ) -> ValidationResult | None:
        typed_text = (action.text or "").strip()
        if not typed_text:
            return ValidationResult(True, 0.58, action.expected_outcome or "Text input completed.")

        if self._observation_contains_text(observation, typed_text):
            return ValidationResult(True, 0.88, action.expected_outcome or f"Typed text is visible: {typed_text}")

        if (
            self._is_edit_focus(observation.focused_element)
            and action.target.bounds is not None
            and self._image_changed_in_bounds(
                previous_observation.screenshot_path,
                observation.screenshot_path,
                action.target.bounds,
            )
        ):
            return ValidationResult(True, 0.67, action.expected_outcome or "Editable field changed after typing.")

        last_execution = self._shell_result_from_observation(observation) if action.type == ActionType.SHELL_EXECUTE else (
            observation.raw_ref.get("last_execution", {}) if isinstance(observation.raw_ref, dict) else {}
        )
        if (
            isinstance(last_execution, dict)
            and bool(last_execution.get("success", False))
            and (
                self._is_edit_focus(observation.focused_element)
                or self._is_edit_element(action.target.control_type)
                or self._looks_like_editor_window(observation)
                or (action.target.fallback_visual_hint or "").strip().lower().startswith("editor:")
            )
        ):
            return ValidationResult(True, 0.58, action.expected_outcome or "Text input was sent to the focused editor.")

        return ValidationResult(False, 0.28, f"Typed text could not be verified on screen: {typed_text}")

    def _validate_marker_outcome(self, action: Action | None, observation: Observation) -> ValidationResult | None:
        if action is None:
            return None
        marker = (action.target.fallback_visual_hint or "").strip().lower()
        if not marker:
            return None
        if marker == "screen:run-dialog":
            if self._is_run_dialog_observation(observation):
                return ValidationResult(True, 0.9, action.expected_outcome or "Run dialog is visible.")
            return ValidationResult(False, 0.28, "Run dialog is not visible yet")
        if marker.startswith("launch:"):
            app_key = marker.split(":", 1)[1]
            if self._observation_has_app(observation, app_key):
                return ValidationResult(True, 0.9, action.expected_outcome or f"{app_key} is visible.")
            return ValidationResult(False, 0.26, f"{app_key} is not visible yet")
        if marker == "editor:save-request":
            if self._is_save_dialog_observation(observation):
                return ValidationResult(True, 0.9, action.expected_outcome or "The Save dialog is visible.")
            if self._looks_like_editor_window(observation) and not self._editor_window_looks_unsaved(observation):
                return ValidationResult(True, 0.82, action.expected_outcome or "The editor document is now saved.")
            return ValidationResult(False, 0.28, "The editor save flow has not started yet")
        if marker == "editor:saved":
            basename = ""
            if action.text:
                basename = Path(action.text).name
            if basename and self._observation_contains_text(observation, basename):
                return ValidationResult(True, 0.88, action.expected_outcome or "The saved file name is visible.")
            if not self._is_save_dialog_observation(observation) and self._looks_like_editor_window(observation) and not self._editor_window_looks_unsaved(observation):
                return ValidationResult(True, 0.84, action.expected_outcome or "The editor returned to a saved document.")
            return ValidationResult(False, 0.28, "The Save dialog is still open or the document still looks unsaved")
        return None

    def _observation_contains_text(self, observation: Observation, text: str) -> bool:
        needle = self._normalize_text(text)
        if not needle:
            return False
        for value in self._observation_evidence(observation):
            if needle in self._normalize_text(value):
                return True
        return False

    def _observation_evidence(self, observation: Observation) -> list[str]:
        evidence = [
            self._active_window_title(observation),
            observation.active_window.class_name if observation.active_window else "",
            observation.focused_element,
            observation.ui_tree_summary,
            *observation.textual_hints[:12],
        ]
        for window in observation.visible_windows[:12]:
            evidence.extend([window.title, window.class_name])
        for element in observation.detected_elements[:16]:
            evidence.extend([element.name, element.automation_id, element.control_type])
        return [item for item in evidence if item]

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "")).casefold()

    def _is_edit_focus(self, focused_element: str) -> bool:
        lowered = (focused_element or "").lower()
        return any(hint in lowered for hint in EDIT_CONTROL_HINTS)

    def _image_changed_in_bounds(self, previous_path: str | None, current_path: str | None, bounds) -> bool:
        if not previous_path or not current_path:
            return False
        previous = QImage(previous_path)
        current = QImage(current_path)
        if previous.isNull() or current.isNull() or previous.size() != current.size():
            return False
        if bounds.width <= 0 or bounds.height <= 0:
            return False

        padding = 8
        left = max(bounds.left - padding, 0)
        top = max(bounds.top - padding, 0)
        right = min(bounds.left + bounds.width + padding, current.width())
        bottom = min(bounds.top + bounds.height + padding, current.height())
        if right <= left or bottom <= top:
            return False

        changed = 0
        total = 0
        for y in range(top, bottom, max((bottom - top) // 12, 1)):
            for x in range(left, right, max((right - left) // 24, 1)):
                left_color = previous.pixelColor(x, y)
                right_color = current.pixelColor(x, y)
                diff = (
                    abs(left_color.red() - right_color.red())
                    + abs(left_color.green() - right_color.green())
                    + abs(left_color.blue() - right_color.blue())
                )
                if diff >= 30:
                    changed += 1
                total += 1
        return bool(total and changed / total >= 0.06)

    def _image_changed(self, previous_path: str | None, current_path: str | None, expected_outcome: str) -> tuple[bool, float]:
        if not previous_path or not current_path:
            return False, 0.0
        previous = QImage(previous_path)
        current = QImage(current_path)
        if previous.isNull() or current.isNull():
            return False, 0.0
        if previous.size() != current.size():
            return True, 0.74

        samples_x = 48
        samples_y = 27
        changed = 0
        total = 0
        total_diff = 0
        for grid_y in range(samples_y):
            for grid_x in range(samples_x):
                x = min((grid_x * current.width()) // samples_x, current.width() - 1)
                y = min((grid_y * current.height()) // samples_y, current.height() - 1)
                left = previous.pixelColor(x, y)
                right = current.pixelColor(x, y)
                diff = abs(left.red() - right.red()) + abs(left.green() - right.green()) + abs(left.blue() - right.blue())
                if diff >= 40:
                    changed += 1
                total_diff += diff
                total += 1

        changed_ratio = changed / total if total else 0.0
        average_diff = total_diff / max(total * 3, 1)
        lowered = expected_outcome.lower()
        draw_like = any(token in lowered for token in ("draw", "paint", "brush", "canvas", "stroke", "illustration", "描", "イラスト"))
        if changed_ratio >= 0.01 or average_diff >= 8.0:
            return True, 0.66
        if draw_like and (changed_ratio >= 0.002 or average_diff >= 3.0):
            return True, 0.58
        return False, 0.0
