"""Grouping adjacent recordings into one meeting, and the capture rule over groups."""

from archiver.models import ArchiverConfig, Recording, RecordingGroup
from archiver.scanner import group_recordings, qualifies

BASE = {
    "result": "Hello world",
    "rawResult": " Hello world",
    "segments": [{"text": "Hello world", "start": 1.0, "end": 12.0}],
    "modelName": "Ultra (Cloud)",
    "languageSelected": "en",
    "appVersion": "2.9.0",
}


def _rec(source_dir, datetime, duration, mode="Super"):
    return Recording(
        source_dir=source_dir, datetime=datetime, duration=duration, modeName=mode, **BASE
    )


def _grouping(**overrides):
    defaults = {"gap_seconds": {"meeting": 60, "super": 60}, "default_gap_seconds": 60}
    defaults.update(overrides)
    return ArchiverConfig.GroupingConfig(**defaults)


def _filters(**overrides):
    defaults = {
        "modes": ["meeting"],
        "min_duration_ms": 60000,
        "long_recording_modes": ["super"],
        "long_recording_min_duration_ms": 300000,
    }
    defaults.update(overrides)
    return ArchiverConfig.FiltersConfig(**defaults)


# --- Gap arithmetic -----------------------------------------------------


def test_single_recording_becomes_a_group_of_one():
    groups = group_recordings([_rec("a", "2026-08-17T09:30:00", 10000)], _grouping())
    assert len(groups) == 1
    assert groups[0].source_dirs == ["a"]


def test_no_recordings_produces_no_groups():
    assert group_recordings([], _grouping()) == []


def test_recordings_within_the_gap_merge():
    # a ends at 09:30:10; b starts 10s later.
    recs = [_rec("a", "2026-08-17T09:30:00", 10000), _rec("b", "2026-08-17T09:30:20", 10000)]
    groups = group_recordings(recs, _grouping())
    assert len(groups) == 1
    assert groups[0].source_dirs == ["a", "b"]


def test_recordings_beyond_the_gap_stay_separate():
    # a ends at 09:30:10; b starts 5 minutes later, well past the 60s super gap.
    recs = [_rec("a", "2026-08-17T09:30:00", 10000), _rec("b", "2026-08-17T09:35:00", 10000)]
    groups = group_recordings(recs, _grouping())
    assert [g.source_dirs for g in groups] == [["a"], ["b"]]


def test_gap_is_measured_from_the_end_of_the_previous_recording():
    """A long recording followed closely still merges, despite a distant start."""
    recs = [_rec("a", "2026-08-17T09:30:00", 600000), _rec("b", "2026-08-17T09:40:30", 10000)]
    groups = group_recordings(recs, _grouping())
    assert len(groups) == 1


def test_gap_exactly_at_the_threshold_merges():
    recs = [_rec("a", "2026-08-17T09:30:00", 10000), _rec("b", "2026-08-17T09:31:10", 10000)]
    assert len(group_recordings(recs, _grouping())) == 1


def test_gap_just_past_the_threshold_splits():
    recs = [_rec("a", "2026-08-17T09:30:00", 10000), _rec("b", "2026-08-17T09:31:11", 10000)]
    assert len(group_recordings(recs, _grouping())) == 2


def test_recordings_are_grouped_in_time_order_regardless_of_input_order():
    recs = [_rec("b", "2026-08-17T09:30:20", 10000), _rec("a", "2026-08-17T09:30:00", 10000)]
    groups = group_recordings(recs, _grouping())
    assert groups[0].source_dirs == ["a", "b"]


# --- Modes are grouped independently ------------------------------------


def test_different_modes_never_merge():
    recs = [
        _rec("a", "2026-08-17T09:30:00", 10000, mode="Super"),
        _rec("b", "2026-08-17T09:30:20", 10000, mode="Meeting"),
    ]
    groups = group_recordings(recs, _grouping())
    assert [g.source_dirs for g in groups] == [["b"], ["a"]] or [g.source_dirs for g in groups] == [
        ["a"],
        ["b"],
    ]
    assert all(len(g.recordings) == 1 for g in groups)


def test_each_mode_uses_its_own_gap():
    """A mode with a wider gap merges what a tighter one splits."""
    grouping = _grouping(gap_seconds={"meeting": 1200, "super": 60})
    recs = lambda mode: [  # noqa: E731
        _rec("a", "2026-08-17T09:00:00", 10000, mode=mode),
        _rec("b", "2026-08-17T09:15:00", 10000, mode=mode),
    ]
    assert len(group_recordings(recs("Meeting"), grouping)) == 1
    assert len(group_recordings(recs("Super"), grouping)) == 2


