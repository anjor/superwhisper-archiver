import json
from pathlib import Path

from archiver.models import Recording
from archiver.scanner import Scanner, is_complete


def _create_recording(tmp_path: Path, dir_name: str, meta: dict):
    """Helper to create a fake recording directory."""
    rec_dir = tmp_path / dir_name
    rec_dir.mkdir()
    (rec_dir / "meta.json").write_text(json.dumps(meta))


MEETING_META = {
    "datetime": "2026-02-13T10:31:50",
    "result": "Hello world",
    "rawResult": " Hello world",
    "duration": 13647,
    "segments": [{"text": "Hello world", "start": 1.0, "end": 12.0}],
    "modeName": "Meeting",
    "modelName": "Ultra (Cloud)",
    "languageSelected": "en",
    "systemAudioEnabled": True,
    "appVersion": "2.9.0",
}

DEFAULT_META = {
    **MEETING_META,
    "modeName": "Default",
    "datetime": "2026-02-14T09:00:00",
}

# What superwhisper writes ~11s into a recording, before it finalises meta.json.
IN_PROGRESS_META = {
    **MEETING_META,
    "datetime": "2026-02-20T14:00:00",
    "result": "",
    "rawResult": "",
    "duration": 0,
    "segments": [],
}


def _recording(**overrides):
    meta = {**MEETING_META, **overrides}
    return Recording(source_dir="test", **meta)


# --- Scanning -----------------------------------------------------------


def test_scan_finds_recordings(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", DEFAULT_META)
    result = Scanner(str(tmp_path)).scan()
    assert len(result.recordings) == 2


def test_scan_skips_invalid_directories(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    (tmp_path / "invalid_dir").mkdir()
    (tmp_path / "random_file.txt").write_text("hello")
    result = Scanner(str(tmp_path)).scan()
    assert len(result.recordings) == 1


def test_scan_returns_sorted_by_datetime(tmp_path):
    early = {**MEETING_META, "datetime": "2026-02-10T08:00:00"}
    late = {**MEETING_META, "datetime": "2026-02-15T18:00:00"}
    _create_recording(tmp_path, "1770978720", late)
    _create_recording(tmp_path, "1770978710", early)
    result = Scanner(str(tmp_path)).scan()
    assert [r.datetime for r in result.recordings] == [
        "2026-02-10T08:00:00",
        "2026-02-15T18:00:00",
    ]


def test_scan_missing_path_returns_empty(tmp_path):
    result = Scanner(str(tmp_path / "nope")).scan()
    assert result.recordings == []


# --- Completeness gate --------------------------------------------------


def test_in_progress_recording_is_not_complete():
    assert is_complete(_recording(**IN_PROGRESS_META)) is False


def test_finished_recording_is_complete():
    assert is_complete(_recording()) is True


def test_recording_with_only_segments_is_complete():
    assert is_complete(_recording(result="", rawResult="")) is True


def test_zero_duration_is_never_complete():
    assert is_complete(_recording(duration=0)) is False


def test_whitespace_only_transcript_without_segments_is_not_complete():
    assert is_complete(_recording(result="  ", rawResult="\n", segments=[])) is False


def test_scan_skips_in_progress_recordings(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1780000000", IN_PROGRESS_META)
    result = Scanner(str(tmp_path)).scan()
    assert [r.source_dir for r in result.recordings] == ["1770978710"]
    assert result.skipped_incomplete == 1


def test_in_progress_recording_is_picked_up_once_finalised(tmp_path):
    """The placeholder is skipped, then archived on a later run once rewritten.

    This is the behaviour the `since` watermark used to make impossible.
    """
    _create_recording(tmp_path, "1780000000", IN_PROGRESS_META)
    scanner = Scanner(str(tmp_path))
    assert scanner.scan().recordings == []

    # superwhisper rewrites meta.json in place when the recording finishes.
    finalised = {**IN_PROGRESS_META, "duration": 1689000, "result": "the real transcript"}
    (tmp_path / "1780000000" / "meta.json").write_text(json.dumps(finalised))

    result = scanner.scan()
    assert [r.source_dir for r in result.recordings] == ["1780000000"]


def test_placeholder_meta_parses_instead_of_raising(tmp_path):
    """A partial meta.json must not blow up Pydantic validation."""
    _create_recording(tmp_path, "1780000000", {"datetime": "2026-02-20T14:00:00"})
    result = Scanner(str(tmp_path)).scan()
    assert result.recordings == []
    assert result.skipped_incomplete == 1
    assert result.failed_to_parse == 0


def test_unparseable_meta_is_counted_not_raised(tmp_path):
    rec_dir = tmp_path / "1780000000"
    rec_dir.mkdir()
    (rec_dir / "meta.json").write_text("{not json")
    result = Scanner(str(tmp_path)).scan()
    assert result.recordings == []
    assert result.failed_to_parse == 1


# The capture rule now applies to groups rather than single recordings;
# see tests/test_grouping.py.


# --- No watermark -------------------------------------------------------


def test_scan_returns_archived_recordings_too(tmp_path):
    """Dedup is per group, not per recording, so scanning must not pre-filter.

    Grouping needs to see archived recordings; otherwise a recording finishing
    next to an archived one would start a second note instead of joining it.
    """
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", {**MEETING_META, "datetime": "2026-02-14T10:00:00"})
    result = Scanner(str(tmp_path)).scan()
    assert sorted(r.source_dir for r in result.recordings) == ["1770978710", "1770978720"]


def test_old_unarchived_recording_is_still_returned(tmp_path):
    """Regression: the `since` watermark permanently dropped recordings it missed.

    Two of the longest February meetings were lost this way. A recording that
    predates every previous run must still be offered for archiving.
    """
    ancient = {**MEETING_META, "datetime": "2020-01-01T00:00:00", "duration": 4620000}
    _create_recording(tmp_path, "1771419794", ancient)
    result = Scanner(str(tmp_path)).scan()
    assert [r.source_dir for r in result.recordings] == ["1771419794"]


def test_since_is_available_as_an_explicit_filter(tmp_path):
    old_meta = {**MEETING_META, "datetime": "2026-02-01T10:00:00"}
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", old_meta)
    result = Scanner(str(tmp_path)).scan(since="2026-02-10")
    assert [r.source_dir for r in result.recordings] == ["1770978710"]
