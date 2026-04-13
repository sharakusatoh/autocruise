from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from autocruise.domain.models import (
    Action,
    ActionType,
    Bounds,
    DetectedElement,
    ExpectedSignal,
    ExpectedSignalKind,
    ExecutionResult,
    LearningEntry,
    Observation,
    ObservationKind,
    PlanStep,
    PrimarySensorSnapshot,
    TargetRef,
    ValidationResult,
    VerificationResult,
    WindowInfo,
    utc_now,
)
from autocruise.infrastructure.storage import append_jsonl


class MockAgentToolset:
    def __init__(self, root: Path, memory_path: Path, live_planner=None) -> None:
        self.root = root
        self.memory_path = memory_path
        self.live_planner = live_planner
        self.stage = 0
        self.reuse_postcheck_observation = False
        self.active_window = WindowInfo(
            window_id=101,
            title="Demo Workspace",
            class_name="MockWindow",
            bounds=Bounds(100, 100, 1200, 800),
            is_visible=True,
        )

    def list_windows(self) -> list[WindowInfo]:
        return [self.active_window]

    def focus_window(self, window_id: int) -> bool:
        return window_id == self.active_window.window_id

    def find_elements(self, query: str) -> list[DetectedElement]:
        normalized = query.lower()
        return [element for element in self._current_elements() if normalized in element.name.lower()]

    def capture_observation(
        self,
        session_id: str,
        *,
        previous_observation: Observation | None = None,
        recent_actions: list[str] | None = None,
        force_full: bool = False,
    ) -> Observation:
        _ = previous_observation, force_full
        recent_actions = recent_actions or []
        screenshot_dir = self.root / "screenshots" / f"session_{session_id}"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / f"mock_step_{self.stage:03d}.png"
        self._write_mock_image(screenshot_path)
        elements = self._current_elements()
        sensor_snapshot = PrimarySensorSnapshot(
            active_window=self.active_window,
            focused_element=elements[0].name if elements else "",
            event_counts={},
            active_automation_backend="mock",
            fingerprint=f"mock-{self.stage}",
        )
        return Observation(
            screenshot_path=str(screenshot_path),
            active_window=self.active_window,
            visible_windows=[self.active_window],
            detected_elements=elements,
            ui_tree_summary=f"Mock stage {self.stage} with {len(elements)} visible elements",
            cursor_position=(250, 180),
            focused_element=elements[0].name if elements else "",
            textual_hints=[f"demo-stage-{self.stage}", self.active_window.title],
            recent_actions=recent_actions[-5:] or [f"stage-{self.stage}"],
            raw_ref={
                "mode": "mock",
                "stage": self.stage,
                "sensor_snapshot": asdict(sensor_snapshot),
                "observation_kind": ObservationKind.FULL.value,
                "vision_fallback_required": False,
            },
        )

    def plan_next_action(
        self,
        goal: str,
        observation: Observation,
        recent_actions: list[Action],
        context=None,
    ) -> PlanStep:
        if self.live_planner is not None:
            live_plan = self.live_planner.plan(goal, observation, recent_actions, context)
            if live_plan is not None:
                return live_plan

        normalized = goal.lower()
        if self.stage == 0:
            return PlanStep(
                summary="Focus the main working window",
                action=Action(
                    type=ActionType.FOCUS_WINDOW,
                    target=TargetRef(window_title=self.active_window.title, name=self.active_window.title),
                    purpose="Bring the target application to the foreground",
                    reason="Execution starts by confirming control of the intended window",
                    preconditions=["A visible application window exists"],
                    expected_outcome="The working window is active",
                    confidence=0.92,
                    expected_signals=[ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target=self.active_window.title)],
                ),
                reasoning="Mock stage 0 always starts by focusing the target window",
            )

        if self.stage == 1:
            return PlanStep(
                summary="Click the primary action button",
                action=Action(
                    type=ActionType.CLICK,
                    target=TargetRef(
                        window_title=self.active_window.title,
                        name="Primary Action",
                        control_type="button",
                        bounds=Bounds(260, 200, 180, 48),
                    ),
                    purpose="Advance the task to the editable stage",
                    reason="The primary action is visible and uniquely named",
                    preconditions=["The button is visible"],
                    expected_outcome="The workflow enters the editable stage",
                    confidence=0.84,
                    expected_signals=[ExpectedSignal(ExpectedSignalKind.ELEMENT_ENABLED_CHANGED, target="Primary Action")],
                ),
                reasoning="Mock stage 1 presents one clear button",
            )

        if self.stage == 2:
            if any(keyword in normalized for keyword in ("save", "overwrite", "settings", "system")):
                return PlanStep(
                    summary="Save the current changes",
                    action=Action(
                        type=ActionType.HOTKEY,
                        target=TargetRef(window_title=self.active_window.title, name="Save"),
                        purpose="Save the current changes",
                        reason="The user request implies persistence or settings mutation",
                        preconditions=["Editable content exists"],
                        expected_outcome="A save or settings mutation is applied",
                        confidence=0.72,
                        hotkey="ctrl+s",
                        expected_signals=[ExpectedSignal(ExpectedSignalKind.WINDOW_CHANGED, target="Save")],
                    ),
                    reasoning="Risky demo step",
                )

            return PlanStep(
                summary="Type the final note",
                action=Action(
                    type=ActionType.TYPE_TEXT,
                    target=TargetRef(
                        window_title=self.active_window.title,
                        name="Notes",
                        control_type="edit",
                        bounds=Bounds(240, 320, 480, 44),
                    ),
                    purpose="Apply the requested content",
                    reason="The text box is visible and ready for input",
                    preconditions=["Input field is visible"],
                    expected_outcome="The note field contains the new content",
                    confidence=0.78,
                    text="AutoCruise demo completed",
                    expected_signals=[ExpectedSignal(ExpectedSignalKind.TEXT_CHANGED, target="Notes")],
                ),
                reasoning="Mock stage 2 applies one text change",
            )

        return PlanStep(
            summary="The mock workflow is complete",
            is_complete=True,
            completion_reason="No more demo actions remain",
            reasoning="Stage 3 terminates the mock run",
        )

    def verify_target(self, action: Action, observation: Observation) -> VerificationResult:
        if action.type == ActionType.SHELL_EXECUTE:
            if action.shell_command.strip():
                return VerificationResult(True, 0.95, "Mock shell action is ready")
            return VerificationResult(False, 0.0, "Shell command is empty")
        if action.type == ActionType.FOCUS_WINDOW:
            for window in observation.visible_windows:
                if window.title == action.target.window_title:
                    return VerificationResult(True, 0.95, "Matching window is visible")
            return VerificationResult(False, 0.0, "Requested window is not visible")

        for element in observation.detected_elements:
            if action.target.name and element.name == action.target.name:
                return VerificationResult(True, 0.9, "Matching element is visible")
        return VerificationResult(False, 0.2, "Target element is not visible")

    def execute_action(self, action: Action) -> ExecutionResult:
        self.stage += 1
        return ExecutionResult(success=True, details=f"Mock executed {action.type.value}")

    def wait_for_expected_change(
        self,
        session_id: str,
        action: Action,
        previous_observation: Observation,
        *,
        recent_actions: list[str] | None = None,
        execution_result: ExecutionResult | None = None,
    ) -> Observation:
        observation = self.capture_observation(
            session_id,
            previous_observation=previous_observation,
            recent_actions=recent_actions,
            force_full=True,
        )
        observation.raw_ref["wait"] = {
            "matched": True,
            "matched_signal": action.expected_signals[0].kind.value if action.expected_signals else "",
            "wait_satisfied_by": "mock",
        }
        if execution_result is not None:
            observation.raw_ref["last_execution"] = {
                "success": bool(execution_result.success),
                "details": execution_result.details,
                "error": execution_result.error,
                "payload": dict(execution_result.payload or {}),
            }
        return observation

    def validate_outcome(
        self,
        expected_outcome: str,
        observation: Observation,
        previous_observation: Observation | None = None,
        action: Action | None = None,
    ) -> ValidationResult:
        if previous_observation and observation.raw_ref.get("stage", 0) > previous_observation.raw_ref.get("stage", 0):
            return ValidationResult(True, 0.9, expected_outcome)
        return ValidationResult(False, 0.3, "Mock stage did not advance")

    def update_memory(self, entry: LearningEntry) -> None:
        target = self.root / "apps" / entry.app / "app_memory.jsonl"
        append_jsonl(target if target.exists() else self.memory_path, asdict(entry))

    def abort_session(self, reason: str) -> None:
        self.stage = max(self.stage, 3)

    def build_learning_entry(
        self,
        session_id: str,
        action: Action,
        observation: Observation,
        app_name: str,
        task_name: str = "",
    ) -> LearningEntry:
        now = utc_now()
        return LearningEntry(
            id=str(uuid.uuid4()),
            app=app_name,
            scope="task-pattern",
            observation_pattern=observation.ui_tree_summary,
            successful_action=f"{action.type.value}:{action.target.name or action.target.window_title}",
            expected_outcome=action.expected_outcome,
            confidence=min(0.55 + action.confidence / 2, 0.95),
            evidence_count=1,
            failure_count=0,
            first_seen_at=now,
            last_verified_at=now,
            invalidation_hint="If the target control name or layout changes",
            source_session_id=session_id,
            task_id=task_name,
            stage=str(self.stage),
        )

    def _current_elements(self) -> list[DetectedElement]:
        if self.stage == 0:
            return [
                DetectedElement(101, name="Demo Workspace", control_type="window", confidence=0.95),
                DetectedElement(101, name="Start", control_type="button", confidence=0.82),
            ]
        if self.stage == 1:
            return [
                DetectedElement(101, name="Primary Action", control_type="button", confidence=0.91),
                DetectedElement(101, name="Cancel", control_type="button", confidence=0.72),
            ]
        if self.stage == 2:
            return [
                DetectedElement(101, name="Notes", control_type="edit", confidence=0.88),
                DetectedElement(101, name="Save As", control_type="button", confidence=0.65),
            ]
        return [DetectedElement(101, name="Completed", control_type="text", confidence=0.98)]

    def _write_mock_image(self, path: Path) -> None:
        width = 480
        height = 270
        image = QImage(width, height, QImage.Format_RGB32)
        for y in range(height):
            for x in range(width):
                red = (x + self.stage * 40) % 255
                green = (y * 2 + 60) % 255
                blue = (80 + self.stage * 50) % 255
                if 120 < x < 360 and 90 < y < 150:
                    red, green, blue = 240, 240, 240
                image.setPixelColor(x, y, QColor(red, green, blue))
        image.save(str(path), "PNG")
