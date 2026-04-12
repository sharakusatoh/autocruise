from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Protocol

from autocruise.application.retrieval import RetrievalPlanner
from autocruise.application.state_machine import InvalidStateTransition, SessionStateMachine
from autocruise.domain.models import (
    Action,
    CompletedData,
    ExecutingData,
    FailedData,
    LearningEntry,
    LearningUpdateData,
    LoadingContextData,
    ObservingData,
    PausedData,
    PlanStep,
    PlanningData,
    PostcheckData,
    PrecheckData,
    ReplanningData,
    SessionMission,
    SessionSnapshot,
    SessionState,
    StoppedData,
    utc_now,
)
from autocruise.infrastructure.storage import (
    JsonlLogger,
    ScreenshotRetentionService,
    WorkspacePaths,
    load_structured,
    normalize_max_steps_preference,
)

MAX_STEPS_DEFAULT: int | None = None
MAX_REPLANS_PER_STEP = 4
MAX_REPEAT_FAILURES = 2
MAX_PRECHECK_MISMATCHES = 3
CAPTURE_SUFFIXES = {".png", ".ppm", ".jpg", ".jpeg", ".webp", ".gif"}


class AgentToolset(Protocol):
    def capture_observation(
        self,
        session_id: str,
        *,
        previous_observation=None,
        recent_actions: list[str] | None = None,
        force_full: bool = False,
    ): ...
    def list_windows(self): ...
    def focus_window(self, window_id: int) -> bool: ...
    def find_elements(self, query: str): ...
    def plan_next_action(self, goal: str, observation, recent_actions: list[Action], context=None) -> PlanStep: ...
    def verify_target(self, action: Action, observation): ...
    def execute_action(self, action: Action): ...
    def wait_for_expected_change(self, session_id: str, action: Action, previous_observation, *, recent_actions: list[str] | None = None): ...
    def validate_outcome(self, expected_outcome: str, observation, previous_observation=None, action: Action | None = None): ...
    def update_memory(self, entry: LearningEntry) -> None: ...
    def abort_session(self, reason: str) -> None: ...
    def build_learning_entry(self, session_id: str, action: Action, observation, app_name: str, task_name: str = "") -> LearningEntry: ...