def test_back_to_back_meetings_do_not_merge():
    """Regression: two distinct calls nine minutes apart must stay separate.

    One call signed off at 10:21 and an entirely different one — different
    person, fresh greeting — began at 10:30. A generous meeting gap merged
    them into a single note. Real restarts within one call are seconds apart,
    so nothing is lost by keeping the gap tight.
    """
    recs = [
        _rec("1786961712", "2026-08-17T10:15:12", 350000, mode="Meeting"),
        _rec("1786962624", "2026-08-17T10:30:24", 1082000, mode="Meeting"),
    ]
    groups = group_recordings(recs, _grouping())
    assert [g.source_dirs for g in groups] == [["1786961712"], ["1786962624"]]


def test_a_meeting_restarted_within_seconds_does_merge():
    """The case a meeting gap must still catch: stop and immediately resume."""
    recs = [
        _rec("1771248100", "2026-02-16T13:21:40", 320, mode="Meeting"),
        _rec("1771248104", "2026-02-16T13:21:44", 299, mode="Meeting"),
        _rec("1771248110", "2026-02-16T13:21:50", 149, mode="Meeting"),
    ]
    assert len(group_recordings(recs, _grouping())) == 1


def test_unknown_mode_falls_back_to_the_default_gap():
    recs = [
        _rec("a", "2026-08-17T09:00:00", 10000, mode="Custom"),
        _rec("b", "2026-08-17T09:00:30", 10000, mode="Custom"),
    ]
    assert len(group_recordings(recs, _grouping())) == 1


# --- Group properties ---------------------------------------------------


def test_group_duration_is_the_sum():
    g = RecordingGroup(
        recordings=[
            _rec("a", "2026-08-17T09:30:00", 21000),
            _rec("b", "2026-08-17T09:31:00", 81000),
        ]
    )
    assert g.duration == 102000


def test_group_datetime_is_the_earliest():
    g = RecordingGroup(
        recordings=[
            _rec("a", "2026-08-17T09:30:00", 21000),
            _rec("b", "2026-08-17T09:31:00", 81000),
        ]
    )
    assert g.datetime == "2026-08-17T09:30:00"
    assert g.modeName == "Super"


# --- Capture rule applies to the group ----------------------------------


def test_short_recordings_qualify_once_grouped():
    """The bug this fixes: a call split into chunks that each miss the floor.

    Three Super recordings of 21s, 81s and 655s are one 12m39s conversation;
    individually only the last clears the 5-minute long-recording floor.
    """
    recs = [
        _rec("a", "2026-08-17T09:30:44", 1000),
        _rec("b", "2026-08-17T09:31:21", 21000),
        _rec("c", "2026-08-17T09:31:52", 81000),
        _rec("d", "2026-08-17T09:33:23", 655000),
    ]
    groups = group_recordings(recs, _grouping())
    assert len(groups) == 1
    assert qualifies(groups[0], _filters()) is True
    assert groups[0].source_dirs == ["a", "b", "c", "d"]


def test_a_burst_of_dictation_still_does_not_qualify():
    """Many adjacent snippets that add up to little must stay out of the archive."""
    recs = [_rec(str(i), f"2026-08-17T09:{30 + i:02d}:00", 3000) for i in range(20)]
    groups = group_recordings(recs, _grouping())
    assert all(qualifies(g, _filters()) is False for g in groups)


def test_meeting_group_over_floor_qualifies():
    g = RecordingGroup(recordings=[_rec("a", "2026-08-17T09:30:00", 90000, mode="Meeting")])
    assert qualifies(g, _filters()) is True


def test_meeting_group_under_floor_does_not_qualify():
    g = RecordingGroup(recordings=[_rec("a", "2026-08-17T09:30:00", 320, mode="Meeting")])
    assert qualifies(g, _filters()) is False


def test_unrelated_mode_never_qualifies():
    g = RecordingGroup(recordings=[_rec("a", "2026-08-17T09:30:00", 999999, mode="Default")])
    assert qualifies(g, _filters()) is False


def test_mode_matching_is_case_insensitive():
    g = RecordingGroup(recordings=[_rec("a", "2026-08-17T09:30:00", 90000, mode="MEETING")])
    assert qualifies(g, _filters()) is True
