"""The auto-capture reconciler.

`reconcile` is a pure function of (state, mic_holders, now), which is the whole
point of its design: the trigger logic is testable without audio, meetings, or
waiting out a single grace period.
"""

from datetime import datetime, timedelta

import pytest

from archiver.reconciler import Action, Phase, TriggerPolicy, WatchState, reconcile

SUPERWHISPER = "com.superduper.superwhisper"
ZOOM = "us.zoom.xos"
SLACK = "com.tinyspeck.slackmacgap"

T0 = datetime(2026, 9, 1, 10, 0, 0)

POLICY = TriggerPolicy(call_apps=frozenset({ZOOM, SLACK}))


def step(state, holders, now):
    return reconcile(state, frozenset(holders), now, POLICY)


class TestStarting:
    def test_a_call_starting_starts_a_recording(self):
        decision = step(WatchState(), {ZOOM}, T0)

        assert decision.action is Action.START
        assert decision.state.phase is Phase.STARTING

    def test_no_call_and_no_recording_does_nothing(self):
        decision = step(WatchState(), set(), T0)

        assert decision.action is Action.NOTHING
        assert decision.state.phase is Phase.IDLE

    def test_superwhisper_alone_is_dictation_not_a_call(self):
        """Plain dictation holds the mic without any call app. Leave it alone."""
        decision = step(WatchState(), {SUPERWHISPER}, T0)

        assert decision.action is Action.NOTHING
        assert decision.state.phase is Phase.IDLE

    def test_start_is_confirmed_when_superwhisper_takes_the_mic(self):
        started = step(WatchState(), {ZOOM}, T0).state

        decision = step(started, {ZOOM, SUPERWHISPER}, T0 + timedelta(seconds=10))

        assert decision.action is Action.NOTHING
        assert decision.state.phase is Phase.RECORDING
        assert decision.state.recording_started_at == T0 + timedelta(seconds=10)


class TestStartVerification:
    def test_an_unconfirmed_start_is_retried(self):
        state = step(WatchState(), {ZOOM}, T0).state

        decision = step(state, {ZOOM}, T0 + timedelta(seconds=10))

        assert decision.action is Action.START
        assert decision.state.phase is Phase.STARTING
        assert decision.state.start_attempts == 2

    def test_a_start_that_never_lands_alerts_and_gives_up(self):
        """The silent no-op is the failure to avoid: six days of it cost Granola."""
        state = WatchState()
        now = T0
        for _ in range(POLICY.start_retries):
            decision = step(state, {ZOOM}, now)
            assert decision.action is Action.START
            state, now = decision.state, now + timedelta(seconds=10)

        decision = step(state, {ZOOM}, now)

        assert decision.action is Action.NOTHING
        assert decision.alert is not None
        assert "start" in decision.alert.lower()


def recording_state(now=T0):
    """A confirmed in-progress recording, reached the way the daemon reaches it."""
    state = step(WatchState(), {ZOOM}, now).state
    return step(state, {ZOOM, SUPERWHISPER}, now).state


class TestStopping:
    def test_a_call_ending_does_not_stop_immediately(self):
        """Exit needs a grace period, or a blip mid-call splits one meeting in two."""
        state = recording_state()

        decision = step(state, {SUPERWHISPER}, T0 + timedelta(seconds=10))

        assert decision.action is Action.NOTHING
        assert decision.state.phase is Phase.GRACE

    def test_the_grace_period_expiring_stops_the_recording(self):
        state = step(recording_state(), {SUPERWHISPER}, T0 + timedelta(seconds=10)).state

        decision = step(state, {SUPERWHISPER}, T0 + timedelta(seconds=10) + POLICY.exit_grace)

        assert decision.action is Action.STOP
        assert decision.state.phase is Phase.STOPPING

    def test_a_call_reappearing_inside_the_grace_period_keeps_one_recording(self):
        """A mic blip or an app restart must not produce two fragment files."""
        state = step(recording_state(), {SUPERWHISPER}, T0 + timedelta(seconds=10)).state

        decision = step(state, {ZOOM, SUPERWHISPER}, T0 + timedelta(seconds=30))

        assert decision.action is Action.NOTHING
        assert decision.state.phase is Phase.RECORDING
        assert decision.state.recording_started_at == T0

    def test_stop_is_confirmed_when_superwhisper_releases_the_mic(self):
        state = step(recording_state(), {SUPERWHISPER}, T0 + timedelta(seconds=10)).state
        stopping = step(state, {SUPERWHISPER}, T0 + timedelta(minutes=2)).state

        decision = step(stopping, set(), T0 + timedelta(minutes=2, seconds=10))

        assert decision.action is Action.NOTHING
        assert decision.state == WatchState()

    def test_an_unconfirmed_stop_is_retried_then_alerts(self):
        """superwhisper://stop is a no-op on 2.17.3, so a stop that does not land
        is the expected failure, not a remote one."""
        state = step(recording_state(), {SUPERWHISPER}, T0 + timedelta(seconds=10)).state
        now = T0 + timedelta(minutes=2)
        decision = step(state, {SUPERWHISPER}, now)
        assert decision.action is Action.STOP

        for _ in range(POLICY.stop_retries - 1):
            now += timedelta(seconds=10)
            decision = step(decision.state, {SUPERWHISPER}, now)
            assert decision.action is Action.STOP

        decision = step(decision.state, {SUPERWHISPER}, now + timedelta(seconds=10))

        assert decision.alert is not None
        assert "stop" in decision.alert.lower()


class TestHardCap:
    def test_the_hard_cap_stops_a_recording_that_outlasts_any_meeting(self):
        """A missed stop must never record forever — it already has, twice."""
        state = recording_state()

        decision = step(state, {ZOOM, SUPERWHISPER}, T0 + POLICY.hard_cap)

        assert decision.action is Action.STOP
        assert decision.state.phase is Phase.STOPPING

    def test_a_recording_inside_the_hard_cap_is_left_alone(self):
        state = recording_state()

        decision = step(state, {ZOOM, SUPERWHISPER}, T0 + POLICY.hard_cap - timedelta(seconds=1))

        assert decision.action is Action.NOTHING
        assert decision.state.phase is Phase.RECORDING


class TestUserOverride:
    def test_stopping_by_hand_mid_call_is_not_undone(self):
        """If the daemon restarted here, one meeting would become two files."""
        state = recording_state()

        dropped = step(state, {ZOOM}, T0 + timedelta(seconds=10))

        assert dropped.action is Action.NOTHING
        assert dropped.state.override_latched

        decision = step(dropped.state, {ZOOM}, T0 + timedelta(seconds=20))

        assert decision.action is Action.NOTHING

    def test_the_override_clears_when_the_call_ends(self):
        state = recording_state()
        dropped = step(state, {ZOOM}, T0 + timedelta(seconds=10)).state

        cleared = step(dropped, set(), T0 + timedelta(minutes=5)).state

        assert not cleared.override_latched
        assert step(cleared, {ZOOM}, T0 + timedelta(minutes=6)).action is Action.START


class TestPersistence:
    def test_state_survives_a_daemon_restart_mid_recording(self):
        """KeepAlive restarts the daemon; an in-flight recording must not be lost."""
        state = recording_state()

        restored = WatchState.from_row(state.to_row())

        assert restored == state
        assert step(restored, {ZOOM, SUPERWHISPER}, T0 + timedelta(seconds=10)).action is Action.NOTHING

    @pytest.mark.parametrize("state", [WatchState(), None])
    def test_a_missing_or_empty_row_restores_to_idle(self, state):
        row = state.to_row() if state else None

        assert WatchState.from_row(row) == WatchState()
