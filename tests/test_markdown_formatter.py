from archiver.markdown_formatter import MarkdownFormatter
from archiver.models import Recording


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


def test_format_contains_frontmatter():
    rec = _make_recording()
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert md.startswith("---\n")
    assert "datetime: " in md
    assert "mode: meeting" in md.lower() or "mode: Meeting" in md
    assert "source_dir: " in md


def test_format_contains_transcription():
    rec = _make_recording()
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "## Transcription" in md
    assert "Hello world. How are you?" in md


def test_format_contains_segments():
    rec = _make_recording()
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "## Segments" in md
    assert "Hello world." in md
    assert "How are you?" in md


def test_format_contains_duration():
    rec = _make_recording(duration=90000)  # 90 seconds
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "1m 30s" in md


def test_format_with_llm_result():
    rec = _make_recording(llmResult="Summary: a greeting was exchanged.")
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "## Summary" in md
    assert "a greeting was exchanged" in md


def test_format_without_llm_result():
    rec = _make_recording()
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "## Summary" not in md


def test_compute_file_path():
    rec = _make_recording(datetime="2026-02-13T10:31:50")
    fmt = MarkdownFormatter()
    path = fmt.compute_file_path(rec)
    assert path == "2026/02/2026-02-13-10-31-50.md"


def test_compute_file_path_different_date():
    rec = _make_recording(datetime="2026-01-05T23:59:01")
    fmt = MarkdownFormatter()
    path = fmt.compute_file_path(rec)
    assert path == "2026/01/2026-01-05-23-59-01.md"


def test_format_duration_hours():
    rec = _make_recording(duration=3723000)  # 1h 2m 3s
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "1h 2m 3s" in md


def test_format_segments_timestamps():
    rec = _make_recording(
        segments=[{"text": "Hello", "start": 65.5, "end": 70.2}]
    )
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    # Should format as MM:SS.s
    assert "01:05.5" in md
    assert "01:10.2" in md
