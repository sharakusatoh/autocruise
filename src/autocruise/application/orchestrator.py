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
    ActionType,
    CompletedData,
    ExecutingData,
    FailedData,
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
    def wait_for_expected_change(self, session_id: str, action: Action, previous_observation, *, recent_actions: list[str] | None = None, execution_result=None): ...
    def validate_outcome(self, expected_outcome: str, observation, previous_observation=None, action: Action | None = None): ...
    def abort_session(self, reason: str) -> None: ...


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
        self._active_toolset: AgentToolset | None = None

    def pause(self) -> None:
        self._pause_requested = True

    def resume(self) -> None:
        self._pause_requested = False

    def stop(self) -> None:
        self._stop_requested = True
        toolset = self._active_toolset
        if toolset is not None:
            try:
                toolset.abort_session("User requested stop")
            except Exception:  # noqa: BLE001
                pass

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
            self._active_toolset = toolset
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
            allow_postcheck_observation_reuse = bool(getattr(toolset, "reuse_postcheck_observation", True))
            reuse_postcheck_observation = False

            while True:
                if self._stop_requested:
                    return self._finalize_history(
                        self._stop(snapshot, "User requested stop"),
                        step_count,
                        confirmation_notes,
                    )

                if allow_postcheck_observation_reuse and reuse_postcheck_observation and snapshot.current_observation is not None:
                    if snapshot.state == SessionState.REPLANNING:
                        snapshot = self._transition(
                            snapshot,
                            SessionState.OBSERVING,
                            ObservingData(reason="Reuse the latest observation while replanning"),
                            "Reuse current observation for replanning",
                        )
                    observation = snapshot.current_observation
                    reuse_postcheck_observation = False
                else:
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
                    stopped = self._stop_if_requested(snapshot, step_count, confirmation_notes)
                    if stopped is not None:
                        return stopped

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
                        recent_actions,
                        observation,
                    ),
                )
                self._emit("plan", {"plan": plan})

                if plan.is_complete:
                    return self._finalize_history(
                        self._complete(snapshot, plan.completion_reason or plan.summary),
                        step_count,
                        confirmation_notes,
                    )
                if not plan.action:
                    return self._finalize_history(
                        self._fail(snapshot, "Planner returned no action"),
                        step_count,
                        confirmation_notes,
                    )

                action = plan.action
                snapshot.last_action = action
                snapshot.summary = plan.summary
                repeat_reason = self._detect_repeated_action_without_progress(action, recent_actions, snapshot.current_observation)
                if repeat_reason:
                    failure_count = self._record_failure(failure_counts, repeat_reason)
                    last_failure_reason = repeat_reason
                    if replans >= MAX_REPLANS_PER_STEP or failure_count > MAX_REPEAT_FAILURES:
                        return self._finalize_history(
                            self._fail(snapshot, repeat_reason),
                            step_count,
                            confirmation_notes,
                        )
                    replans += 1
                    snapshot = self._transition(
                        snapshot,
                        SessionState.REPLANNING,
                        ReplanningData(failure_reason=repeat_reason, attempt=replans),
                        "Repeated action without new progress; replanning",
                    )
                    reuse_postcheck_observation = True
                    context = self.retrieval.retrieve(instruction, stage="replan", failure_reason=repeat_reason)
                    snapshot.retrieved_context = context
                    self._log_retrieval(session_id, context)
                    continue
                stopped = self._stop_if_requested(snapshot, step_count, confirmation_notes)
                if stopped is not None:
                    return stopped

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
                        reuse_postcheck_observation = False
                        context = self.retrieval.retrieve(instruction, stage="replan", failure_reason=verification.reason)
                        snapshot.retrieved_context = context
                        self._log_retrieval(session_id, context)
                        continue
                    return self._finalize_history(
                        self._fail(snapshot, f"Repeated target verification failure: {verification.reason}"),
                        step_count,
                        confirmation_notes,
                    )
                stopped = self._stop_if_requested(snapshot, step_count, confirmation_notes)
                if stopped is not None:
                    return stopped

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
                        )
                    replans += 1
                    snapshot = self._transition(
                        snapshot,
                        SessionState.REPLANNING,
                        ReplanningData(failure_reason=failure_reason, attempt=replans),
                        "Execution failed; replanning",
                    )
                    reuse_postcheck_observation = False
                    context = self.retrieval.retrieve(instruction, stage="replan", failure_reason=failure_reason)
                    snapshot.retrieved_context = context
                    self._log_retrieval(session_id, context)
                    continue
                stopped = self._stop_if_requested(snapshot, step_count, confirmation_notes)
                if stopped is not None:
                    return stopped

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
                    execution_result=execution,
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
                        )
                    replans += 1
                    snapshot = self._transition(
                        snapshot,
                        SessionState.REPLANNING,
                        ReplanningData(failure_reason=validation.details, attempt=replans),
                        "Validation failed; replanning",
                    )
                    reuse_postcheck_observation = False
                    context = self.retrieval.retrieve(instruction, stage="replan", failure_reason=validation.details)
                    snapshot.retrieved_context = context
                    self._log_retrieval(session_id, context)
                    continue
                stopped = self._stop_if_requested(snapshot, step_count, confirmation_notes)
                if stopped is not None:
                    return stopped

                recent_actions.append(action)
                step_count += 1
                minor_failures = 0
                replans = 0
                last_failure_reason = ""
                failure_counts.clear()
                reuse_postcheck_observation = allow_postcheck_observation_reuse

                if reuse_postcheck_observation:
                    snapshot = self._transition(
                        snapshot,
                        SessionState.OBSERVING,
                        ObservingData(reason="Use postcheck observation for the next plan"),
                        "Use postcheck observation for next planning step",
                    )
                if max_steps is not None and step_count >= max_steps:
                    return self._finalize_history(
                        self._stop(snapshot, "最大ステップ数に達したため停止しました。"),
                        step_count,
                        confirmation_notes,
                    )
        except InvalidStateTransition as exc:
            return self._finalize_history(self._fail(snapshot, str(exc)), 0, [])
        except Exception as exc:  # noqa: BLE001
            return self._finalize_history(self._fail(snapshot, str(exc)), 0, [])
        finally:
            self._active_toolset = None

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

    def _stop_if_requested(
        self,
        snapshot: SessionSnapshot,
        step_count: int,
        confirmation_notes: list[str],
    ) -> SessionSnapshot | None:
        if not self._stop_requested:
            return None
        return self._finalize_history(
            self._stop(snapshot, "User requested stop"),
            step_count,
            confirmation_notes,
        )

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
        recent_actions: list[Action] | None = None,
        observation=None,
    ) -> dict[str, object]:
        repeat_guard = self._repeat_guard_payload(recent_actions or [], observation)
        return {
            "session_id": session_id,
            "retrieved_context": retrieved_context,
            "autopilot_mode": True,
            "autonomy_mode": autonomy_mode,
            "step_count": step_count,
            "remaining_steps": max(max_steps - step_count, 0) if max_steps is not None else None,
            "recent_failure_reason": last_failure_reason,
            "recent_failure_count": failure_counts.get(last_failure_reason, 0) if last_failure_reason else 0,
            "repeat_guard": repeat_guard,
            "confirmation_policy": "Do not ask the user. Keep progressing and finish the task unless the desktop is genuinely blocked.",
        }

    def _repeat_guard_payload(self, recent_actions: list[Action], observation) -> dict[str, object]:
        last_signature = self._action_signature(recent_actions[-1]) if recent_actions else ""
        previous_signature = self._action_signature(recent_actions[-2]) if len(recent_actions) >= 2 else ""
        stable = self._observation_is_stable(observation)
        return {
            "last_action_signature": last_signature,
            "previous_action_signature": previous_signature,
            "repeat_streak": 2 if last_signature and last_signature == previous_signature else (1 if last_signature else 0),
            "observation_stable": stable,
            "avoid_signature": last_signature if stable and last_signature else "",
        }

    def _detect_repeated_action_without_progress(self, action: Action, recent_actions: list[Action], observation) -> str:
        if not recent_actions or observation is None:
            return ""
        if action.type not in {
            ActionType.CLICK,
            ActionType.TYPE_TEXT,
            ActionType.HOTKEY,
            ActionType.FOCUS_WINDOW,
            ActionType.SHELL_EXECUTE,
            ActionType.WAIT,
        }:
            return ""
        if not self._observation_is_stable(observation):
            return ""
        current_signature = self._action_signature(action)
        if not current_signature:
            return ""
        if current_signature != self._action_signature(recent_actions[-1]):
            return ""
        return f"Repeated action without new progress: {current_signature}"

    def _observation_is_stable(self, observation) -> bool:
        if observation is None or not isinstance(getattr(observation, "raw_ref", None), dict):
            return False
        raw_ref = observation.raw_ref
        change_summary = str(raw_ref.get("change_summary", "")).strip().lower()
        planner_skip_reason = str(raw_ref.get("planner_skip_reason", "")).strip().lower()
        if planner_skip_reason == "sensor_unchanged":
            return True
        return change_summary in {"", "no structured changes.", "no structured changes"}

    def _action_signature(self, action: Action | None) -> str:
        if action is None:
            return ""
        target = action.target.automation_id or action.target.name or action.target.window_title
        parts = [action.type.value, str(target or "").strip().lower()]
        if action.type == ActionType.TYPE_TEXT:
            parts.append(str(action.text or "").strip())
        elif action.type == ActionType.HOTKEY:
            parts.append(str(action.hotkey or "").strip().lower())
        elif action.type == ActionType.SHELL_EXECUTE:
            parts.append(str(action.shell_kind or "").strip().lower())
            parts.append(str(action.shell_command or "").strip().lower())
        return "|".join(parts)

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
                "used_context": [item.path for item in context.selections] if context else [],
                "saved_captures": captures,
                "flow": [item.to_state.value for item in snapshot.transitions],
            }
        )
        return snapshot
