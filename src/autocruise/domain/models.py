from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionState(str, Enum):
    IDLE = "IDLE"
    LOADING_CONTEXT = "LOADING_CONTEXT"
    OBSERVING = "OBSERVING"
    PLANNING = "PLANNING"
    PRECHECK = "PRECHECK"
    EXECUTING = "EXECUTING"
    POSTCHECK = "POSTCHECK"
    REPLANNING = "REPLANNING"
    LEARNING_UPDATE = "LEARNING_UPDATE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionType(str, Enum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    DRAG = "drag"
    TYPE_TEXT = "type_text"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    WAIT = "wait"
    FOCUS_WINDOW = "focus_window"


class AdapterMode(str, Enum):
    MOCK = "mock"
    WINDOWS = "windows"


class ScheduleKind(str, Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    WEEKDAYS = "weekdays"
    INTERVAL = "interval"
    RANDOM_HOURLY = "random_hourly"
    RANDOM_DAILY = "random_daily"


class ScheduledJobState(str, Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ObservationKind(str, Enum):
    FULL = "full"
    STRUCTURED = "structured"
    REUSED = "reused"
    VISION_FALLBACK = "vision_fallback"


class ExpectedSignalKind(str, Enum):
    WINDOW_CHANGED = "window_changed"
    FOCUS_CHANGED = "focus_changed"
    ELEMENT_APPEARED = "element_appeared"
    ELEMENT_DISAPPEARED = "element_disappeared"
    ELEMENT_ENABLED_CHANGED = "element_enabled_changed"
    TEXT_CHANGED = "text_changed"
    VALUE_CHANGED = "value_changed"
    DIALOG_OPENED = "dialog_opened"
    BROWSER_NAVIGATION = "browser_navigation"
    DOM_MUTATION = "dom_mutation"
    VISION_CHANGE = "vision_change"


@dataclass(slots=True)
class Bounds:
    left: int
    top: int
    width: int
    height: int


@dataclass(slots=True)
class WindowInfo:
    window_id: int
    title: str
    class_name: str = ""
    bounds: Bounds | None = None
    is_visible: bool = True
    process_id: int = 0


@dataclass(slots=True)
class DetectedElement:
    window_id: int | None
    name: str = ""
    automation_id: str = ""
    control_type: str = ""
    bounds: Bounds | None = None
    confidence: float = 0.0


@dataclass(slots=True)
class TargetRef:
    window_title: str = ""
    automation_id: str = ""
    name: str = ""
    control_type: str = ""
    bounds: Bounds | None = None
    fallback_visual_hint: str = ""


@dataclass(slots=True)
class PointerPoint:
    x: int
    y: int


@dataclass(slots=True)
class PointerStroke:
    path: list[PointerPoint] = field(default_factory=list)
    coordinate_mode: str = "absolute"
    duration_ms: int = 0
    pause_after_ms: int = 0
    button: str = "left"


@dataclass(slots=True)
class ExpectedSignal:
    kind: ExpectedSignalKind
    target: str = ""
    detail: str = ""


@dataclass(slots=True)
class PrimarySensorSnapshot:
    active_window: WindowInfo | None
    focused_element: str
    event_counts: dict[str, int]
    active_automation_backend: str
    fingerprint: str
    has_events: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)


@dataclass(slots=True)
class Action:
    type: ActionType
    target: TargetRef
    purpose: str
    reason: str
    preconditions: list[str]
    expected_outcome: str
    risk_level: RiskLevel = RiskLevel.LOW
    confidence: float = 0.0
    text: str = ""
    hotkey: str = ""
    scroll_amount: int = 0
    drag_coordinate_mode: str = "absolute"
    drag_path: list[PointerPoint] = field(default_factory=list)
    drag_duration_ms: int = 0
    pointer_script: list[PointerStroke] = field(default_factory=list)
    expected_signals: list[ExpectedSignal] = field(default_factory=list)
    wait_timeout_ms: int = 2200


@dataclass(slots=True)
class Observation:
    screenshot_path: str | None
    active_window: WindowInfo | None
    visible_windows: list[WindowInfo]
    detected_elements: list[DetectedElement]
    ui_tree_summary: str
    cursor_position: tuple[int, int]
    focused_element: str
    textual_hints: list[str]
    recent_actions: list[str]
    timestamp: str = field(default_factory=utc_now)
    raw_ref: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlanStep:
    summary: str
    action: Action | None = None
    is_complete: bool = False
    requires_replan: bool = False
    completion_reason: str = ""
    reasoning: str = ""
    plan_outline: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VerificationResult:
    matched: bool
    confidence: float
    reason: str


@dataclass(slots=True)
class ValidationResult:
    success: bool
    confidence: float
    details: str


@dataclass(slots=True)
class ExecutionResult:
    success: bool
    details: str
    error: str = ""


@dataclass(slots=True)
class LearningEntry:
    id: str
    app: str
    scope: str
    observation_pattern: str
    successful_action: str
    expected_outcome: str
    confidence: float
    evidence_count: int
    failure_count: int
    first_seen_at: str
    last_verified_at: str
    invalidation_hint: str
    source_session_id: str
    task_id: str = ""
    stage: str = ""


@dataclass(slots=True)
class KnowledgeSelection:
    kind: str
    path: str
    score: float
    reason: str
    excerpt: str


@dataclass(slots=True)
class RetrievedContext:
    goal: str
    stage: str
    app_candidates: list[str]
    task_candidates: list[str]
    selections: list[KnowledgeSelection]


@dataclass(slots=True)
class SessionMission:
    instruction: str
    user_id: str = "default"
    task_id: str = ""
    trigger: str = "manual"
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class IdleData:
    message: str = "Ready"


@dataclass(slots=True)
class LoadingContextData:
    goal: str
    stage: str


@dataclass(slots=True)
class ObservingData:
    reason: str


@dataclass(slots=True)
class PlanningData:
    goal: str


@dataclass(slots=True)
class PrecheckData:
    action_summary: str


@dataclass(slots=True)
class ExecutingData:
    action_summary: str


@dataclass(slots=True)
class PostcheckData:
    action_summary: str


@dataclass(slots=True)
class ReplanningData:
    failure_reason: str
    attempt: int


@dataclass(slots=True)
class LearningUpdateData:
    entries: int


@dataclass(slots=True)
class PausedData:
    resume_target: SessionState


@dataclass(slots=True)
class StoppedData:
    reason: str


@dataclass(slots=True)
class FailedData:
    reason: str


@dataclass(slots=True)
class CompletedData:
    summary: str


StatePayload = (
    IdleData
    | LoadingContextData
    | ObservingData
    | PlanningData
    | PrecheckData
    | ExecutingData
    | PostcheckData
    | ReplanningData
    | LearningUpdateData
    | PausedData
    | StoppedData
    | FailedData
    | CompletedData
)


@dataclass(slots=True)
class TransitionRecord:
    from_state: SessionState
    to_state: SessionState
    reason: str
    timestamp: str = field(default_factory=utc_now)


@dataclass(slots=True)
class SessionSnapshot:
    session_id: str
    mission: SessionMission
    state: SessionState
    payload: StatePayload
    transitions: list[TransitionRecord] = field(default_factory=list)
    retrieved_context: RetrievedContext | None = None
    current_observation: Observation | None = None
    last_action: Action | None = None
    summary: str = ""


@dataclass(slots=True)
class ProviderSettings:
    provider: str
    base_url: str
    model: str
    reasoning_effort: str
    timeout_seconds: int
    retry_count: int
    max_tokens: int
    allow_images: bool = True
    is_default: bool = False
    service_tier: str = "auto"


@dataclass(slots=True)
class ProviderTestResult:
    ok: bool
    message: str
    checked_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class ScheduledJob:
    task_id: str
    instruction: str
    run_at: str
    recurrence: ScheduleKind
    enabled: bool
    last_result: ScheduledJobState = ScheduledJobState.SCHEDULED
    last_message: str = ""
    last_run_at: str = ""
    weekdays: list[str] = field(default_factory=list)
    interval_minutes: int = 0
    random_runs_per_day: int = 0
    next_run_at: str = ""
    planned_run_times: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
