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


def test_get_archived_source_dirs_is_empty_initially(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.get_archived_source_dirs() == set()


def test_get_archived_source_dirs_returns_all(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.mark_archived("dir1", "2026-02-13T10:00:00", "Meeting", 5000, "a.md", "sha1")
    tracker.mark_archived("dir2", "2026-02-13T11:00:00", "Meeting", 6000, "b.md", "sha2")
    assert tracker.get_archived_source_dirs() == {"dir1", "dir2"}


def test_get_file_paths_is_empty_for_unknown(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.get_file_paths(["nope"]) == set()


def test_get_file_paths_is_empty_for_no_input(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.get_file_paths([]) == set()


def test_get_file_paths_collapses_shared_notes(tmp_path):
    """Grouped recordings share one note, so their paths deduplicate."""
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.mark_archived("dir1", "2026-02-13T10:00:00", "Super", 5000, "2026/02/a.md", "sha1")
    tracker.mark_archived("dir2", "2026-02-13T10:01:00", "Super", 6000, "2026/02/a.md", "sha1")
    tracker.mark_archived("dir3", "2026-02-13T11:00:00", "Super", 6000, "2026/02/b.md", "sha2")
    assert tracker.get_file_paths(["dir1", "dir2"]) == {"2026/02/a.md"}
    assert tracker.get_file_paths(["dir1", "dir3"]) == {"2026/02/a.md", "2026/02/b.md"}


# --- Failure tracking ---------------------------------------------------


def test_no_failures_initially(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.get_failures() == []


def test_record_failure_starts_at_one_attempt(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.record_failure("dir1", "boom")
    failures = tracker.get_failures()
    assert len(failures) == 1
    assert failures[0]["source_dir"] == "dir1"
    assert failures[0]["attempts"] == 1
    assert failures[0]["last_error"] == "boom"


def test_record_failure_increments_and_keeps_first_failed_at(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.record_failure("dir1", "first")
    first_seen = tracker.get_failures()[0]["first_failed_at"]
    tracker.record_failure("dir1", "second")
    failure = tracker.get_failures()[0]
    assert failure["attempts"] == 2
    assert failure["last_error"] == "second"
    assert failure["first_failed_at"] == first_seen


def test_clear_failure_removes_the_row(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.record_failure("dir1", "boom")
    tracker.clear_failure("dir1")
    assert tracker.get_failures() == []


def test_clear_failure_is_safe_when_absent(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.clear_failure("never-seen")
    assert tracker.get_failures() == []


def test_failures_are_ordered_by_first_failure(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.record_failure("older", "boom")
    tracker.record_failure("newer", "boom")
    assert [f["source_dir"] for f in tracker.get_failures()] == ["older", "newer"]
