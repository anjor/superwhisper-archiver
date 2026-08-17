from archiver.markdown_formatter import MarkdownFormatter
from archiver.models import Recording, RecordingGroup


def _make_recording(**overrides) -> Recording:
    defaults = {
        "source_dir": "1770978710",
        "datetime": "2026-02-13T10:31:50",
        "result": "Hello world. How are you?",
        "rawResult": " Hello world. How are you?",
        "duration": 13647,
        "segments": [
            {"text": "Hello world.", "start": 1.696, "end": 5.0},
            {"text": "How are you?", "start": 5.5, "end": 12.864},
        ],
        "modeName": "Meeting",
        "modelName": "Ultra (Cloud)",
        "languageModelName": "GPT-5 mini",
        "languageSelected": "en",
        "systemAudioEnabled": True,
        "appVersion": "2.9.0",
    }
    defaults.update(overrides)
    return Recording(**defaults)


def _group(*recordings) -> RecordingGroup:
    return RecordingGroup(recordings=list(recordings) or [_make_recording()])


def _format(*recordings) -> str:
    return MarkdownFormatter().format_group(_group(*recordings))


# --- Single-recording groups (the common case) --------------------------


def test_format_contains_frontmatter():
    md = _format()
    assert md.startswith("---\n")
    assert "datetime: " in md
    assert "mode: Meeting" in md


def test_single_recording_keeps_the_singular_source_key():
    """Notes for one recording stay byte-comparable with the old format."""
    md = _format()
    assert 'source_dir: "1770978710"' in md
    assert "source_dirs:" not in md
    assert "recording_count:" not in md


def test_format_contains_transcription():
    md = _format()
    assert "## Transcription" in md
    assert "Hello world. How are you?" in md


def test_format_contains_segments():
    md = _format()
    assert "## Segments" in md
    assert "Hello world." in md
    assert "How are you?" in md


def test_format_contains_duration():
    md = _format(_make_recording(duration=90000))
    assert "1m 30s" in md


def test_format_with_llm_result():
    md = _format(_make_recording(llmResult="Summary: a greeting was exchanged."))
    assert "## Summary" in md
    assert "a greeting was exchanged" in md


def test_format_without_llm_result():
    assert "## Summary" not in _format()


def test_format_duration_hours():
    assert "1h 2m 3s" in _format(_make_recording(duration=3723000))


def test_format_segments_timestamps():
    md = _format(_make_recording(segments=[{"text": "Hello", "start": 65.5, "end": 70.2}]))
    assert "01:05.5" in md
    assert "01:10.2" in md


def test_compute_file_path():
    path = MarkdownFormatter().compute_file_path(_group())
    assert path == "2026/02/2026-02-13-10-31-50.md"


def test_compute_file_path_different_date():
    group = _group(_make_recording(datetime="2026-01-05T23:59:01"))
    assert MarkdownFormatter().compute_file_path(group) == "2026/01/2026-01-05-23-59-01.md"


# --- Merged groups ------------------------------------------------------


def _split_call():
    """One conversation captured as two adjacent recordings."""
    first = _make_recording(
        source_dir="1786959081",
        datetime="2026-08-17T09:31:21",
        duration=21000,
        result="I haven't talked to you in a while.",
        segments=[{"text": "I haven't talked to you in a while.", "start": 1.0, "end": 20.0}],
    )
    second = _make_recording(
        source_dir="1786959112",
        datetime="2026-08-17T09:31:52",
        duration=81000,
        result="Bring me up to speed.",
        segments=[{"text": "Bring me up to speed.", "start": 2.0, "end": 80.0}],
    )
    return first, second


def test_merged_file_path_uses_the_earliest_recording():
    """The path must not move when a later recording joins an existing group."""
    path = MarkdownFormatter().compute_file_path(_group(*_split_call()))
    assert path == "2026/08/2026-08-17-09-31-21.md"


def test_merged_frontmatter_lists_every_source():
    md = _format(*_split_call())
    assert "source_dirs:" in md
    assert '- "1786959081"' in md
    assert '- "1786959112"' in md
    assert "recording_count: 2" in md
    assert "source_dir: " not in md


def test_merged_duration_is_the_total():
    md = _format(*_split_call())
    assert "duration_ms: 102000" in md
    assert "1m 42s" in md


def test_merged_transcription_keeps_both_parts_in_order():
    md = _format(*_split_call())
    body = md.split("## Transcription", 1)[1]
    assert body.index("I haven't talked to you in a while.") < body.index("Bring me up to speed.")


def test_merged_segments_are_offset_to_the_group_start():
    """The second recording starts 31s after the first, so its 2.0s mark is 33.0s."""
    md = _format(*_split_call())
    assert "00:01.0" in md  # first recording, unshifted
    assert "00:33.0" in md  # second recording, shifted by 31s


def test_merged_note_marks_the_part_boundaries():
    md = _format(*_split_call())
    assert md.count("### Part ") == 2
