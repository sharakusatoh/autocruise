from __future__ import annotations

from dataclasses import replace

from autocruise.domain.models import (
    IdleData,
    SessionMission,
    SessionSnapshot,
    SessionState,
    StatePayload,
    TransitionRecord,
)


class InvalidStateTransition(RuntimeError):
    """Raised when the session attempts an invalid state transition."""


ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.IDLE: {SessionState.LOADING_CONTEXT},
    SessionState.LOADING_CONTEXT: {
        SessionState.OBSERVING,
        SessionState.FAILED,
        SessionState.STOPPED,
    },
    SessionState.OBSERVING: {
        SessionState.PLANNING,
        SessionState.REPLANNING,
        SessionState.PAUSED,
        SessionState.STOPPED,
        SessionState.FAILED,
    },
    SessionState.PLANNING: {
        SessionState.PRECHECK,
        SessionState.REPLANNING,
        SessionState.COMPLETED,
        SessionState.PAUSED,
        SessionState.STOPPED,
        SessionState.FAILED,
    },
    SessionState.PRECHECK: {
        SessionState.EXECUTING,
        SessionState.REPLANNING,
        SessionState.PAUSED,
        SessionState.STOPPED,
        SessionState.FAILED,
    },
    SessionState.EXECUTING: {
        SessionState.POSTCHECK,
        SessionState.REPLANNING,
        SessionState.PAUSED,
        SessionState.STOPPED,
        SessionState.FAILED,
    },
    SessionState.POSTCHECK: {
        SessionState.OBSERVING,
        SessionState.REPLANNING,
        SessionState.COMPLETED,
        SessionState.PAUSED,
        SessionState.STOPPED,
        SessionState.FAILED,
    },
    SessionState.REPLANNING: {
        SessionState.OBSERVING,
        SessionState.STOPPED,
        SessionState.FAILED,
    },
    SessionState.PAUSED: {
        SessionState.OBSERVING,
        SessionState.PRECHECK,
        SessionState.EXECUTING,
        SessionState.STOPPED,
        SessionState.FAILED,
    },
    SessionState.STOPPED: set(),
    SessionState.FAILED: set(),
    SessionState.COMPLETED: set(),
}


class SessionStateMachine:
    def create(self, session_id: str, mission: SessionMission) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=session_id,
            mission=mission,
            state=SessionState.IDLE,
            payload=IdleData(),
        )

    def transition(
        self,
        snapshot: SessionSnapshot,
        new_state: SessionState,
        payload: StatePayload,
        reason: str,
    ) -> SessionSnapshot:
        allowed = ALLOWED_TRANSITIONS.get(snapshot.state, set())
        if new_state not in allowed:
            raise InvalidStateTransition(
                f"Cannot transition from {snapshot.state.value} to {new_state.value}: {reason}"
            )

        record = TransitionRecord(
            from_state=snapshot.state,
            to_state=new_state,
            reason=reason,
        )
        transitions = [*snapshot.transitions, record]
        return replace(snapshot, state=new_state, payload=payload, transitions=transitions)
