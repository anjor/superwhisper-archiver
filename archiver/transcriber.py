from pathlib import Path
from typing import Optional

import av

from .models import LocalTranscript, Segment


def audio_duration_ms(path: Path) -> int:
    with av.open(str(path)) as container:
        if container.duration is None:
            raise ValueError(f"{path} does not say how long it is")
        return container.duration * 1000 // av.time_base


class LocalTranscriber:
    """Most runs transcribe nothing, so faster-whisper is imported and the model
    loaded only when the first recording needs it.
    """

    def __init__(self, model: str):
        self.model = model
        self._whisper = None

    def __call__(self, audio_path: Path, language: Optional[str]) -> LocalTranscript:
        if self._whisper is None:
            self._whisper = self._load()
        segments, _ = self._whisper.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return LocalTranscript(
            model=self.model,
            segments=[
                Segment(text=s.text.strip(), start=s.start, end=s.end)
                for s in segments
                if s.text.strip()
            ],
        )

    def _load(self):
        from faster_whisper import WhisperModel

        # Loading by name asks Hugging Face for the latest files before using
        # the cache, and this runs exactly when the network is misbehaving.
        try:
            return WhisperModel(
                self.model, device="cpu", compute_type="int8", local_files_only=True
            )
        except Exception:
            return WhisperModel(self.model, device="cpu", compute_type="int8")