class SessionOrchestrator:
    def __init__(
        self,
        paths: WorkspacePaths,
        toolset_factory: Callable[[], AgentToolset],
        event_sink: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.paths = paths
        self.paths.ensure()
        self.logger = JsonlLogger(paths)
        self.retention = ScreenshotRetentionService(paths)
        self.retrieval = RetrievalPlanner(paths)
        self.state_machine = SessionStateMachine()
        self.event_sink = event_sink
        self.toolset_factory = toolset_factory
        self._pause_requested = False
        self._stop_requested = False

    def pause(self) -> None:
        self._pause_requested = True

    def resume(self) -> None:
        self._pause_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self, instruction: str, task_id: str = "", trigger: str = "manual") -> SessionSnapshot:
        self._pause_requested = False
        self._stop_requested = False

        mission = SessionMission(instruction=instruction, task_id=task_id, trigger=trigger)
        session_id = uuid.uuid4().hex[:8]
        snapshot = self.state_machine.create(session_id, mission)
        self._emit("state", {"snapshot": snapshot})

        try:
            preferences = load_structured(self.paths.preferences_path())
            _max_steps_limit_enabled, max_steps = normalize_max_steps_preference(preferences)
            autonomy_mode = str(preferences.get("autonomy_mode", "autonomous") or "autonomous")
            self.retention.purge(
                default_ttl_days=int(preferences.get("screenshot_ttl_days", 3)),
                important_ttl_days=int(
                    preferences.get(
                        "keep_important_screenshots_days",
                        preferences.get("keep_high_risk_screenshots_days", 14),
                    )
                ),
            )
            toolset = self.toolset_factory()
            snapshot = self._transition(
                snapshot,
                SessionState.LOADING_CONTEXT,
                LoadingContextData(goal=instruction, stage="initial"),
                "Load mission context",
            )
            context = self.retrieval.retrieve(instruction, stage="initial")
            snapshot.retrieved_context = context
            self._log_retrieval(session_id, context)

            recent_actions: list[Action] = []
            minor_failures = 0
            replans = 0
            last_failure_reason = ""
            failure_counts: dict[str, int] = {}
            step_count = 0
            confirmation_notes: list[str] = []
            learning_updates = 0

            while True:
                if self._stop_requested:
                    return self._finalize_history(
                        self._stop(snapshot, "User requested stop"),
                        step_count,
                        confirmation_notes,
                        learning_updates,
                    )

                snapshot = self._maybe_pause(snapshot, SessionState.OBSERVING)
                snapshot = self._transition(
                    snapshot,
                    SessionState.OBSERVING,
                    ObservingData(reason="Refresh structured state before planning"),
                    "Observe current state",
                )
                observation = toolset.capture_observation(
                    session_id,
                    previous_observation=snapshot.current_observation,
                    recent_actions=self._recent_action_labels(recent_actions),
                    force_full=snapshot.current_observation is None,
                )
                snapshot.current_observation = observation
                self._emit("observation", {"observation": observation})

                snapshot = self._transition(
                    snapshot,
                    SessionState.PLANNING,
                    PlanningData(goal=instruction),
                    "Plan the next single action",
                )
                plan = toolset.plan_next_action(
                    instruction,
                    observation,
                    recent_actions,
                    self._build_planning_context(
                        snapshot.session_id,
                        snapshot.retrieved_context,
                        step_count,
                        max_steps,
                        last_failure_reason,
                        failure_counts,
                        autonomy_mode,
                    ),
                )
                self._emit("plan", {"plan": plan})

                if plan.is_complete:
                    return self._finalize_history(
                        self._complete(snapshot, plan.completion_reason or plan.summary),
                        step_count,
                        confirmation_notes,
                        learning_updates,
                    )
                if not plan.action:
                    return self._finalize_history(
                        self._fail(snapshot, "Planner returned no action"),
                        step_count,
                        confirmation_notes,
                        learning_updates,
                    )

                action = plan.action
                snapshot.last_action = action
                snapshot.summary = plan.summary

                snapshot = self._maybe_pause(snapshot, SessionState.PRECHECK)
                snapshot = self._transition(
                    snapshot,
                    SessionState.PRECHECK,
                    PrecheckData(action_summary=plan.summary),
                    "Resolve target before execution",
                )
                precheck_observation = snapshot.current_observation
                verification = toolset.verify_target(action, precheck_observation)
                if not verification.matched:
                    failure_count = self._record_failure(failure_counts, verification.reason)
                    minor_failures += 1
                    last_failure_reason = verification.reason
                    if (
                        minor_failures <= MAX_PRECHECK_MISMATCHES
                        and replans < MAX_REPLANS_PER_STEP
                        and failure_count <= MAX_REPEAT_FAILURES
                    ):
                        replans += 1
                        snapshot = self._transition(
                            snapshot,
                            SessionState.REPLANNING,
                            ReplanningData(failure_reason=verification.reason, attempt=replans),
                            "Precheck failed; replanning",
                        )
                        context = self.retrieval.retrieve(instruction, stage="replan", failure_reason=verification.reason)
                        snapshot.retrieved_context = context
                        self._log_retrieval(session_id, context)
                        continue
                    return self._finalize_history(
                        self._fail(snapshot, f"Repeated target verification failure: {verification.reason}"),
                        step_count,
                        confirmation_notes,
                        learning_updates,
                    )

                snapshot = self._maybe_pause(snapshot, SessionState.EXECUTING)
                snapshot = self._transition(
                    snapshot,
                    SessionState.EXECUTING,
                    ExecutingData(action_summary=plan.summary),
                    "Execute one action",
                )
                execution = toolset.execute_action(action)
                if not execution.success:
                    failure_reason = execution.error or execution.details
                    failure_count = self._record_failure(failure_counts, failure_reason)
                    last_failure_reason = failure_reason
                    if replans >= MAX_REPLANS_PER_STEP or failure_count > MAX_REPEAT_FAILURES:
                        return self._finalize_history(
                            self._fail(snapshot, failure_reason),
                            step_count,
                            confirmation_notes,
                            learning_updates,
                        )
                    replans += 1
                    snapshot = self._transition(
                        snapshot,
                        SessionState.REPLANNING,
                        ReplanningData(failure_reason=failure_reason, attempt=replans),
                        "Execution failed; replanning",
                    )
                    context = self.retrieval.retrieve(instruction, stage="replan", failure_reason=failure_reason)
                    snapshot.retrieved_context = context
                    self._log_retrieval(session_id, context)
                    continue

                snapshot = self._transition(
                    snapshot,
                    SessionState.POSTCHECK,
                    PostcheckData(action_summary=plan.summary),
                    "Wait for expected change after execution",
                )
                postcheck_observation = toolset.wait_for_expected_change(
                    session_id,
                    action,
                    precheck_observation,
                    recent_actions=self._recent_action_labels(recent_actions),
                )
                snapshot.current_observation = postcheck_observation
                validation = toolset.validate_outcome(
                    action.expected_outcome,
                    postcheck_observation,
                    previous_observation=precheck_observation,
                    action=action,
                )
                self.logger.execution(
                    {
                        "session_id": session_id,
                        "instruction": instruction,
                        "action": asdict(action),
                        "execution": asdict(execution),
                        "validation": asdict(validation),
                        "timestamp": postcheck_observation.timestamp,
                    }
                )

                if not validation.success:
                    failure_count = self._record_failure(failure_counts, validation.details)
                    last_failure_reason = validation.details
                    if replans >= MAX_REPLANS_PER_STEP or failure_count > MAX_REPEAT_FAILURES:
                        return self._finalize_history(
                            self._fail(snapshot, f"Validation failed after replanning: {validation.details}"),
                            step_count,
                            confirmation_notes,
                            learning_updates,
                        )
                    replans += 1
                    snapshot = self._transition(
                        snapshot,
                        SessionState.REPLANNING,
                        ReplanningData(failure_reason=validation.details, attempt=replans),
                        "Validation failed; replanning",
                    )
                    context = self.retrieval.retrieve(instruction, stage="replan", failure_reason=validation.details)
                    snapshot.retrieved_context = context
                    self._log_retrieval(session_id, context)
                    continue

                recent_actions.append(action)
                step_count += 1
                minor_failures = 0
                replans = 0
                last_failure_reason = ""
                failure_counts.clear()

                app_name = (
                    snapshot.retrieved_context.app_candidates[0]
                    if snapshot.retrieved_context and snapshot.retrieved_context.app_candidates
                    else "general"
                )
                task_name = (
                    snapshot.retrieved_context.task_candidates[0]
                    if snapshot.retrieved_context and snapshot.retrieved_context.task_candidates
                    else ""
                )
                learning_entry = toolset.build_learning_entry(
                    session_id,
                    action,
                    postcheck_observation,
                    app_name,
                    task_name,
                )
                snapshot = self._transition(
                    snapshot,
                    SessionState.LEARNING_UPDATE,
                    LearningUpdateData(entries=1),
                    "Append learning memory",
                )
                toolset.update_memory(learning_entry)
                self.logger.learning({"session_id": session_id, "entry": asdict(learning_entry)})
                learning_updates += 1
                if max_steps is not None and step_count >= max_steps:
                    return self._finalize_history(
                        self._stop(snapshot, "最大ステップ数に達したため停止しました。"),
                        step_count,
                        confirmation_notes,
                        learning_updates,
                    )
        except InvalidStateTransition as exc:
            return self._finalize_history(self._fail(snapshot, str(exc)), 0, [], 0)
        except Exception as exc:  # noqa: BLE001
            return self._finalize_history(self._fail(snapshot, str(exc)), 0, [], 0)

    def _transition(self, snapshot: SessionSnapshot, new_state: SessionState, payload, reason: str) -> SessionSnapshot:
        snapshot = self.state_machine.transition(snapshot, new_state, payload, reason)
        self.logger.audit(
            {
                "session_id": snapshot.session_id,
                "type": "state_transition",
                "from_state": snapshot.transitions[-1].from_state.value,
                "to_state": snapshot.transitions[-1].to_state.value,
                "reason": reason,
                "timestamp": snapshot.transitions[-1].timestamp,
            }
        )
        self._emit("state", {"snapshot": snapshot})
        return snapshot

    def _recent_action_labels(self, recent_actions: list[Action]) -> list[str]:
        labels: list[str] = []
        for action in recent_actions[-5:]:
            target = action.target.name or action.target.window_title or action.target.automation_id
            labels.append(f"{action.type.value}:{target}")
        return labels

    def _emit(self, kind: str, payload: dict) -> None:
        if self.event_sink is not None:
            self.event_sink(kind, payload)

    def _complete(self, snapshot: SessionSnapshot, summary: str) -> SessionSnapshot:
        completed = self._transition(
            snapshot,
            SessionState.COMPLETED,
            CompletedData(summary=summary or "Completed"),
            "Session completed",
        )
        self._emit("finished", {"snapshot": completed})
        return completed

    def _stop(self, snapshot: SessionSnapshot, reason: str) -> SessionSnapshot:
        stopped = self._transition(
            snapshot,
            SessionState.STOPPED,
            StoppedData(reason=reason),
            reason,
        )
        self._emit("finished", {"snapshot": stopped})
        return stopped

    def _fail(self, snapshot: SessionSnapshot, reason: str) -> SessionSnapshot:
        if snapshot.state == SessionState.IDLE:
            snapshot = self._transition(
                snapshot,
                SessionState.LOADING_CONTEXT,
                LoadingContextData(goal=snapshot.mission.instruction, stage="failure"),
                "Prepare failure state",
            )
        failed = self._transition(
            snapshot,
            SessionState.FAILED,
            FailedData(reason=reason),
            reason,
        )
        self._emit("finished", {"snapshot": failed})
        return failed

    def _maybe_pause(self, snapshot: SessionSnapshot, resume_target: SessionState) -> SessionSnapshot:
        if not self._pause_requested:
            return snapshot

        paused = self._transition(
            snapshot,
            SessionState.PAUSED,
            PausedData(resume_target=resume_target),
            "Paused by user",
        )
        while self._pause_requested and not self._stop_requested:
            time.sleep(0.1)
        if self._stop_requested:
            return paused
        return self._transition(paused, resume_target, self._resume_payload(resume_target, snapshot.summary), "Resume execution")

    def _resume_payload(self, resume_target: SessionState, summary: str):
        if resume_target == SessionState.OBSERVING:
            return ObservingData(reason="Resume after pause")
        if resume_target == SessionState.PRECHECK:
            return PrecheckData(action_summary=summary or "Resume precheck")
        return ExecutingData(action_summary=summary or "Resume execution")

    def _build_planning_context(
        self,
        session_id: str,
        retrieved_context,
        step_count: int,
        max_steps: int | None,
        last_failure_reason: str,
        failure_counts: dict[str, int],
        autonomy_mode: str,
    ) -> dict[str, object]:
        return {
            "session_id": session_id,
            "retrieved_context": retrieved_context,
            "autopilot_mode": True,
            "autonomy_mode": autonomy_mode,
            "step_count": step_count,
            "remaining_steps": max(max_steps - step_count, 0) if max_steps is not None else None,
            "recent_failure_reason": last_failure_reason,
            "recent_failure_count": failure_counts.get(last_failure_reason, 0) if last_failure_reason else 0,
            "confirmation_policy": "Do not ask the user. Keep progressing and finish the task unless the desktop is genuinely blocked.",
        }

    def _record_failure(self, failure_counts: dict[str, int], reason: str) -> int:
        if not reason:
            return 0
        failure_counts[reason] = failure_counts.get(reason, 0) + 1
        return failure_counts[reason]

    def _log_retrieval(self, session_id: str, context) -> None:
        self.logger.audit(
            {
                "session_id": session_id,
                "type": "retrieval",
                "goal": context.goal,
                "stage": context.stage,
                "app_candidates": context.app_candidates,
                "task_candidates": context.task_candidates,
                "selections": [asdict(item) for item in context.selections],
            }
        )

    def _finalize_history(
        self,
        snapshot: SessionSnapshot,
        step_count: int,
        confirmation_notes: list[str],
        learning_updates: int,
    ) -> SessionSnapshot:
        result_map = {
            SessionState.COMPLETED: "success",
            SessionState.FAILED: "failed",
            SessionState.STOPPED: "stopped",
        }
        result = result_map.get(snapshot.state, "stopped")
        screenshot_dir = self.paths.session_screenshot_dir(snapshot.session_id)
        captures = [str(path) for path in sorted(screenshot_dir.iterdir()) if path.is_file() and path.suffix.lower() in CAPTURE_SUFFIXES]
        context = snapshot.retrieved_context
        target_app = ""
        if context and context.app_candidates:
            target_app = context.app_candidates[0]
        elif snapshot.current_observation and snapshot.current_observation.active_window:
            target_app = snapshot.current_observation.active_window.title

        message = getattr(snapshot.payload, "summary", "") or getattr(snapshot.payload, "reason", "")
        self.logger.history(
            {
                "session_id": snapshot.session_id,
                "executed_at": snapshot.mission.created_at,
                "completed_at": utc_now(),
                "instruction": snapshot.mission.instruction,
                "task_id": snapshot.mission.task_id,
                "trigger": snapshot.mission.trigger,
                "target_app": target_app,
                "result": result,
                "step_count": step_count,
                "message": message,
                "failure_reason": getattr(snapshot.payload, "reason", ""),
                "important_confirmations": confirmation_notes,
                "used_knowledge": [item.path for item in context.selections] if context else [],
                "saved_captures": captures,
                "learning_updated": learning_updates > 0,
                "learning_update_count": learning_updates,
                "flow": [item.to_state.value for item in snapshot.transitions],
            }
        )
        return snapshot
