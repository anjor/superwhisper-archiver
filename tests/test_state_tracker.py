from archiver.state_tracker import StateTracker


def test_is_archived_returns_false_for_unknown(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.is_archived("unknown_dir") is False


def test_mark_and_check_archived(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.mark_archived(
        source_dir="1770978710",
        recording_datetime="2026-02-13T10:31:50",
        mode="Meeting",
        duration_ms=13647,
        file_path="2026/02/2026-02-13-10-31-50.md",
        commit_sha="abc123",
    )
    assert tracker.is_archived("1770978710") is True


def test_get_archived_count(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.get_archived_count() == 0
    tracker.mark_archived("dir1", "2026-02-13T10:00:00", "Meeting", 5000, "a.md", "sha1")
    tracker.mark_archived("dir2", "2026-02-13T11:00:00", "Meeting", 6000, "b.md", "sha2")
    assert tracker.get_archived_count() == 2


def test_update_and_get_last_run(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.get_last_run_timestamp() is None
    tracker.update_last_run(
        recordings_processed=5,
        recordings_archived=3,
        recordings_failed=1,
    )
    ts = tracker.get_last_run_timestamp()
    assert ts is not None


def test_mark_archived_is_idempotent(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.mark_archived("dir1", "2026-02-13T10:00:00", "Meeting", 5000, "a.md", "sha1")
    tracker.mark_archived("dir1", "2026-02-13T10:00:00", "Meeting", 5000, "a.md", "sha2")
    assert tracker.get_archived_count() == 1
