"""Decide whether to start or stop a Meeting-mode recording.

`reconcile` is deliberately a pure function of (state, mic_holders, now). The
microphone holder list answers two questions at once — whether a call is
happening (`desired`), and whether superwhisper is actually recording it
(`actual`) — which makes this a closed loop rather than fire-and-forget. Every
action is verified on a later tick, so a trigger that has silently stopped
working is detectable rather than a six-day outage.

Both verifications matter for a different reason on 2.17.3: STOP is a synthetic
hotkey press, and toggling is blind. It starts if stopped and stops if started,
so the reconciler must read the microphone either side rather than trust it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Mapping

SUPERWHISPER = "com.superduper.superwhisper"


class Action(Enum):
    NOTHING = "nothing"
    START = "start"
    STOP = "stop"


class Phase(Enum):
    IDLE = "idle"
    #: START sent, waiting for superwhisper to take the microphone.
    STARTING = "starting"
    RECORDING = "recording"
    #: The call is gone but the recording is held open, in case it comes back.
    GRACE = "grace"
    #: STOP sent, waiting for superwhisper to release the microphone.
    STOPPING = "stopping"


@dataclass(frozen=True)
class TriggerPolicy:
    #: Bundle IDs whose use of the microphone means a call is happening.
    call_apps: frozenset[str]
    #: How long a recording is held open after the call apps release the mic.
    #: Costs trailing silence; buys not splitting one meeting into two files.
    exit_grace: timedelta = timedelta(seconds=60)
    #: A missed stop must never record forever. Two real recordings have
    #: already run to 4h17m and 2h53m.
    hard_cap: timedelta = timedelta(hours=3)
    start_retries: int = 3
    stop_retries: int = 3


@dataclass(frozen=True)
class WatchState:
    phase: Phase = Phase.IDLE
    #: When the current phase began. Only the grace countdown reads it.
    since: datetime | None = None
    recording_started_at: datetime | None = None
    start_attempts: int = 0
    stop_attempts: int = 0
    #: The user stopped a recording by hand mid-call. Do not restart it, or one
    #: meeting becomes two fragment files.
    override_latched: bool = False

    def to_row(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "since": _to_text(self.since),
            "recording_started_at": _to_text(self.recording_started_at),
            "start_attempts": self.start_attempts,
            "stop_attempts": self.stop_attempts,
            "override_latched": int(self.override_latched),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> WatchState:
        """Rebuild after a restart. A missing row is a cold start, not an error."""
        if not row:
            return cls()
        return cls(
            phase=Phase(row["phase"]),
            since=_from_text(row["since"]),
            recording_started_at=_from_text(row["recording_started_at"]),
            start_attempts=row["start_attempts"],
            stop_attempts=row["stop_attempts"],
            override_latched=bool(row["override_latched"]),
        )


@dataclass(frozen=True)
class Decision:
    action: Action
    state: WatchState
    alert: str | None = None


def _to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _from_text(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _begin_stop(state: WatchState, now: datetime) -> Decision:
    return Decision(
        Action.STOP,
        replace(state, phase=Phase.STOPPING, since=now, stop_attempts=1),
    )


def _capped(state: WatchState, now: datetime, policy: TriggerPolicy) -> bool:
    started = state.recording_started_at
    return started is not None and now - started >= policy.hard_cap


def reconcile(
    state: WatchState,
    mic_holders: frozenset[str],
    now: datetime,
    policy: TriggerPolicy,
) -> Decision:
    """One tick. Returns the action to take and the state to persist."""
    desired = bool(policy.call_apps & mic_holders)
    actual = SUPERWHISPER in mic_holders

    if state.phase is Phase.IDLE:
        if not desired:
            # The call is over, so a hand-stop no longer needs suppressing.
            return Decision(Action.NOTHING, replace(state, override_latched=False))
        if state.override_latched:
            return Decision(Action.NOTHING, state)
        return Decision(
            Action.START,
            replace(state, phase=Phase.STARTING, since=now, start_attempts=1),
        )

    if state.phase is Phase.STARTING:
        if actual:
            return Decision(
                Action.NOTHING,
                replace(state, phase=Phase.RECORDING, since=now, recording_started_at=now),
            )
        if state.start_attempts >= policy.start_retries:
            return Decision(
                Action.NOTHING,
                WatchState(),
                alert=(
                    f"start was sent {state.start_attempts} times and superwhisper never "
                    "took the microphone — Accessibility may have been revoked"
                ),
            )
        return Decision(Action.START, replace(state, start_attempts=state.start_attempts + 1))

    if state.phase in (Phase.RECORDING, Phase.GRACE):
        if not actual:
            # We were recording and now we are not, without having sent a stop.
            return Decision(
                Action.NOTHING,
                WatchState(override_latched=desired),
            )
        if _capped(state, now, policy):
            return _begin_stop(state, now)
        if desired:
            if state.phase is Phase.GRACE:
                # The call came back inside the grace period: same recording.
                return Decision(Action.NOTHING, replace(state, phase=Phase.RECORDING, since=now))
            return Decision(Action.NOTHING, state)
        if state.phase is Phase.RECORDING:
            return Decision(Action.NOTHING, replace(state, phase=Phase.GRACE, since=now))
        if state.since is not None and now - state.since >= policy.exit_grace:
            return _begin_stop(state, now)
        return Decision(Action.NOTHING, state)

    if state.phase is Phase.STOPPING:
        if not actual:
            return Decision(Action.NOTHING, WatchState())
        if state.stop_attempts >= policy.stop_retries:
            return Decision(
                Action.NOTHING,
                state,
                alert=(
                    f"stop was sent {state.stop_attempts} times and superwhisper is still "
                    "holding the microphone — it may be recording indefinitely"
                ),
            )
        return Decision(Action.STOP, replace(state, stop_attempts=state.stop_attempts + 1))

    raise AssertionError(f"unhandled phase: {state.phase}")
