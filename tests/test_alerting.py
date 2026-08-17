"""Alerting when recordings fail to archive across multiple runs."""

from archiver.main import (
    ALERT_ATTEMPT_THRESHOLD,
    maybe_alert_failures,
    record_archive_outcome,
    recordings_needing_alert,
)
from archiver.models import ArchiveResult
from archiver.state_tracker import StateTracker


def _tracker(tmp_path):
    return StateTracker(str(tmp_path / "test.db"))


def _failure(source_dir="dir1", attempts=1, last_error="boom"):
    return {
        "source_dir": source_dir,
        "attempts": attempts,
        "first_failed_at": "2026-02-13T10:00:00",
        "last_error": last_error,
    }


# --- Pure filter --------------------------------------------------------


def test_no_failures_needs_no_alert():
    assert recordings_needing_alert([]) == []


def test_below_threshold_does_not_alert():
    rows = [_failure(attempts=ALERT_ATTEMPT_THRESHOLD - 1)]
    assert recordings_needing_alert(rows) == []


def test_at_threshold_alerts():
    rows = [_failure(attempts=ALERT_ATTEMPT_THRESHOLD)]
    assert len(recordings_needing_alert(rows)) == 1


def test_only_offenders_are_returned():
    rows = [_failure("ok", attempts=1), _failure("bad", attempts=5)]
    assert [r["source_dir"] for r in recordings_needing_alert(rows)] == ["bad"]


# --- Outcome recording --------------------------------------------------


def test_failure_is_recorded(tmp_path):
    tracker = _tracker(tmp_path)
    result = ArchiveResult(success=False, source_dir="dir1", error="disk full")
    record_archive_outcome(tracker, "dir1", result)
    failures = tracker.get_failures()
    assert len(failures) == 1
    assert failures[0]["attempts"] == 1
    assert failures[0]["last_error"] == "disk full"


def test_repeated_failures_increment_attempts(tmp_path):
    tracker = _tracker(tmp_path)
    for _ in range(3):
        record_archive_outcome(
            tracker, "dir1", ArchiveResult(success=False, source_dir="dir1", error="boom")
        )
    assert tracker.get_failures()[0]["attempts"] == 3


def test_success_clears_the_failure(tmp_path):
    tracker = _tracker(tmp_path)
    record_archive_outcome(
        tracker, "dir1", ArchiveResult(success=False, source_dir="dir1", error="boom")
    )
    record_archive_outcome(tracker, "dir1", ArchiveResult(success=True, source_dir="dir1"))
    assert tracker.get_failures() == []


def test_dry_run_never_mutates_state(tmp_path):
    tracker = _tracker(tmp_path)
    record_archive_outcome(
        tracker,
        "dir1",
        ArchiveResult(success=False, source_dir="dir1", error="boom"),
        dry_run=True,
    )
    assert tracker.get_failures() == []


# --- Notification -------------------------------------------------------


def test_alert_fires_once_threshold_reached(tmp_path):
    tracker = _tracker(tmp_path)
    sent = []
    for _ in range(ALERT_ATTEMPT_THRESHOLD):
        record_archive_outcome(
            tracker, "dir1", ArchiveResult(success=False, source_dir="dir1", error="boom")
        )

    alerting = maybe_alert_failures(tracker, notifier=lambda t, m: sent.append((t, m)))

    assert len(alerting) == 1
    assert len(sent) == 1
    assert "dir1" in sent[0][1]
    assert "boom" in sent[0][1]


def test_no_alert_when_nothing_is_failing(tmp_path):
    sent = []
    alerting = maybe_alert_failures(_tracker(tmp_path), notifier=lambda t, m: sent.append((t, m)))
    assert alerting == []
    assert sent == []


def test_no_alert_below_threshold(tmp_path):
    tracker = _tracker(tmp_path)
    sent = []
    record_archive_outcome(
        tracker, "dir1", ArchiveResult(success=False, source_dir="dir1", error="boom")
    )
    maybe_alert_failures(tracker, notifier=lambda t, m: sent.append((t, m)))
    assert sent == []
